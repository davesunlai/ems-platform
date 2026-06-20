"""Adaptér pro Solis S6-EH3P50K-H (třífázový HV hybrid) přes Modbus TCP.

Vzorováno 1:1 na `GoodweAdapter` — vrací PŘESNĚ STEJNÁ kanonická pole
telemetrie i znaménkové konvence (viz ems.core.model):

  PV_POWER       >= 0
  BATTERY_POWER  + = nabíjení,  − = vybíjení
  GRID_POWER     + = odběr ze sítě (import),  − = dodávka do sítě (export)

Read-only (monitoring). Holding registry (ovládání 0x03/0x06) jsou zatím
mimo rozsah — řešíme později jako samostatný zápisový modul.

Transport: čistý Modbus TCP (ne Solarman V5), lib `pymodbus` >= 3.13.
POZOR API pymodbus 3.13: read_input_registers(addr, *, count=N, device_id=U)
— count i device_id jsou keyword-only, starší `slave=` už neexistuje.
"""
from __future__ import annotations

import asyncio
import logging

from ems.core.model import DeviceType, Measurement, Metric, Reading, UNIT_OF, utcnow
from .mapping import BATTERY_PACKS, REG_ENERGY_TOTAL, REG_GRID_METER, REG_PV_POWER

logger = logging.getLogger(__name__)


def _decode(regs: list[int], rtype: str, scale: float) -> float:
    """Dekóduje surové registry podle typu (U16/S16/U32/S32) a měřítka."""
    if rtype == "u16":
        v = regs[0]
    elif rtype == "s16":
        v = regs[0] - 0x10000 if regs[0] >= 0x8000 else regs[0]
    elif rtype == "u32":
        v = (regs[0] << 16) | regs[1]
    elif rtype == "s32":
        v = (regs[0] << 16) | regs[1]
        if v >= 0x80000000:
            v -= 0x100000000
    else:
        raise ValueError(f"Neznámý typ registru: {rtype}")
    return v * scale


