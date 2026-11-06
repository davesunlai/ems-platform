"""🧪 Automat testu baterie (běží v kolektoru, volá se každý tick).

Fáze: preparing → discharge0 (na dno) → charge (na strop, snímky po 10 %) → hold (T_hold na stropu)
      → discharge (na dno, snímky po 10 %) → done | aborted
Zdroj povelů `battery_test` má přednost před planner/schedule/spot/manual (zámek = běžící záznam v battery_tests).
Bezpečnost: 🛡 strop exportu (tick_export_guard) má přednost i před testem; hlavní jistič hlídá engine (grid import).
Automatické přerušení: ztráta komunikace > 120 s, článek < 2,8 V / > 3,65 V, teplota > 50 °C, ruční abort.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ems.control import db as control_db
from . import db

logger = logging.getLogger("ems.battest")
_TZ = ZoneInfo("Europe/Prague")
SRC = "battery_test"
# Názvy kroků (slovo „fáze“ je vyhrazené pro L1–L3): klíč stavu → popisek
STEP_NAMES = {"preparing": "Krok 0 · Příprava", "discharge0": "Krok 1 · Předvybití", "charge": "Krok 2 · Nabíjení",
              "hold": "Krok 3 · Výdrž", "discharge": "Krok 4 · Vybíjení", "done": "Vyhodnocení", "aborted": "Přerušeno"}
ALLOWED_SOURCES = {SRC, "keepalive", "export_guard", "self-heal", "target"}   # kdo smí do fronty modulu během testu
TICK_S = 20
COMM_LOSS_S = 120
CELL_VMIN, CELL_VMAX, T_MAX = 2.80, 3.65, 50.0
BREAKER_PF = 0.95          # rezerva pod jističem (3 × 230 V × A × 0,95)
CHARGE_TAPER = 1.2         # BMS u 100 % zpomaluje → odhad délky nabíjení × 1,2

METRICS = ["battery_soc", "battery_soc_1", "battery_soc_2", "battery_power", "battery_voltage_1", "battery_voltage_2",
           "battery_current_1", "battery_current_2", "battery_cell_vmin_1", "battery_cell_vmax_1", "battery_cell_vmin_2",
           "battery_cell_vmax_2", "battery_cell_nmin_1", "battery_cell_nmax_1", "battery_cell_nmin_2", "battery_cell_nmax_2",
           "battery_bms_cells_per_module_1", "battery_bms_cells_per_module_2", "battery_cell_tmin_1", "battery_cell_tmax_1", "battery_cell_tmin_2", "battery_cell_tmax_2",
           "energy_bat_charge_total", "energy_bat_discharge_total", "pv_power", "grid_power", "load_power"]


# ---------- slunce (NOAA aproximace, bez závislostí) ----------
def sun_times(lat: float, lon: float, day: datetime) -> tuple[datetime, datetime] | None:
    """(východ, západ) v UTC pro daný den; None za polárního dne/noci."""
    n = day.timetuple().tm_yday
    lngHour = lon / 15.0
    out = []
    for rising in (True, False):
        t = n + ((6 if rising else 18) - lngHour) / 24.0
        M = (0.9856 * t) - 3.289
        L = (M + 1.916 * math.sin(math.radians(M)) + 0.020 * math.sin(math.radians(2 * M)) + 282.634) % 360
        RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
        RA = (RA + (math.floor(L / 90) * 90 - math.floor(RA / 90) * 90)) / 15.0
        sinDec = 0.39782 * math.sin(math.radians(L)); cosDec = math.cos(math.asin(sinDec))
        cosH = (math.cos(math.radians(90.833)) - sinDec * math.sin(math.radians(lat))) / (cosDec * math.cos(math.radians(lat)))
        if cosH > 1 or cosH < -1:
            return None
        H = (360 - math.degrees(math.acos(cosH))) if rising else math.degrees(math.acos(cosH))
        T = (H / 15.0 + RA - 0.06571 * t - 6.622 - lngHour) % 24
        out.append(datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=T))
    return out[0], out[1]


# ---------- odhad délky a doporučený start ----------
def estimate(params: dict, soc_now: float | None) -> dict:
    cap = float(params["capacity_kwh"]); pc, pd = float(params["p_chg_kw"]), float(params["p_dis_kw"])
    floor, ceil = float(params["floor_pct"]), float(params["ceil_pct"])
    span = (ceil - floor) / 100.0 * cap
    h0 = max(0.0, ((soc_now if soc_now is not None else 50.0) - floor) / 100.0 * cap / pd)
    h1 = span / pc * CHARGE_TAPER
    h2 = float(params["hold_min"]) / 60.0
    h3 = span / pd
    return {"h_discharge0": round(h0, 1), "h_charge": round(h1, 1), "h_hold": round(h2, 1), "h_discharge": round(h3, 1),
            "h_total": round(h0 + h1 + h2 + h3, 1)}


def recommend_start(est: dict, lat: float | None, lon: float | None, now: datetime) -> dict:
    """Doporučený start tak, aby fáze 3 (vybíjení) proběhla mezi západem a východem slunce (ořez exportem FVE)."""
    if lat is None or lon is None:
        return {"ok": None, "msg": "Lokalita nemá souřadnice — doporučení času nelze spočítat."}
    pre = est["h_discharge0"] + est["h_charge"] + est["h_hold"]
    for d in range(0, 3):
        day = (now + timedelta(days=d)).astimezone(_TZ)
        st = sun_times(lat, lon, day)
        if not st:
            continue
        _, sunset = st
        nxt = sun_times(lat, lon, day + timedelta(days=1))
        sunrise_next = nxt[0] if nxt else sunset + timedelta(hours=12)
        night_h = (sunrise_next - sunset).total_seconds() / 3600
        start = sunset - timedelta(hours=pre)
        if start < now:
            if d == 0 and (sunset - now).total_seconds() / 3600 >= 0:
                # dnes už nestihneme předfáze před západem → začít hned jen pokud vybíjení skončí před východem
                end_dis = now + timedelta(hours=est["h_total"])
                if end_dis <= sunrise_next and now >= sunset - timedelta(hours=pre) - timedelta(hours=0.5):
                    pass
            continue
        fits = est["h_discharge"] <= night_h
        return {"ok": fits, "start_at": start.astimezone(_TZ).isoformat(), "sunset": sunset.astimezone(_TZ).isoformat(),
                "sunrise_next": sunrise_next.astimezone(_TZ).isoformat(), "night_h": round(night_h, 1),
                "msg": (f"Doporučený start {start.astimezone(_TZ).strftime('%d.%m. %H:%M')}: vybíjení začne po západu "
                        f"({sunset.astimezone(_TZ).strftime('%H:%M')}) a potrvá ≈ {est['h_discharge']} h"
                        + ("" if fits else f" — delší než noc ({night_h:.1f} h), zvaž vyšší vybíjecí výkon"))}
    return {"ok": None, "msg": "Doporučení nelze spočítat."}


# ---------- předkontrola ----------
async def precheck(locality_id: int, module_id: str, params: dict) -> dict:
    from ems.localities import db as loc_db
    from ems.planner import db as planner_db
    from ems.planner.service import _soc_now
    loc = await loc_db.get(locality_id) or {}
    cfg = await planner_db.get_config(locality_id) or {}
    warnings, blockers = [], []
    if await db.running(module_id):
        blockers.append("Na tomto modulu už test běží.")
    m = await db.latest_metrics(module_id, ["battery_soc", "battery_power"], COMM_LOSS_S)
    if "battery_soc" not in m:
        blockers.append("Měnič nekomunikuje (žádné SoC za posledních 2 min).")
    breaker = loc.get("main_breaker_a")
    if not breaker:
        blockers.append("Není zadána velikost hlavního jističe lokality (A) — nabíjení ze sítě se musí hlídat proti jističi. Zadej ji v Lokalitách.")
    else:
        ph = int(loc.get("main_breaker_phases") or 3)
        imp_kw = ph * 230 * float(breaker) * BREAKER_PF / 1000
        if float(params["p_chg_kw"]) > imp_kw * 0.8:
            warnings.append(f"Nabíjecí výkon {params['p_chg_kw']} kW je blízko limitu jističe ({ph}×{breaker:g} A ≈ {imp_kw:.1f} kW) — engine ho bude ořezávat podle odběru domu.")
    if not cfg.get("grid_export_limit_kw"):
        blockers.append("Není nastaven strop exportu (Řízení → Limity) — vybíjení do sítě bez něj nelze.")
    warnings.append(f"Záložní SoC měniče (reg. 43024) bude po dobu testu dočasně nastaven na {params['floor_pct']:g} % a po skončení/přerušení vrácen.")
    warnings.append("Během testu nenabíjej auto; pokud ano, wallbox bude omezen na 6 A / 1 fázi (≈ 1,4 kW) a po testu uvolněn.")
    warnings.append("Plánovač, časový plán, spotové řízení i ruční povely jsou po dobu testu pro tento modul zablokované.")
    soc = await _soc_now([module_id])
    est = estimate(params, soc)
    rec = recommend_start(est, loc.get("lat"), loc.get("lon"), datetime.now(timezone.utc))
    ph = int(loc.get("main_breaker_phases") or 3)
    imp_kw = round(ph * 230 * float(breaker) * BREAKER_PF / 1000, 1) if breaker else None
    return {"ok": not blockers, "blockers": blockers, "warnings": warnings, "soc_now": soc, "estimate": est, "recommend": rec,
            "breaker_a": breaker, "breaker_phases": ph, "import_limit_kw": imp_kw, "export_limit_kw": cfg.get("grid_export_limit_kw")}


def default_params(capacity_kwh: float) -> dict:
    return {"capacity_kwh": capacity_kwh, "p_chg_kw": round(capacity_kwh / 10, 1), "p_dis_kw": round(capacity_kwh / 10, 1),
            "hold_min": 60, "floor_pct": 10, "ceil_pct": 100}


# ---------- start / abort ----------
async def start(locality_id: int, module_id: str, params: dict, username: str | None) -> dict:
    pc = await precheck(locality_id, module_id, params)
    if not pc["ok"]:
        raise ValueError(" ".join(pc["blockers"]))
    saved = {"soc_now": pc["soc_now"], "estimate": pc["estimate"]}
    from . import blocks as blocks_mod
    m0 = await db.latest_metrics(module_id, ["battery_soc_1", "battery_soc_2"], 600)
    packs = sum(1 for k in ("battery_soc_1", "battery_soc_2") if k in m0) or 1
    params = {**params, "blocks": await blocks_mod.blocks_for_test(module_id, float(params["capacity_kwh"]), packs)}
    t = await db.create(locality_id, module_id, params, saved, username)
    await db.log(t["id"], f"Test založen uživatelem {username or '?'}: {params}")
    await _event(t, "spuštěn", f"{username or '?'} · nabíjení {params['p_chg_kw']} kW, vybíjení {params['p_dis_kw']} kW, výdrž {params['hold_min']} min, "
                               f"{params['floor_pct']:g}–{params['ceil_pct']:g} % · odhad ≈ {pc['estimate']['h_total']} h. Řízení modulu {module_id} je do konce testu zablokované.")
    # krok 1: přečíst řídicí registry (43024) — výsledek vyzvedne tick
    cid = await control_db.enqueue(module_id, "read_controls", {"source": SRC, "reason": "test baterie: snímek nastavení"}, username=SRC)
    await db.update(t["id"], saved={**saved, "read_cmd": cid})
    # wallbox omezit (pokud v lokalitě je)
    try:
        from ems.evcharger.routes import _ev_modules
        for ev in await _ev_modules(locality_id):
            await control_db.enqueue(ev, "ev_set", {"amp": 6, "psm": 1, "source": SRC, "reason": "test baterie: omezení wallboxu"}, username=SRC)
            await db.log(t["id"], f"Wallbox {ev} omezen na 6 A / 1f.")
            saved["ev_limited"] = ev
            await db.update(t["id"], saved={**saved, "read_cmd": cid})
    except Exception as exc:
        logger.debug("battest wallbox: %s", exc)
    return await db.get(t["id"])


async def abort(test_id: int, reason: str, username: str | None = None) -> dict | None:
    t = await db.get(test_id)
    if not t or t["status"] not in db.RUNNING:
        return t
    await _finish(t, "aborted", reason)
    return await db.get(test_id)


async def _event(t: dict, title: str, detail: str = "") -> None:
    """Provozní událost lokality → zobrazí se ve výstrahách a odejde e-mailem uživatelům s notifikacemi."""
    try:
        from ems.alerts import db as alerts_db
        await alerts_db.record_event(t.get("locality_id"), "battery_test", f"Test baterie #{t['id']}: {title}", detail)
    except Exception as exc:
        logger.debug("battest event: %s", exc)


async def _finish(t: dict, status: str, reason: str | None) -> None:
    mod = t["module_id"]
    await control_db.enqueue(mod, "stop", {"source": SRC, "reason": f"test baterie: {status}"}, username=SRC)
    orig = (t.get("saved") or {}).get("soc_backup_orig")
    if orig is not None:
        await control_db.enqueue(mod, "set_soc_backup", {"pct": orig, "source": SRC, "reason": "test baterie: obnova záložního SoC"}, username=SRC)
        await db.log(t["id"], f"Záložní SoC vrácen na {orig} %.")
    ev = (t.get("saved") or {}).get("ev_limited")
    if ev:
        await control_db.enqueue(ev, "ev_release", {"source": SRC, "reason": "test baterie: konec"}, username=SRC)
    await db.update(t["id"], status=status, ended_at=datetime.now(timezone.utc), abort_reason=reason)
    await db.log(t["id"], f"Konec testu: {status}" + (f" — {reason}" if reason else ""), "warn" if status == "aborted" else "info")
    if status == "aborted":
        await _event(t, "PŘERUŠEN", reason or "")
    else:
        full = await db.get(t["id"]); r = (full or {}).get("result") or {}
        await _event(t, "dokončen", f"nabito {r.get('e_charge_kwh')} kWh, vybito {r.get('e_discharge_kwh')} kWh, kapacita ≈ {r.get('capacity_est_kwh')} kWh, "
                                    f"SoH {r.get('soh_pct')} %, účinnost {r.get('efficiency_pct')} %")


# ---------- výpočet výsledku ----------
async def compute_result(t: dict) -> dict:
    snaps = t.get("snapshots") or []
    p = t["params"]; cap = float(p["capacity_kwh"]); span = (float(p["ceil_pct"]) - float(p["floor_pct"])) / 100.0
    def tot(phase):
        s = [x for x in snaps if x["phase"] == phase]
        return float(s[-1]["e_phase_kwh"]) if s else None
    e_chg, e_hold, e_dis = tot("charge"), tot("hold"), tot("discharge")
    out = {"e_charge_kwh": round(e_chg, 2) if e_chg is not None else None,
           "e_hold_kwh": round(e_hold, 2) if e_hold is not None else None,
           "e_discharge_kwh": round(e_dis, 2) if e_dis is not None else None}
    e_in = (e_chg or 0) + (e_hold or 0)
    if e_dis:
        out["capacity_est_kwh"] = round(e_dis / span, 2)
        out["soh_pct"] = round(e_dis / span / cap * 100, 1)
    if e_dis and e_in:
        out["efficiency_pct"] = round(e_dis / e_in * 100, 1)
    if e_chg:
        out["capacity_from_charge_kwh"] = round(e_chg / span, 2)
    out["segments"] = [{"phase": s["phase"], "step": s["soc_step"], "kwh": s.get("e_step_kwh"), "minutes": s.get("minutes_step"),
                        "kw": round(float(s["e_step_kwh"]) / (float(s["minutes_step"]) / 60), 2) if s.get("e_step_kwh") and s.get("minutes_step") else None}
                       for s in snaps if s["phase"] in ("charge", "discharge")]
    s1 = [x for x in snaps if x.get("soc1") is not None and x.get("soc2") is not None]
    if s1:
        out["pack_drift_pct_max"] = round(max(abs(float(x["soc1"]) - float(x["soc2"])) for x in s1), 1)
    # vyhodnocení po blocích a článcích (assess.py); při chybě výsledek nesmí spadnout
    try:
        from . import assess as assess_mod
        tt = {**t, "phase_marks": await db.phase_marks(t["id"]), "ended_at": t.get("ended_at") or datetime.now(timezone.utc).isoformat()}
        out["assess"] = await assess_mod.assess(tt, out)
        out["blocks"] = [{k: b.get(k) for k in ("idx", "name", "nominal_kwh", "e_chg_kwh", "e_hold_kwh", "e_dis_kwh", "capacity_est_kwh", "soh_pct", "efficiency_pct", "level")}
                         for b in out["assess"]["blocks"]]
    except Exception as exc:
        logger.warning("battest assess #%s: %s", t.get("id"), exc)
    return out


# ---------- tick ----------
async def tick(state: dict) -> None:
    import time
    now_m = time.monotonic()
    if now_m - state.get("battest_last", 0) < TICK_S:
        return
    state["battest_last"] = now_m
    try:
        tests = await db.running()
    except Exception:
        return
    for t in tests:
        try:
            await _step(t, state)
        except Exception as exc:
            logger.warning("battest #%s tick: %s", t["id"], exc)


async def _force(t: dict, action: str, power_kw: float, reason: str) -> None:
    """Zajistí, že modul drží požadovaný force (re-force při jiném stavu/zdroji/výkonu)."""
    mod = t["module_id"]
    st = (await control_db.get_states([mod])).get(mod) or {}
    reg = int(round(power_kw * 100))
    p = st.get("params") or {}
    if isinstance(p, str):
        import json; p = json.loads(p) if p else {}
    if st.get("action") == action and st.get("source") in (SRC, "export_guard") and p.get("power_req", p.get("power")) == reg:
        return
    await control_db.enqueue(mod, action, {"power": reg, "source": SRC, "reason": reason}, username=SRC)
    await db.log(t["id"], f"{action} {power_kw:g} kW — {reason}")


async def _step(t: dict, state: dict) -> None:
    tid, mod, p = t["id"], t["module_id"], t["params"]
    m = await db.latest_metrics(mod, METRICS, COMM_LOSS_S)
    now = datetime.now(timezone.utc)
    # bezpečnost
    if "battery_soc" not in m:
        return await _finish(t, "aborted", "ztráta komunikace s měničem > 120 s")
    vmin = min([v for k, v in m.items() if k.startswith("battery_cell_vmin")] or [9])
    vmax = max([v for k, v in m.items() if k.startswith("battery_cell_vmax")] or [0])
    tmax = max([v for k, v in m.items() if k.startswith("battery_cell_tmax")] or [0])
    if vmin < CELL_VMIN or vmax > CELL_VMAX:
        return await _finish(t, "aborted", f"napětí článku mimo meze (min {vmin:.3f} V, max {vmax:.3f} V)")
    if tmax > T_MAX:
        return await _finish(t, "aborted", f"teplota baterie {tmax:.0f} °C > {T_MAX:g} °C")
    soc_raw = float(m["battery_soc"]); floor, ceil = float(p["floor_pct"]), float(p["ceil_pct"])
    # battery_soc je u dvou packů průměr (99 % + 100 % = 99,5 %) → pro prahy zaokrouhlujeme na celé %,
    # jinak se strop 100 % nikdy nedosáhne (test #1 stál 5 h na 99,5 %).
    soc = float(round(soc_raw))
    socs = [float(m[k]) for k in ("battery_soc_1", "battery_soc_2") if k in m]
    full_bms = (socs and max(socs) >= ceil and abs(float(m.get("battery_power") or 0)) < 300)   # jeden pack 100 % a BMS už nenabíjí
    saved = t.get("saved") or {}
    status = t["status"]
    phase_start = datetime.fromisoformat(t["phase_started_at"]) if t.get("phase_started_at") else now

    if status == "preparing":
        cmd = await control_db.get_command(int(saved.get("read_cmd") or 0)) if saved.get("read_cmd") else None
        if not cmd or cmd.get("status") == "pending":
            if (now - datetime.fromisoformat(t["started_at"])).total_seconds() > 300:
                return await _finish(t, "aborted", "čtení registrů měniče neproběhlo do 5 min")
            return
        if cmd.get("status") not in ("ok", "done"):
            return await _finish(t, "aborted", f"čtení registrů selhalo: {cmd.get('result')}")
        res = cmd.get("result") or {}
        if isinstance(res, str):
            import json; res = json.loads(res)
        ctr = (res.get("controls") or {})
        orig = ctr.get("43024")
        if orig is None:
            return await _finish(t, "aborted", "nepodařilo se přečíst záložní SoC (43024)")
        saved["soc_backup_orig"] = int(orig)
        await control_db.enqueue(mod, "set_soc_backup", {"pct": floor, "source": SRC, "reason": "test baterie: dno"}, username=SRC)
        await db.log(tid, f"Záložní SoC {orig} % → dočasně {floor:g} %.")
        await db.update(tid, saved=saved, status="discharge0", phase_started_at=now)
        return

    if status == "discharge0":
        if soc <= floor:
            await db.log(tid, f"Dno {floor:g} % dosaženo (SoC {soc:.0f} %) → Krok 2 · Nabíjení.")
            await _event(t, "Krok 2 · Nabíjení", f"dno {floor:g} % dosaženo, nabíjení {p['p_chg_kw']} kW na {ceil:g} %")
            await db.update(tid, status="charge", phase_started_at=now, saved={**saved, "next_step": _next_step_up(soc, floor)})
            await _snapshot(t, "charge", int(round(soc)), now, now, m, 0.0, None)
            return
        return await _force(t, "force_discharge", float(p["p_dis_kw"]), "Krok 1 · Předvybití na dno")

    if status == "charge":
        await _charge_with_breaker_guard(t, m)
        nxt = int(saved.get("next_step") or _next_step_up(soc, floor))
        if soc >= nxt:
            await _snapshot(t, "charge", nxt, phase_start, now, m)
            saved["next_step"] = nxt + 10
            await db.update(tid, saved=saved)
        if soc >= ceil or (full_bms and (now - phase_start).total_seconds() > 600):
            if soc < ceil:
                await db.log(tid, f"SoC {soc_raw:.1f} % (packy {'/'.join(f'{s:g}' for s in socs)} %), BMS nabíjení ukončil → strop považován za dosažený.")
            if int(saved.get("next_step") or 0) <= int(ceil):
                await _snapshot(t, "charge", int(ceil), phase_start, now, m)
            await db.log(tid, f"Strop {ceil:g} % dosažen → Krok 3 · Výdrž {p['hold_min']} min.")
            await _event(t, "Krok 3 · Výdrž", f"strop {ceil:g} % dosažen, výdrž {p['hold_min']} min")
            await db.update(tid, status="hold", phase_started_at=now)
        return

    if status == "hold":
        await _charge_with_breaker_guard(t, m)
        if (now - phase_start).total_seconds() >= float(p["hold_min"]) * 60:
            await _snapshot(t, "hold", int(ceil), phase_start, now, m)
            await db.log(tid, "Výdrž ukončena → Krok 4 · Vybíjení.")
            await _event(t, "Krok 4 · Vybíjení", f"vybíjení {p['p_dis_kw']} kW na {floor:g} %")
            await db.update(tid, status="discharge", phase_started_at=now, saved={**saved, "next_step": _next_step_down(soc, ceil)})
            await _snapshot(t, "discharge", int(round(soc)), now, now, m, 0.0, None)
        return

    if status == "discharge":
        await _force(t, "force_discharge", float(p["p_dis_kw"]), "Krok 4 · Vybíjení na dno")
        nxt = int(saved.get("next_step") or _next_step_down(soc, ceil))
        if soc <= nxt:
            await _snapshot(t, "discharge", nxt, phase_start, now, m)
            saved["next_step"] = nxt - 10
            await db.update(tid, saved=saved)
        if soc <= floor:
            full = await db.get(tid)
            res = await compute_result(full)
            await db.update(tid, result=res)
            await db.log(tid, f"Výsledek: nabito {res.get('e_charge_kwh')} kWh, vybito {res.get('e_discharge_kwh')} kWh, "
                              f"kapacita ≈ {res.get('capacity_est_kwh')} kWh, SoH {res.get('soh_pct')} %, účinnost {res.get('efficiency_pct')} %")
            await _finish({**t, "saved": saved}, "done", None)
        return


def _next_step_up(soc: float, floor: float) -> int:
    s = int(math.floor(soc / 10) * 10) + 10
    return max(s, int(floor) + 10 if floor % 10 == 0 else int(math.ceil(floor / 10) * 10))


def _next_step_down(soc: float, ceil: float) -> int:
    s = int(math.ceil(soc / 10) * 10) - 10
    return min(s, int(ceil) - 10 if ceil % 10 == 0 else int(math.floor(ceil / 10) * 10))


async def _charge_with_breaker_guard(t: dict, m: dict) -> None:
    """Nabíjení ze sítě omezené hlavním jističem: P_chg ≤ limit − (odběr domu bez baterie)."""
    from ems.localities import db as loc_db
    p = t["params"]; want = float(p["p_chg_kw"])
    loc = await loc_db.get(t["locality_id"]) or {}
    br = loc.get("main_breaker_a")
    if br:
        limit = int(loc.get("main_breaker_phases") or 3) * 230 * float(br) * BREAKER_PF / 1000
        grid = float(m.get("grid_power") or 0) / 1000      # + import
        bat = max(0.0, float(m.get("battery_power") or 0) / 1000)
        house = max(0.0, grid - bat)                        # import mimo baterii
        allowed = max(0.5, limit - house)
        if allowed < want:
            want = round(allowed, 1)
    await _force(t, "force_charge", want, "nabíjení" + (f" (ořez jističem na {want:g} kW)" if want < float(p["p_chg_kw"]) else ""))


async def _snapshot(t: dict, phase: str, step: int, phase_start: datetime, now: datetime, m: dict,
                    e_phase: float | None = None, prev=None) -> None:
    chg, dis = await db.energy_kwh(t["module_id"], phase_start, now)
    e = e_phase if e_phase is not None else (chg if phase in ("charge", "hold") else dis)
    last = await db.last_snapshot(t["id"], phase)
    e_step = (e - float(last["e_phase_kwh"])) if last else e
    mins = (now - datetime.fromisoformat(last["ts"])).total_seconds() / 60 if last else (now - phase_start).total_seconds() / 60
    await db.add_snapshot(
        t["id"], phase=phase, soc_step=step, ts=now, soc=m.get("battery_soc"), soc1=m.get("battery_soc_1"), soc2=m.get("battery_soc_2"),
        e_phase_kwh=round(e, 3), e_step_kwh=round(e_step, 3), minutes_step=round(mins, 1),
        bat_w=m.get("battery_power"), grid_w=m.get("grid_power"), pv_w=m.get("pv_power"), load_w=m.get("load_power"),
        u1=m.get("battery_voltage_1"), u2=m.get("battery_voltage_2"), i1=m.get("battery_current_1"), i2=m.get("battery_current_2"),
        cell_vmin=min([v for k, v in m.items() if k.startswith("battery_cell_vmin")] or [None]) if any(k.startswith("battery_cell_vmin") for k in m) else None,
        cell_vmax=max([v for k, v in m.items() if k.startswith("battery_cell_vmax")] or [None]) if any(k.startswith("battery_cell_vmax") for k in m) else None,
        t_min=min([v for k, v in m.items() if k.startswith("battery_cell_tmin")] or [None]) if any(k.startswith("battery_cell_tmin") for k in m) else None,
        t_max=max([v for k, v in m.items() if k.startswith("battery_cell_tmax")] or [None]) if any(k.startswith("battery_cell_tmax") for k in m) else None,
        inv_chg_total=m.get("energy_bat_charge_total"), inv_dis_total=m.get("energy_bat_discharge_total"),
        cell_vmin_1=m.get("battery_cell_vmin_1"), cell_vmax_1=m.get("battery_cell_vmax_1"),
        cell_vmin_2=m.get("battery_cell_vmin_2"), cell_vmax_2=m.get("battery_cell_vmax_2"),
        cell_nmin_1=m.get("battery_cell_nmin_1"), cell_nmax_1=m.get("battery_cell_nmax_1"),
        cell_nmin_2=m.get("battery_cell_nmin_2"), cell_nmax_2=m.get("battery_cell_nmax_2"),
        cpm_1=m.get("battery_bms_cells_per_module_1"), cpm_2=m.get("battery_bms_cells_per_module_2"))
    await db.log(t["id"], f"{STEP_NAMES.get(phase, phase)} {step} %: {e:.2f} kWh od začátku kroku (+{e_step:.2f} kWh / {mins:.0f} min)")
