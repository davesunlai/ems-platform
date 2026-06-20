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

    async def read(self) -> Reading:
        return await asyncio.to_thread(self._read_sync)

    def _read_sync(self) -> Reading:
        if self._client is None or not getattr(self._client, "connected", False):
            self._connect_sync()

        measurements: list[Measurement] = []

        def add(metric: Metric, value: float) -> None:
            measurements.append(Measurement(metric=metric, value=float(value), unit=UNIT_OF[metric]))

        def try_metric(metric: Metric, spec: tuple, transform=None) -> None:
            try:
                v = self._read_reg(spec)
                add(metric, transform(v) if transform else v)
            except Exception as exc:
                logger.debug("Solis '%s': reg %s (%s) nepřečten: %s", self.device_id, spec[0], metric, exc)

        dtype = self.device_type

        if dtype == DeviceType.GENERATION.value:
            try_metric(Metric.PV_POWER, REG_PV_POWER)
            try_metric(Metric.ENERGY_PV_TOTAL, REG_ENERGY_TOTAL)
            # Solis +export/−import  ->  EMS +import/−export  => OTOČIT znaménko
            try_metric(Metric.GRID_POWER, REG_GRID_METER, transform=lambda v: -v)

        elif dtype == DeviceType.STORAGE.value:
            pack = BATTERY_PACKS.get(self.battery_pack, BATTERY_PACKS[1])
            soc = volt = curr = None
            try:
                soc = self._read_reg(pack["soc"])
            except Exception as exc:
                logger.debug("Solis SOC pack%s: %s", self.battery_pack, exc)
            try:
                volt = self._read_reg(pack["voltage"])
            except Exception as exc:
                logger.debug("Solis U pack%s: %s", self.battery_pack, exc)
            try:
                curr = self._read_reg(pack["current"])
            except Exception as exc:
                logger.debug("Solis I pack%s: %s", self.battery_pack, exc)

            if soc is not None:
                add(Metric.BATTERY_SOC, soc)
            if volt is not None:
                add(Metric.VOLTAGE, volt)
            if curr is not None:
                add(Metric.CURRENT, curr)
            # battery_power = U*I (W); znaménko nese proud: + nabíjení / − vybíjení
            # (shodné s EMS i goodwe — neotáčíme)
            if volt is not None and curr is not None:
                add(Metric.BATTERY_POWER, volt * curr)

        elif dtype == DeviceType.GRID_POINT.value:
            try_metric(Metric.GRID_POWER, REG_GRID_METER, transform=lambda v: -v)

        # LOAD_POWER: registr výkonu domácí zátěže není pro 3f model potvrzen
        # (brief §9 — jednofázoví kandidáti nesedí). Doplníme po živém dočtení.

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