class SolisAdapter:
    def __init__(
        self,
        device_id: str,
        host: str,
        port: int = 502,
        unit: int = 1,
        device_type: str = "storage",
        battery_pack: int = 1,
        timeout: float = 3.0,
    ) -> None:
        self.device_id = device_id
        self.host = host
        self.port = int(port)
        self.unit = int(unit)            # Modbus device_id / unit (jedno spojení čte vše)
        self.device_type = str(device_type)
        self.battery_pack = int(battery_pack)
        self.timeout = float(timeout)
        self._client = None

    # --- spojení ---
    async def connect(self) -> None:
        await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
        from pymodbus.client import ModbusTcpClient  # lazy: jen pokud se solis použije

        self._client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
        if not self._client.connect():
            raise RuntimeError(f"Nelze se připojit k Solis {self.host}:{self.port}")
        logger.info(
            "Připojeno k Solis '%s' na %s:%s (unit=%s, typ=%s, pack=%s)",
            self.device_id, self.host, self.port, self.unit, self.device_type, self.battery_pack,
        )

    # --- čtení ---
    def _read_reg(self, spec: tuple) -> float:
        addr, rtype, scale = spec
        count = 2 if rtype in ("u32", "s32") else 1
        rr = self._client.read_input_registers(addr, count=count, device_id=self.unit)
        if rr.isError() or not getattr(rr, "registers", None):
            raise IOError(f"čtení registru {addr} selhalo: {rr}")
        return _decode(rr.registers, rtype, scale)

    def _read_pack(self, pack_id: int):
        """Vrátí (soc, voltage, current) battery packu; None u nepřečtených."""
        pack = BATTERY_PACKS.get(pack_id)
        if not pack:
            return (None, None, None)
        out = []
        for field in ("soc", "voltage", "current"):
            try:
                out.append(self._read_reg(pack[field]))
            except Exception as exc:
                logger.debug("Solis '%s' pack%s %s: %s", self.device_id, pack_id, field, exc)
                out.append(None)
        return tuple(out)

    async def read(self) -> Reading:
        return await asyncio.to_thread(self._read_sync)

    def _read_sync(self) -> Reading:
        if self._client is None or not getattr(self._client, "connected", False):
            self._connect_sync()

        measurements: list[Measurement] = []

        def add(metric: Metric, value: float) -> None:
            measurements.append(Measurement(metric=metric, value=float(value), unit=UNIT_OF[metric]))

        def add_system() -> None:
            # FVE + celková energie + síť (Solis +export/−import -> EMS +import/−export => OTOČIT)
            for metric, spec, transform in (
                (Metric.PV_POWER, REG_PV_POWER, None),
                (Metric.ENERGY_PV_TOTAL, REG_ENERGY_TOTAL, None),
                (Metric.GRID_POWER, REG_GRID_METER, lambda v: -v),
            ):
                try:
                    v = self._read_reg(spec)
                    add(metric, transform(v) if transform else v)
                except Exception as exc:
                    logger.debug("Solis '%s': reg %s (%s) nepřečten: %s", self.device_id, spec[0], metric, exc)

        def add_pack(pack_id: int) -> None:
            soc, volt, curr = self._read_pack(pack_id)
            if soc is not None:
                add(Metric.BATTERY_SOC, soc)
            if volt is not None:
                add(Metric.VOLTAGE, volt)
            if curr is not None:
                add(Metric.CURRENT, curr)
            # battery_power = U*I (W); znaménko nese proud: + nabíjení / − vybíjení (shodné s EMS)
            if volt is not None and curr is not None:
                add(Metric.BATTERY_POWER, volt * curr)

        dtype = self.device_type

        if dtype == DeviceType.GENERATION.value:
            add_system()

        elif dtype == DeviceType.STORAGE.value:
            add_pack(self.battery_pack)

        elif dtype == DeviceType.GRID_POINT.value:
            try:
                add(Metric.GRID_POWER, -self._read_reg(REG_GRID_METER))
            except Exception as exc:
                logger.debug("Solis '%s' grid: %s", self.device_id, exc)

        elif dtype == DeviceType.HYBRID.value:
            # Vše v jednom modulu: FVE + síť + energie + baterie (OBĚ packy agregovaně).
            add_system()
            socs, volts, currs, powers = [], [], [], []
            for pid in BATTERY_PACKS:
                soc, volt, curr = self._read_pack(pid)
                if soc is not None:
                    socs.append(soc)
                if volt is not None:
                    volts.append(volt)
                if curr is not None:
                    currs.append(curr)
                if volt is not None and curr is not None:
                    powers.append(volt * curr)
            if socs:
                add(Metric.BATTERY_SOC, sum(socs) / len(socs))   # průměr packů
            if volts:
                add(Metric.VOLTAGE, sum(volts) / len(volts))     # paralelní HV bus ≈ stejné
            if currs:
                add(Metric.CURRENT, sum(currs))                  # celkový proud baterie
            if powers:
                add(Metric.BATTERY_POWER, sum(powers))           # celkový výkon baterie
            # LOAD_POWER (domácí zátěž) a BACKUP: registry pro 3f model zatím
            # nepotvrzené (brief §9) -> doplníme po živém dočtení proti střídači.

        return Reading(device_id=self.device_id, timestamp=utcnow(), measurements=measurements)

    async def read_raw(self) -> dict:
        """Pomůcka pro ladění: přečte klíčové registry a vrátí surové hodnoty."""
        def _run() -> dict:
            if self._client is None or not getattr(self._client, "connected", False):
                self._connect_sync()
            out: dict = {}
            for name, spec in {
                "pv_power": REG_PV_POWER, "energy_total": REG_ENERGY_TOTAL, "grid_meter": REG_GRID_METER,
            }.items():
                try:
                    out[name] = self._read_reg(spec)
                except Exception as exc:
                    out[name] = f"ERR: {exc}"
            for pack_id, regs in BATTERY_PACKS.items():
                for field, spec in regs.items():
                    try:
                        out[f"bat{pack_id}_{field}"] = self._read_reg(spec)
                    except Exception as exc:
                        out[f"bat{pack_id}_{field}"] = f"ERR: {exc}"
            return out

        return await asyncio.to_thread(_run)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.close)
            except Exception:
                pass
            self._client = None
