"""Adaptér pro wallbox go-e Charger CORE / Gemini (HTTP API v2, lokální, bez autentizace).

Ověřeno živě 31. 10. 2026 na CORE FW 60.4 (GOE-ADAPTER-BRIEF §0/§7): čtení `/api/status?filter=…`
(18 klíčů) i zápisy `/api/set?amp=&psm=&frc=` (JSON hodnoty, odpověď `{"klíč": true|"chyba"}`).
Žádný Modbus/OCPP/MQTT. Stdlib only (urllib) — stejný kód běží v kolektoru i v EMSBOXu.

Poll: `poll_s` (30 s) v klidu, `poll_active_s` (10 s) při nabíjení (car=2) — kvůli regulaci pod jistič.
Zápisy jen při změně, `amp`/`psm` min. 60 s od sebe (flash ~100k cyklů), on/off přes `frc`.
Snapshot pro ev_telemetry je v `self._last` (vzor Stiebel ISG → hp_telemetry).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request

from ems.core.model import Measurement, Metric, Reading, UNIT_OF

logger = logging.getLogger(__name__)

# `cbl` ve filtru FW 60.4 vrací HTTP 400 (ověřeno 31. 10.) → nečteme; limit kabelu je obsažen v `acu`.
FILTER_KEYS = ("car", "alw", "acu", "amp", "ama", "psm", "frc", "lmo", "modelStatus", "err",
               "nrg", "eto", "wh", "trx", "pnp", "tma", "rbt")
CAR_STATE = {0: "unknown", 1: "idle", 2: "charging", 3: "wait_car", 4: "complete", 5: "error"}
MIN_WRITE_GAP_S = 60.0          # amp/psm: flash šetrnost (brief §3)

# modelStatus → česky (brief §9); výběr, zbytek jako číslo
MODEL_STATUS_CZ = {
    0: "bez řídicích dat", 1: "přehřátí", 2: "čeká na přístup (RFID)", 3: "vynuceno ZAP", 4: "vynuceno VYP",
    5: "plánovač nabíječky", 6: "limit energie dosažen", 7: "Awattar – levná cena", 12: "PV přebytek",
    13: "fallback go-e výchozí", 14: "fallback go-e plánovač", 15: "fallback – nabíjí (výchozí)",
    16: "fallback Awattar (nenabíjí)", 17: "fallback AutomaticStop (nenabíjí)", 19: "keep-alive kompatibility",
    20: "pauza není povolena", 22: "simulace odpojení", 23: "přepínání fází", 24: "min. doba pauzy",
    26: "chyba", 27: "load management nechce", 28: "OCPP nechce", 29: "zpoždění po připojení",
    30: "blokováno adaptérem", 31: "podfrekvenční regulace", 32: "nesymetrie zátěže",
    33: "vybíjení PV baterie", 34: "monitoring sítě", 35: "OCPP fallback",
}


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


class GoeChargerAdapter:
    def __init__(self, device_id: str, host: str, port: int = 80, poll_s: float = 30.0,
                 poll_active_s: float = 10.0, timeout: float = 5.0, **_ignored):
        self.device_id = str(device_id)
        self.host = host
        self.port = int(port or 80)
        self.poll_s = float(poll_s)
        self.poll_active_s = float(poll_active_s)
        self.timeout = float(timeout)
        self._last_poll = 0.0
        self._last: dict | None = None          # poslední snapshot (ev_telemetry)
        self._last_write: dict[str, float] = {}  # klíč → monotonic poslední zápis
        self._last_set: dict = {}               # klíč → naposledy zapsaná hodnota
        self.last_ok = None
        self.last_error = None

    # --- HTTP ---------------------------------------------------------------
    def _url(self, path: str, query: dict | None = None) -> str:
        q = ("?" + urllib.parse.urlencode(query, safe=",:[]{}\"")) if query else ""
        return f"http://{self.host}:{self.port}{path}{q}"

    def _get(self, path: str, query: dict | None = None) -> dict:
        req = urllib.request.Request(self._url(path, query), headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:   # noqa: S310 (LAN)
            return json.loads(r.read().decode("utf-8"))

    def _fetch(self) -> dict:
        return self._get("/api/status", {"filter": ",".join(FILTER_KEYS)})

    async def connect(self) -> None:
        return None   # bezstavové HTTP

    async def close(self) -> None:
        return None

    # --- čtení ----------------------------------------------------------------
    @staticmethod
    def parse(raw: dict) -> dict:
        """Surový JSON → plochý snapshot (klíče ev_telemetry)."""
        nrg = raw.get("nrg") or []
        n = (lambda i: _f(nrg[i]) if i < len(nrg) else None)
        d = {
            "car": raw.get("car"), "car_state": CAR_STATE.get(raw.get("car") if raw.get("car") is not None else -1, "unknown"),
            "allowed": raw.get("alw"), "amp_set": raw.get("amp"), "amp_max": raw.get("ama"), "amp_allowed": raw.get("acu"),
            "phase_mode": raw.get("psm"), "force": raw.get("frc"), "logic_mode": raw.get("lmo"),
            "model_status": raw.get("modelStatus"), "error": raw.get("err"),
            "u_l1": n(0), "u_l2": n(1), "u_l3": n(2), "u_n": n(3),
            "i_l1": n(4), "i_l2": n(5), "i_l3": n(6),
            "p_l1": n(7), "p_l2": n(8), "p_l3": n(9), "p_n": n(10), "power_w": n(11),
            "pf_l1": n(12), "pf_l2": n(13), "pf_l3": n(14),
            "energy_total_wh": _f(raw.get("eto")), "session_wh": _f(raw.get("wh")),
            "transaction": raw.get("trx"), "phases_active": raw.get("pnp"), "cable_limit_a": raw.get("cbl"),
            "uptime_ms": raw.get("rbt"),
        }
        tma = [t for t in (raw.get("tma") or []) if isinstance(t, (int, float))]
        d["temp_c"] = max(tma) if tma else None
        d["model_status_cz"] = MODEL_STATUS_CZ.get(d["model_status"], str(d["model_status"]))
        return d

    async def read(self) -> Reading:
        now = time.monotonic()
        active = bool(self._last and self._last.get("car") == 2)
        gap = self.poll_active_s if active else self.poll_s
        if now - self._last_poll < gap:
            return Reading(device_id=self.device_id, measurements=[])
        self._last_poll = now
        try:
            raw = await asyncio.to_thread(self._fetch)
            self.last_ok = time.monotonic()
            self.last_error = None
        except Exception as exc:
            logger.warning("go-e %s: čtení selhalo: %s", self.host, exc)
            self.last_error = str(exc)
            if self.last_ok is None:
                self.last_ok = time.monotonic() - 1
            return Reading(device_id=self.device_id, measurements=[])
        d = self.parse(raw)
        prev = self._last
        if prev and d.get("uptime_ms") is not None and prev.get("uptime_ms") is not None \
                and d["uptime_ms"] < prev["uptime_ms"]:
            d["rebooted"] = True               # rbt klesl → nabíječka restartovala (re-apply cíle; krok 3)
            logger.warning("go-e %s: detekován restart nabíječky (rbt %s → %s)", self.host, prev["uptime_ms"], d["uptime_ms"])
        self._last = d

        ms: list[Measurement] = []

        def add(metric: Metric, key: str, scale: float = 1.0):
            v = d.get(key)
            if v is not None:
                try:
                    ms.append(Measurement(metric=metric, value=float(v) * scale, unit=UNIT_OF[metric]))
                except (TypeError, ValueError):
                    pass
        add(Metric.EV_POWER, "power_w")
        add(Metric.EV_CURRENT_L1, "i_l1"); add(Metric.EV_CURRENT_L2, "i_l2"); add(Metric.EV_CURRENT_L3, "i_l3")
        add(Metric.EV_VOLTAGE_L1, "u_l1"); add(Metric.EV_VOLTAGE_L2, "u_l2"); add(Metric.EV_VOLTAGE_L3, "u_l3")
        add(Metric.EV_SESSION_KWH, "session_wh", 0.001)
        add(Metric.EV_ENERGY_TOTAL, "energy_total_wh", 0.001)
        add(Metric.EV_CAR_STATE, "car"); add(Metric.EV_AMP_SET, "amp_set"); add(Metric.EV_AMP_ALLOWED, "amp_allowed")
        add(Metric.EV_PHASE_MODE, "phase_mode"); add(Metric.EV_FORCE, "force"); add(Metric.EV_PHASES_ACTIVE, "phases_active")
        add(Metric.EV_MODEL_STATUS, "model_status"); add(Metric.EV_ERROR, "error"); add(Metric.EV_TEMP, "temp_c")
        add(Metric.EV_CABLE_LIMIT, "cable_limit_a")
        states = {"car_state": d["car_state"], "model_status": d["model_status_cz"],
                  "allowed": str(bool(d.get("allowed")))}
        return Reading(device_id=self.device_id, measurements=ms, states=states)

    # --- zápis (krok 3 používá; validace je v control vrstvě) ---------------------
    def _set(self, values: dict) -> dict:
        q = {k: json.dumps(v) for k, v in values.items()}
        return self._get("/api/set", q)

    async def set_values(self, values: dict, force: bool = False) -> dict:
        """`/api/set` s ochranou flash: amp/psm jen při změně a min. 60 s od posledního zápisu
        téhož klíče (force=True obchází — havarijní snížení pod jistič). Ostatní klíče (frc, dwo,
        fup, lmo) jen při změně. Vrací {klíč: True|"chyba"} + 'skipped' pro vynechané."""
        now = time.monotonic()
        todo, skipped = {}, {}
        for k, v in values.items():
            if self._last_set.get(k) == v and k in self._last_set:
                skipped[k] = "beze změny"
                continue
            if k in ("amp", "psm") and not force and now - self._last_write.get(k, -1e9) < MIN_WRITE_GAP_S:
                skipped[k] = f"rate-limit {MIN_WRITE_GAP_S:.0f} s"
                continue
            todo[k] = v
        res = {}
        if todo:
            res = await asyncio.to_thread(self._set, todo)
            for k, v in todo.items():
                if res.get(k) is True:
                    self._last_set[k] = v
                    self._last_write[k] = now
                else:
                    logger.warning("go-e %s: set %s=%s → %s", self.host, k, v, res.get(k))
        return {**res, **({"skipped": skipped} if skipped else {})}

    async def status_full(self) -> dict:
        """Kompletní dump (diagnostika; v produkci nepoužívat — brief §2)."""
        return await asyncio.to_thread(self._get, "/api/status")
