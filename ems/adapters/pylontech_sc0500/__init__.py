"""Pylontech SC0500 (řídicí jednotka HV bloku H48050, PowerCube) — BMS přes RS485 / Modbus RTU. JEN ČTENÍ.

Mapa registrů není z dokumentace výrobce: byla nalezena průchodem 21. 11. 2026 na pilotu (blok B1, 9600 Bd 8N1, adresa 1)
a ověřena křížově (min/max článků ↔ tabulka článků, součet napětí modulů ↔ napětí bloku, proud ↔ výkon nabíjení).
Funkce 03 i 04 vrací totéž; používá se 04.

  4355        napětí bloku ×0,1 V              4357  proud ×0,01 A (znaménko při vybíjení K OVĚŘENÍ)
  4359        SoC %                            4368/4369  max / min napětí článku mV
  4370/4371   index (od 0) článku max / min    4372/4373  max / min teplota ×0,1 °C
  4406/4407   počet modulů / článků
  5216+       napětí modulů ×0,01 V            5296+  teploty modulů ×0,1 °C
  5376+       napětí článků mV (165)           6144+  teploty u článků ×0,1 °C (165)
"""
from __future__ import annotations

import asyncio
import logging
import time

from ems.core.interfaces import TelemetryAdapter
from ems.core.model import Measurement, Metric, Reading, UNIT_OF

logger = logging.getLogger(__name__)

REG_SUMMARY = (4352, 60)        # 4352..4411
REG_MODULE_V, REG_MODULE_T = 5216, 5296
REG_CELL_V, REG_CELL_T = 5376, 6144
MAX_CELLS, MAX_MODULES = 400, 40
CELLS_EVERY_S = 55.0            # články 1× za minutu (server ukládá 1×/5 min, při testu baterie 1×/min)


def _s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


class PylontechSc0500Adapter(TelemetryAdapter):
    def __init__(self, device_id: str, serial_port: str | None = None, baudrate: int = 9600, parity: str = "N",
                 stopbits: int = 1, bytesize: int = 8, unit: int = 1, host: str | None = None, port: int = 502,
                 timeout: float = 2.0, **_ignored) -> None:
        self.device_id = device_id
        self.serial_port, self.host, self.port = serial_port, host, int(port)
        self.baudrate, self.parity = int(baudrate), str(parity or "N").upper()[:1]
        self.stopbits, self.bytesize = int(stopbits), int(bytesize)
        self.unit, self.timeout = int(unit), float(timeout)
        self._client = None
        self._last_cells = 0.0

    async def connect(self) -> None:
        await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
        if self.serial_port:
            from pymodbus.client import ModbusSerialClient
            self._client = ModbusSerialClient(port=self.serial_port, baudrate=self.baudrate, parity=self.parity,
                                              stopbits=self.stopbits, bytesize=self.bytesize, timeout=self.timeout)
        elif self.host:
            from pymodbus.client import ModbusTcpClient
            self._client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
        else:
            raise RuntimeError("Pylontech SC0500: chybí serial_port (RS485) nebo host")
        if not self._client.connect():
            raise RuntimeError(f"Pylontech SC0500 '{self.device_id}': nelze otevřít {self.serial_port or self.host}")
        logger.info("Připojeno k BMS SC0500 '%s' (%s, %s Bd, unit=%s)", self.device_id, self.serial_port or self.host, self.baudrate, self.unit)

    async def close(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._client = None

    def _block(self, start: int, count: int) -> list[int]:
        """Souvislý rozsah po kusech ≤ 100 registrů (limit Modbus rámce 125)."""
        out: list[int] = []
        for off in range(0, count, 100):
            n = min(100, count - off)
            rr = self._client.read_input_registers(start + off, count=n, device_id=self.unit)
            if rr.isError() or not getattr(rr, "registers", None) or len(rr.registers) < n:
                raise IOError(f"SC0500 blok {start + off}+{n} selhal: {rr}")
            out += list(rr.registers)
        return out

    async def read(self) -> Reading:
        return await asyncio.to_thread(self._read_sync)

    async def read_live(self) -> Reading:
        """Živé sledování: souhrn + napětí všech článků hned. Teploty se živě nečtou (mění se pomalu) —
        ty dál chodí s běžným čtením 1× za minutu, takže živé čtení zatěžuje linku zhruba poloviční dobu."""
        return await asyncio.to_thread(self._read_sync, True)

    def _read_sync(self, live: bool = False) -> Reading:
        if self._client is None or not getattr(self._client, "connected", False):
            self._connect_sync()
        s = self._block(*REG_SUMMARY)
        g = lambda reg: s[reg - REG_SUMMARY[0]]
        out: list[Measurement] = []

        def add(metric: Metric, value) -> None:
            if value is not None:
                out.append(Measurement(metric=metric, value=float(value), unit=UNIT_OF[metric]))

        vmax, vmin = g(4368), g(4369)
        add(Metric.BMS_VOLTAGE, g(4355) / 10.0)
        add(Metric.BMS_CURRENT, _s16(g(4357)) / 100.0)
        add(Metric.BMS_SOC, g(4359))
        if 1000 < vmin <= vmax < 5000:
            add(Metric.BMS_CELL_VMAX, vmax / 1000.0)
            add(Metric.BMS_CELL_VMIN, vmin / 1000.0)
            add(Metric.BMS_CELL_NMAX, g(4370) + 1)
            add(Metric.BMS_CELL_NMIN, g(4371) + 1)
            add(Metric.BMS_CELL_DELTA_MV, vmax - vmin)
        add(Metric.BMS_TEMP_MAX, _s16(g(4372)) / 10.0)
        add(Metric.BMS_TEMP_MIN, _s16(g(4373)) / 10.0)
        modules, cells = g(4406), g(4407)
        arrays: dict[str, list[float]] = {}
        now = time.monotonic()
        full = now - self._last_cells >= CELLS_EVERY_S
        if 0 < cells <= MAX_CELLS and 0 < modules <= MAX_MODULES and (full or live):
            try:
                arrays["bms_cells_mv"] = [float(v) for v in self._block(REG_CELL_V, cells)]
                arrays["bms_modules_cv"] = [float(v) for v in self._block(REG_MODULE_V, modules)]
                if full:
                    arrays["bms_cells_temp"] = [float(_s16(v)) for v in self._block(REG_CELL_T, cells)]
                    arrays["bms_modules_temp"] = [float(_s16(v)) for v in self._block(REG_MODULE_T, modules)]
                    self._last_cells = now
            except Exception as exc:                       # souhrn pošli i když články zrovna nejdou
                logger.info("SC0500 '%s': články nepřečteny: %s", self.device_id, exc)
                arrays = {}
        return Reading(device_id=self.device_id, measurements=out, arrays=arrays)
