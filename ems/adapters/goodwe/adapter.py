"""Adaptér pro Goodwe měniče (ET hybrid i DT grid-tie).

Staví na knihovně `goodwe` (https://github.com/marcelblijleven/goodwe),
která sama detekuje rodinu měniče a komunikuje přes UDP port 8899
nebo Modbus/TCP port 502. Funguje přes OpenVPN tunel na lokální IP měniče.

Read-only (monitoring). Řízení (set_operation_mode apod.) přidáme jako
samostatný krok až po validaci telemetrie.
"""
from __future__ import annotations

import logging

from ems.core.model import Measurement, Reading, UNIT_OF, utcnow
from .mapping import GOODWE_METRIC_MAP

logger = logging.getLogger(__name__)


class GoodweAdapter:
    def __init__(
        self,
        device_id: str,
        host: str,
        port: int = 8899,
        comm_addr: int | None = None,
        timeout: float = 2.0,
        retries: int = 3,
    ) -> None:
        self.device_id = device_id
        self.host = host
        self.port = port
        self.comm_addr = comm_addr
        self.timeout = timeout
        self.retries = retries
        self._inverter = None

    async def connect(self) -> None:
        import goodwe  # lazy import: mock režim tak nepotřebuje tuto závislost

        kwargs: dict = {"port": self.port, "timeout": self.timeout, "retries": self.retries}
        if self.comm_addr is not None:
            kwargs["comm_addr"] = self.comm_addr
        self._inverter = await goodwe.connect(self.host, **kwargs)
        logger.info(
            "Připojeno k Goodwe '%s' na %s:%s (model=%s, sériové=%s)",
            self.device_id, self.host, self.port,
            getattr(self._inverter, "model_name", "?"),
            getattr(self._inverter, "serial_number", "?"),
        )

    async def read(self) -> Reading:
        if self._inverter is None:
            raise RuntimeError("Adaptér není připojen — zavolej nejdřív connect().")
        raw = await self._inverter.read_runtime_data()
        reading = self._to_reading(raw)
        # provozní režim (např. ECO_CHARGE při nuceném nabíjení) jako stav
        try:
            mode = await self._inverter.get_operation_mode()
            if mode is not None:
                reading.states = {"operation_mode": mode.name}
        except Exception:
            pass  # DT a jiné rodiny režim nemají
        return reading

    async def read_raw(self) -> dict:
        """Vrátí surový dict všech sensorů — pro ladění a discovery."""
        if self._inverter is None:
            raise RuntimeError("Adaptér není připojen — zavolej nejdřív connect().")
        return await self._inverter.read_runtime_data()

    def _to_reading(self, raw: dict) -> Reading:
        measurements: list[Measurement] = []
        for metric, candidates in GOODWE_METRIC_MAP.items():
            for sensor_id in candidates:
                value = raw.get(sensor_id)
                if value is not None:
                    try:
                        measurements.append(
                            Measurement(metric=metric, value=float(value), unit=UNIT_OF[metric])
                        )
                    except (TypeError, ValueError):
                        logger.debug("Nelze převést %s=%r na float", sensor_id, value)
                    break
        return Reading(device_id=self.device_id, timestamp=utcnow(), measurements=measurements)

    async def close(self) -> None:
        self._inverter = None
