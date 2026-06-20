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
from .mapping import (
    BATTERY_PACKS, BLOCK_BAT1, BLOCK_BAT2, BLOCK_GRID, BLOCK_SYS1, BLOCK_SYS2,
    REG_ENERGY_TODAY, REG_ENERGY_TOTAL, REG_GRID_METER,
    REG_GRID_V_L1, REG_GRID_V_L2, REG_GRID_V_L3, REG_INV_TEMP, REG_PV_POWER,
)

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
        battery_packs="auto",
        timeout: float = 3.0,
    ) -> None:
        self.device_id = device_id
        self.host = host
        self.port = int(port)
        self.unit = int(unit)            # Modbus device_id / unit (jedno spojení čte vše)
        self.device_type = str(device_type)
        self.battery_pack = int(battery_pack)
        self.battery_packs = battery_packs   # hybrid: "auto" | 1 | 2 (počet packů)
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

    def _reconnect(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._connect_sync()

    # --- čtení ---
    def _read_reg(self, spec: tuple, _retry: bool = True) -> float:
        addr, rtype, scale = spec
        count = 2 if rtype in ("u32", "s32") else 1
        try:
            rr = self._client.read_input_registers(addr, count=count, device_id=self.unit)
        except Exception:
            # výjimka = socket nejspíš spadl (často po předchozím nevalidním čtení
            # tentýž cyklus). Reconnectni a zkus JEN tento registr ještě jednou,
            # ať jeden vadný registr neotráví čtení ostatních (hybrid, pack 2…).
            if _retry:
                self._reconnect()
                return self._read_reg(spec, _retry=False)
            raise
        if rr.isError() or not getattr(rr, "registers", None):
            # chybová ODPOVĚĎ (např. illegal address) — socket je v pořádku,
            # další registry půjdou číst dál; jen tento přeskočíme.
            raise IOError(f"čtení registru {addr} selhalo: {rr}")
        return _decode(rr.registers, rtype, scale)

    def _read_block(self, start: int, count: int, _retry: bool = True) -> list:
        """Přečte souvislý blok registrů (1 dotaz). Reconnect+retry na výjimku."""
        try:
            rr = self._client.read_input_registers(start, count=count, device_id=self.unit)
        except Exception:
            if _retry:
                self._reconnect()
                return self._read_block(start, count, _retry=False)
            raise
        if rr.isError() or not getattr(rr, "registers", None):
            raise IOError(f"blok {start}+{count} selhal: {rr}")
        return rr.registers

    def _load(self, blocks: list) -> dict:
        """Načte zadané bloky do mapy {adresa: u16}. Selhání bloku se přeskočí."""
        if self._client is None or not getattr(self._client, "connected", False):
            self._connect_sync()
        cache: dict = {}
        for start, count in blocks:
            try:
                regs = self._read_block(start, count)
                for i, v in enumerate(regs):
                    cache[start + i] = v
            except Exception as exc:
                logger.debug("Solis '%s' blok %s+%s: %s", self.device_id, start, count, exc)
        return cache

    @staticmethod
    def _dec(cache: dict, spec: tuple):
        """Dekóduje veličinu z cache; None pokud registry v cache nejsou."""
        addr, rtype, scale = spec
        if rtype in ("u32", "s32"):
            if addr not in cache or addr + 1 not in cache:
                return None
            return _decode([cache[addr], cache[addr + 1]], rtype, scale)
        if addr not in cache:
            return None
        return _decode([cache[addr]], rtype, scale)

    async def read(self) -> Reading:
        return await asyncio.to_thread(self._read_sync)

    def _read_sync(self) -> Reading:
        dtype = self.device_type

        # vyber bloky podle typu zařízení (méně dotazů = šetrnější k měniči)
        blocks = []
        if dtype in (DeviceType.GENERATION.value, DeviceType.HYBRID.value):
            blocks += [BLOCK_SYS1, BLOCK_SYS2, BLOCK_GRID]
        if dtype == DeviceType.GRID_POINT.value:
            blocks += [BLOCK_GRID]
        if dtype == DeviceType.STORAGE.value:
            blocks += [BLOCK_BAT1 if self.battery_pack != 2 else BLOCK_BAT2]
        if dtype == DeviceType.HYBRID.value:
            blocks += [BLOCK_BAT1, BLOCK_BAT2]
        cache = self._load(blocks)

        measurements: list[Measurement] = []

        def add(metric: Metric, value) -> None:
            if value is not None:
                measurements.append(Measurement(metric=metric, value=float(value), unit=UNIT_OF[metric]))

        def add_system() -> None:
            add(Metric.PV_POWER, self._dec(cache, REG_PV_POWER))
            add(Metric.ENERGY_PV_TOTAL, self._dec(cache, REG_ENERGY_TOTAL))
            add(Metric.ENERGY_TODAY, self._dec(cache, REG_ENERGY_TODAY))
            g = self._dec(cache, REG_GRID_METER)
            add(Metric.GRID_POWER, -g if g is not None else None)   # Solis +export -> EMS +import
            add(Metric.GRID_VOLTAGE_L1, self._dec(cache, REG_GRID_V_L1))
            add(Metric.GRID_VOLTAGE_L2, self._dec(cache, REG_GRID_V_L2))
            add(Metric.GRID_VOLTAGE_L3, self._dec(cache, REG_GRID_V_L3))
            add(Metric.TEMPERATURE, self._dec(cache, REG_INV_TEMP))  # teplota měniče

        def pack_fields(pid: int) -> dict:
            return {f: self._dec(cache, spec) for f, spec in (BATTERY_PACKS.get(pid) or {}).items()}

        if dtype == DeviceType.GENERATION.value:
            add_system()

        elif dtype == DeviceType.STORAGE.value:
            d = pack_fields(self.battery_pack)
            add(Metric.BATTERY_SOC, d.get("soc"))
            add(Metric.VOLTAGE, d.get("voltage"))
            add(Metric.CURRENT, d.get("current"))
            if d.get("voltage") is not None and d.get("current") is not None:
                add(Metric.BATTERY_POWER, d["voltage"] * d["current"])

        elif dtype == DeviceType.GRID_POINT.value:
            g = self._dec(cache, REG_GRID_METER)
            add(Metric.GRID_POWER, -g if g is not None else None)

        elif dtype == DeviceType.HYBRID.value:
            add_system()
            soc_m = {1: Metric.BATTERY_SOC_1, 2: Metric.BATTERY_SOC_2}
            volt_m = {1: Metric.BATTERY_VOLTAGE_1, 2: Metric.BATTERY_VOLTAGE_2}
            curr_m = {1: Metric.BATTERY_CURRENT_1, 2: Metric.BATTERY_CURRENT_2}
            pow_m = {1: Metric.BATTERY_POWER_1, 2: Metric.BATTERY_POWER_2}
            soh_m = {1: Metric.BATTERY_SOH_1, 2: Metric.BATTERY_SOH_2}
            temp_m = {1: Metric.BATTERY_TEMP_1, 2: Metric.BATTERY_TEMP_2}
            explicit = str(self.battery_packs).isdigit()
            candidates = ([p for p in range(1, int(self.battery_packs) + 1) if p in BATTERY_PACKS]
                          if explicit else list(BATTERY_PACKS))   # "auto" -> zkus všechny
            socs, powers = [], []
            for pid in candidates:
                d = pack_fields(pid)
                soc = d.get("soc")
                if soc is None or (not explicit and not (0 < soc <= 100)):
                    continue   # auto: pack bez platného SOC fyzicky není
                add(soc_m[pid], soc)
                socs.append(soc)
                volt, curr = d.get("voltage"), d.get("current")
                add(volt_m[pid], volt)
                add(curr_m[pid], curr)
                if volt is not None and curr is not None:
                    p = volt * curr
                    add(pow_m[pid], p)
                    powers.append(p)
                add(soh_m[pid], d.get("soh"))
                add(temp_m[pid], d.get("temp"))
            if socs:
                add(Metric.BATTERY_SOC, sum(socs) / len(socs))   # průměr (pro souhrn)
            if powers:
                add(Metric.BATTERY_POWER, sum(powers))           # součet (pro graf/souhrn)
            # LOAD_POWER / BACKUP: registry pro 3f model zatím nepotvrzené (brief §9).

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
