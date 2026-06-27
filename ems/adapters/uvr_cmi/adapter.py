"""Read-only adaptér pro UVR16x2 přes CMI (JSON API, Basic auth). Stdlib only.

Telemetrie teplot akumulačních nádrží (Fáze 1: jen měření, žádné řízení).
CMI pustí max 1 dotaz/minutu na uzel → adaptér interně throttluje na 60 s
(kolektor volá read() každých ~10 s).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import urllib.request

from ems.core.model import Measurement, Quality, Reading, utcnow
from .mapping import is_bad, resolve_sensors

logger = logging.getLogger(__name__)


class UvrCmiAdapter:
    def __init__(self, device_id, host, user="admin", password="", node=2,
                 throttle_s=60, sensors=None, **_ignore):
        self.device_id = str(device_id)
        self.host = host
        self.user = user
        self.password = str(password)
        self.node = int(node)
        self.throttle_s = float(throttle_s)
        self.sensors = resolve_sensors(sensors)
        self._last_fetch = 0.0

    def _fetch(self) -> dict:
        url = f"http://{self.host}/INCLUDE/api.cgi?jsonnode={self.node}&jsonparam=I"
        req = urllib.request.Request(url)
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        req.add_header("Authorization", "Basic " + token)
        with urllib.request.urlopen(req, timeout=10) as r:   # noqa: S310 (interní LAN)
            return json.load(r)

    async def connect(self) -> None:
        # CMI je bezstavové HTTP — žádné trvalé spojení se nedrží.
        return None

    async def read(self) -> Reading:
        # CMI limit 1/min: mezi fetchi vrať prázdný odečet (nic se nezapíše)
        now = time.monotonic()
        if now - self._last_fetch < self.throttle_s:
            return Reading(device_id=self.device_id, measurements=[])
        self._last_fetch = now

        try:
            data = await asyncio.to_thread(self._fetch)
        except Exception as exc:
            logger.warning("CMI %s: čtení selhalo: %s", self.host, exc)
            return Reading(device_id=self.device_id, measurements=[])

        status = str(data.get("Status", "")).upper()
        if status and status != "OK":
            logger.warning("CMI %s node %s: status=%s", self.host, self.node, data.get("Status"))
            return Reading(device_id=self.device_id, measurements=[])

        inputs = {}
        for i in data.get("Data", {}).get("Inputs", []):
            try:
                inputs[int(i.get("Number"))] = i
            except (TypeError, ValueError):
                continue

        measurements = []
        for num, (metric, _role) in self.sensors.items():
            inp = inputs.get(int(num))
            if not inp:                                  # např. I13 chybí
                continue
            v = inp.get("Value", {}) or {}
            val, unit = v.get("Value"), str(v.get("Unit"))
            if val is None or is_bad(unit, val):         # sentinel → None (nevkládat)
                continue
            measurements.append(Measurement(metric=metric, value=float(val),
                                            unit="°C", quality=Quality.GOOD))
        return Reading(device_id=self.device_id, timestamp=utcnow(), measurements=measurements)

    async def close(self) -> None:
        pass
