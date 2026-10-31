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
PSM_HYSTERESIS_S = 600.0        # přepnutí fází nejdřív po 10 min (nabíječka sama vynucuje mptwt=10 min)
OFFLINE_FAILSAFE_S = 300.0      # ztráta spojení > 5 min → po obnově frc=0 (auto nesmí zůstat zamčené)
AMP_MIN, AMP_MAX = 6, 32

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
                 poll_active_s: float = 10.0, timeout: float = 5.0, amp_1f_max: int = 16,
                 amp_3f_max: int = 32, **_ignored):
        self.device_id = str(device_id)
        self.amp_1f_max = int(amp_1f_max or 16)     # la1 — limit 1f proudu (ověřit s autem; do té doby 16)
        self.amp_3f_max = int(amp_3f_max or 32)
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
        self._target: dict | None = None        # cíl EMS {amp, psm, frc, dwo} — None = uvolněno (frc=0)
        self._last_psm_change = -1e9
        self._took_over = False                 # fup=false&lmo=3 zapsáno
        self._pending_release = False

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
        return None   # bezstavové HTTP; převzetí řízení až s prvním cílem (takeover)

    async def close(self) -> None:
        """Fail-safe při shutdownu/odpojení modulu: uvolnit (frc=0), ať auto nezůstane zamčené."""
        if self._target is not None or self._took_over:
            try:
                await asyncio.to_thread(self._set, {"frc": 0})
            except Exception as exc:
                logger.warning("go-e %s: fail-safe frc=0 při close selhal: %s", self.host, exc)
        self._target = None

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
        rebooted = bool(prev and d.get("uptime_ms") is not None and prev.get("uptime_ms") is not None
                        and d["uptime_ms"] < prev["uptime_ms"])
        if rebooted:
            d["rebooted"] = True               # rbt klesl → nabíječka restartovala → re-apply cíle
            logger.warning("go-e %s: detekován restart nabíječky (rbt %s → %s)", self.host, prev["uptime_ms"], d["uptime_ms"])
            self._last_set.clear(); self._last_write.clear(); self._took_over = False   # re-apply hned, bez rate-limitu
            self._last_psm_change = -1e9          # nabíječka po restartu nemá běžící mptwt
        # fail-safe po výpadku spojení > 5 min: TERA mezitím neřídila → uvolnit, cíl zahodit
        gap = (now - prev_ok) if (prev_ok := getattr(self, "_prev_ok", None)) is not None else 0.0
        self._prev_ok = self.last_ok
        if gap > OFFLINE_FAILSAFE_S and (self._target is not None or self._took_over):
            logger.warning("go-e %s: spojení chybělo %.0f s → fail-safe frc=0, cíl zahozen", self.host, gap)
            self._target = None
            self._pending_release = True
        self._last = d
        try:
            await self._reconcile_target(d)
        except Exception as exc:
            logger.warning("go-e %s: aplikace cíle selhala: %s", self.host, exc)

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

    # --- cíl EMS (krok 3): set_target / release / reconcile ----------------------
    def normalize(self, t: dict) -> dict:
        """Ořez cíle na limity: amp 6–32 a amp_1f_max při psm=1; psm 0/1/2; frc 0/1/2."""
        out = {}
        if t.get("psm") is not None:
            out["psm"] = int(t["psm"]) if int(t["psm"]) in (0, 1, 2) else 0
        if t.get("amp") is not None:
            cap = self.amp_1f_max if out.get("psm", (self._last or {}).get("phase_mode")) == 1 else self.amp_3f_max
            cap = min(cap, int((self._last or {}).get("amp_max") or AMP_MAX))
            out["amp"] = max(AMP_MIN, min(cap, int(round(float(t["amp"])))))
        if t.get("frc") is not None:
            out["frc"] = int(t["frc"]) if int(t["frc"]) in (0, 1, 2) else 0
        if "dwo" in t:
            out["dwo"] = None if t["dwo"] in (None, "", 0) else float(t["dwo"])
        return out

    async def set_target(self, t: dict, force: bool = False) -> dict:
        """Nastaví cíl EMS (sloučí s předchozím) a hned ho zkusí aplikovat. force=True = havarijní
        snížení (obchází rate-limit amp; psm hysterezi neobchází)."""
        base = dict(self._target or {})
        base.update(self.normalize(t))
        self._target = base
        self._pending_release = False
        return await self._reconcile_target(self._last or {}, force=force)

    async def release(self, permanent: bool = False) -> dict:
        """Uvolnit řízení: frc=0 (auto jede podle nabíječky/app). permanent=True vrátí i fup=true."""
        self._target = None
        vals = {"frc": 0, "dwo": None}
        if permanent:
            vals["fup"] = True; self._took_over = False
        res = await self.set_values(vals)
        self._pending_release = False
        return res

    async def _reconcile_target(self, d: dict, force: bool = False) -> dict:
        """Každý poll: zapiš, co se liší od cíle a co rate-limity dovolí (re-apply po restartu, odložené psm)."""
        if self._pending_release:
            return await self.release()
        t = self._target
        if not t:
            return {}
        vals = {}
        if not self._took_over:
            vals.update(fup=False, lmo=3)        # převzetí řízení: vypnout interní PV logiku
        now = time.monotonic()
        want_psm = t.get("psm")
        if want_psm is not None and want_psm != d.get("phase_mode"):
            if now - self._last_psm_change >= PSM_HYSTERESIS_S:
                vals["psm"] = want_psm
            # jinak odloženo — zkusí se příští poll
        if t.get("amp") is not None and t["amp"] != d.get("amp_set"):
            vals["amp"] = t["amp"]
        if t.get("frc") is not None and t["frc"] != d.get("force"):
            vals["frc"] = t["frc"]
        if "dwo" in t:
            vals["dwo"] = t["dwo"]              # set_values vynechá, pokud beze změny
        if not vals:
            return {}
        res = await self.set_values(vals, force=force)
        if res.get("psm") is True:
            self._last_psm_change = now
        if res.get("fup") is True or res.get("lmo") is True:
            self._took_over = True
        return res

    @property
    def target(self) -> dict | None:
        return dict(self._target) if self._target else None

    async def status_full(self) -> dict:
        """Kompletní dump (diagnostika; v produkci nepoužívat — brief §2)."""
        return await asyncio.to_thread(self._get, "/api/status")
