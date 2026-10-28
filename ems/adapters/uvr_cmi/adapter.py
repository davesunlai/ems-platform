"""Read-only adaptér pro UVR16x2 přes CMI (JSON API, Basic auth). Stdlib only.

Čtení (v1.5.2+): CMI pustí max 1 dotaz/min na uzel → sloty po `throttle_s` (60 s) se střídají
  I (čidla + digitální vstupy) · O (výstupy O1–O9, čerpadlo AKU1↔2 = O6) — každé à 2 min.
Read-only (rozhodnutí 28. 10.): do UVR se nezapisuje; práh F6 se mění na displeji regulátoru.
Viz UVR-TAPPS2-BRIEF.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import urllib.request

from ems.core.model import Measurement, Metric, Quality, Reading, utcnow
from .mapping import is_bad, resolve_sensors

logger = logging.getLogger(__name__)

DEFAULT_OUTPUTS = {6: Metric.AKU_PUMP}                     # který výstup je fyzicky čerpadlo AKU1↔2 (ověřuje se, viz brief)
ALL_OUTPUTS = {n: _m for n, _m in ((1, Metric.UVR_O1), (2, Metric.UVR_O2), (3, Metric.UVR_O3), (4, Metric.UVR_O4), (5, Metric.UVR_O5),
                                   (6, Metric.UVR_O6), (7, Metric.UVR_O7), (8, Metric.UVR_O8), (9, Metric.UVR_O9))}
DIGITAL_INPUTS = {10: Metric.UVR_D10, 12: Metric.UVR_D12}  # Jablotron: sepnutí topení / radiátorů
_METRIC_BY_NAME = {m.value: m for m in Metric}


def _resolve(cfg, default: dict) -> dict:
    if not cfg:
        return default
    out = {}
    for k, v in cfg.items():
        try:
            m = _METRIC_BY_NAME.get(v if isinstance(v, str) else (v or {}).get("metric"))
            if m is not None:
                out[int(k)] = m
        except (TypeError, ValueError):
            continue
    return out or default


def _loads_tolerant(raw: bytes) -> dict:
    """CMI u prázdných seznamů (Na/Nd) vrací nevalidní JSON (čárka před ]) — opravíme."""
    txt = raw.decode("utf-8", "replace")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        fixed = re.sub(r",\s*([\]}])", r"\1", txt)
        return json.loads(fixed)


class UvrCmiAdapter:
    def __init__(self, device_id, host, user="admin", password="", node=2,
                 throttle_s=60, sensors=None, outputs=None, **_ignore):
        self.device_id = str(device_id)
        self.host = host
        self.user = user
        self.password = str(password)
        self.node = int(node)
        self.throttle_s = max(1.0, float(throttle_s))
        self.sensors = resolve_sensors(sensors)
        self.outputs = _resolve(outputs, DEFAULT_OUTPUTS)
        self._last_fetch = 0.0
        self._last_bucket = -1          # zarovnání na celé minuty wall-clock (bez driftu → žádné vynechané minuty)
        self._slot = 0

    # --- HTTP JSON API -------------------------------------------------------
    def _fetch(self, param: str = "I") -> dict:
        url = f"http://{self.host}/INCLUDE/api.cgi?jsonnode={self.node}&jsonparam={param}"
        req = urllib.request.Request(url)
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        req.add_header("Authorization", "Basic " + token)
        with urllib.request.urlopen(req, timeout=10) as r:   # noqa: S310 (interní LAN)
            return _loads_tolerant(r.read())

    async def connect(self) -> None:
        return None   # bezstavové HTTP

    @staticmethod
    def _by_number(data: dict, key_hint: str | None = None) -> dict[int, dict]:
        """{Number: item} z Data[<první seznam>] (klíč se liší: Inputs/Outputs/Network Analog…)."""
        d = data.get("Data", {}) or {}
        lst = d.get(key_hint) if key_hint and isinstance(d.get(key_hint), list) else None
        if lst is None:
            lst = next((v for v in d.values() if isinstance(v, list)), [])
        out = {}
        for i in lst:
            try:
                out[int(i.get("Number"))] = i
            except (TypeError, ValueError):
                continue
        return out

    async def _get(self, param: str) -> dict[int, dict] | None:
        try:
            data = await asyncio.to_thread(self._fetch, param)
        except Exception as exc:
            logger.warning("CMI %s param %s: čtení selhalo: %s", self.host, param, exc)
            return None
        status = str(data.get("Status", "")).upper()
        if status and status != "OK":
            logger.warning("CMI %s node %s param %s: status=%s", self.host, self.node, param, data.get("Status"))
            return None
        return self._by_number(data)

    async def read(self) -> Reading:
        # Slot = celá minuta wall-clock (int(time/throttle)); dřív monotonic+60 s driftoval a každých ~70 min
        # vynechal minutu (lekce 28. 10.). Dotaz jde v první iteraci každé nové minuty (~2 s po začátku).
        bucket = int((time.time() - 2) // self.throttle_s)
        if bucket == self._last_bucket:
            return Reading(device_id=self.device_id, measurements=[])
        self._last_bucket = bucket
        self._last_fetch = time.monotonic()
        slot = self._slot
        self._slot += 1
        measurements: list[Measurement] = []

        if slot % 2 == 0:                                     # čidla (každý druhý slot = à 2 min)
            items = await self._get("I")
            if items is None:
                return Reading(device_id=self.device_id, measurements=[])
            for num, (metric, _role) in self.sensors.items():
                inp = items.get(int(num))
                if not inp:
                    continue
                v = inp.get("Value", {}) or {}
                val, unit = v.get("Value"), str(v.get("Unit"))
                if val is None or is_bad(unit, val):
                    continue
                measurements.append(Measurement(metric=metric, value=float(val), unit="°C", quality=Quality.GOOD))
            for num, metric in DIGITAL_INPUTS.items():     # digitální vstupy (0/1) — spouštěče topných okruhů
                inp = items.get(num)
                val = ((inp or {}).get("Value") or {}).get("Value") if inp else None
                if val is not None and (inp.get("AD") == "D" or val in (0, 1)):
                    measurements.append(Measurement(metric=metric, value=float(val), unit="", quality=Quality.GOOD))
        else:                                                 # výstupy (0/1) — à 2 min
            items = await self._get("O")
            for num, it in (items or {}).items():            # všechny výstupy O1–O9 (0/1)
                val = ((it.get("Value") or {}).get("Value"))
                if val is None or num not in ALL_OUTPUTS:
                    continue
                measurements.append(Measurement(metric=ALL_OUTPUTS[num], value=float(val), unit="", quality=Quality.GOOD))
                if num in self.outputs:                       # + alias „čerpadlo AKU1↔2" dle konfigurace
                    measurements.append(Measurement(metric=self.outputs[num], value=float(val), unit="", quality=Quality.GOOD))
        return Reading(device_id=self.device_id, timestamp=utcnow(), measurements=measurements)



    async def close(self) -> None:
        pass
