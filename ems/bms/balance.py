"""⚖ Balancování bateriového bloku podle napětí článků z BMS (v1.12.0).

Cyklus:  NABÍJENÍ výkonem P, dokud rozpětí článků (max − min) nedosáhne meze `delta_stop_v`
       → ČEKÁNÍ (baterie stojí, dům nekryje), dokud rozpětí neklesne pod `delta_resume_v`  → změří se „doba návratu“
       → VYBÍJENÍ výkonem P × `dis_p_ratio` po dobu `dis_t_ratio` × doba nabíjení (v1.12.7)
       → další cyklus s nabíjecím výkonem P × `chg_ratio` (vždy z předchozího cyklu; doba návratu se jen měří a zobrazuje).
Konec (hotovo): proběhl celý cyklus, během kterého rozpětí článků ani jednou nepřekročilo `delta_final_v`.
Záložní konce: výkon dalšího cyklu < `p_min_kw`, uplynulo `max_hours`, ruční stop, pojistka.

Běží v API procesu (potřebuje živé snímky článků à 5 s, které jsou jen v jeho paměti). Povely měniči jdou běžnou frontou
`control_queue` se zdrojem `bms_balance`; po dobu běhu je modul měniče zamčený stejně jako při testu baterie.
Kolektor hlídá tep (`heartbeat_at`): když řídicí smyčka přestane žít, vrátí měnič do Self-Use (`watchdog`).
BMS se jen čte.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.api.db import get_pool
from ems.auth.deps import get_current_user, require_permission
from ems.control import db as control_db
from . import live

logger = logging.getLogger("ems.bms.balance")
SRC = "bms_balance"
TICK_S = 5
STALE_PAUSE_S, STALE_ABORT_S = 30, 180       # stáří snímku článků: pozastavit výkon / přerušit
CELL_MIN_MV, CELL_MAX_MV = 2800, 3650        # tvrdé meze článku (stejné jako test baterie)
SOC_DIS_FLOOR = 10.0                         # pod tímto SoC se krok vybíjení přeskočí
BREAKER_PF = 0.95
WATCHDOG_S = 90

DEFAULTS = {
    "delta_stop_v": 0.050,        # rozpětí článků, při kterém se nabíjení zastaví
    "delta_resume_v": 0.002,      # rozpětí, pod které musí články klesnout, než se pokračuje
    "delta_final_v": 0.030,       # hotovo = celý cyklus, ve kterém rozpětí tuto hodnotu ani jednou nepřekročilo
    "chg_ratio": 0.5,             # nabíjecí výkon dalšího cyklu = chg_ratio × nabíjecí výkon tohoto cyklu
    "dis_p_ratio": 0.5,           # vybíjecí výkon = dis_p_ratio × nabíjecí výkon tohoto cyklu
    "dis_t_ratio": 0.5,           # doba vybíjení = dis_t_ratio × doba nabíjení tohoto cyklu
    "p_max_kw": 10.0,             # „plný výkon“ prvního cyklu a strop dalších
    "p_min_kw": 0.3,              # pod tímto výkonem balancování končí
    "p_idle_kw": 0.1,             # výkon ve fázi čekání (nucené nabíjení minimem = baterie nekryje dům)
    "max_wait_min": 60.0,         # nejdelší čekání na návrat
    "cell_vtop": 3.60,            # strop článku — nabíjení se zastaví i když rozpětí mez nedosáhlo
    "max_hours": 12.0,
}
LIMITS = {"delta_stop_v": (0.005, 0.5), "delta_resume_v": (0.001, 0.4), "delta_final_v": (0.002, 0.5), "chg_ratio": (0.05, 1.5), "dis_p_ratio": (0.0, 2.0), "dis_t_ratio": (0.0, 3.0),
          "p_max_kw": (0.2, 50), "p_min_kw": (0.05, 20), "p_idle_kw": (0.0, 1.0), "max_wait_min": (1, 600),
          "cell_vtop": (3.40, 3.60), "max_hours": (0.2, 72)}
PHASES = {"charge": "Nabíjení", "wait": "Čekání na návrat", "discharge": "Vybíjení"}


# --- logika 2 (v1.13.0): „vmax“ = podle napětí nejvyššího článku, body podle SoC -------------------------------------
# Bod: do jakého SoC platí, strop nejvyššího článku, nejmenší počet cyklů, hystereze, poměr doby vybíjení, minimální výkon.
# Nabíjení: jakmile nejvyšší článek dojde na (strop − hystereze), výkon se sníží poměrem `chg_ratio` (to není cyklus),
# nejníž na minimum bodu. Na minimu a při dosažení stropu → vybíjení `dis_p_ratio` × poslední nabíjecí výkon, dokud nejvyšší
# článek neklesne na (strop − `dis_drop_v` bodu) → konec cyklu. Bez časového limitu (v1.13.8); brzdí jen SoC ≤ 10 %,
# meze článku a nejdelší běh celého balancování.
# Další bod: odjetý min. počet cyklů A SoC ≥ SoC bodu.
# Když SoC přeroste hodnotu bodu a článek je přitom pod (strop − hystereze), přejde se na další bod i bez cyklů (v1.13.6).
POINT_DEFAULT = {"soc": 100.0, "u_max": 3.52, "cycles": 4, "hyst": 0.01, "dis_drop_v": 0.02, "p_min_kw": 1.0}
DEFAULTS_V = {
    "p_in_kw": 10.0,            # vstupní výkon: první nabíjení každého bodu
    "chg_ratio": 0.75,          # další schod nabíjecího výkonu = chg_ratio × aktuální
    "dis_p_ratio": 0.2,         # vybíjecí výkon = dis_p_ratio × poslední nabíjecí výkon
    "settle_s": 30.0,           # prodleva po snížení výkonu, než smí přijít další snížení
    "cell_vtop": 3.60, "p_idle_kw": 0.1, "max_hours": 24.0,
    "points": [{**POINT_DEFAULT, "soc": 50.0, "u_max": 3.35}, {**POINT_DEFAULT, "soc": 85.0, "u_max": 3.40},
               {**POINT_DEFAULT, "soc": 95.0, "u_max": 3.45}, {**POINT_DEFAULT, "soc": 98.0, "u_max": 3.49},
               {**POINT_DEFAULT, "soc": 100.0, "u_max": 3.52, "cycles": 0}],
}
LIMITS_V = {"p_in_kw": (0.2, 50), "chg_ratio": (0.1, 0.99), "dis_p_ratio": (0.0, 2.0), "settle_s": (5, 600),
            "cell_vtop": (3.40, 3.60), "p_idle_kw": (0.0, 1.0), "max_hours": (0.2, 72)}
POINT_LIMITS = {"soc": (1, 100), "u_max": (3.20, 3.60), "cycles": (0, 50), "hyst": (0.001, 0.1),
                "dis_drop_v": (0.0, 0.3), "p_min_kw": (0.05, 20)}


def _num(v, name: str, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: neplatné číslo")
    if not (lo <= x <= hi):
        raise ValueError(f"{name} = {x:g} je mimo rozsah {lo:g}–{hi:g}")
    return x


def _clean_vmax(raw: dict | None, base: dict | None) -> dict:
    b = dict(base or {})
    out = {"mode": "vmax"}
    for k, (lo, hi) in LIMITS_V.items():
        v = (raw or {}).get(k)
        out[k] = _num(v if v is not None else b.get(k, DEFAULTS_V[k]), k, lo, hi)
    pts_in = (raw or {}).get("points") or b.get("points") or DEFAULTS_V["points"]
    if not isinstance(pts_in, list) or not (1 <= len(pts_in) <= 8):
        raise ValueError("Body: zadej 1 až 8 bodů")
    pts = []
    for i, pt in enumerate(pts_in):
        row = {}
        for k, (lo, hi) in POINT_LIMITS.items():
            v = (pt or {}).get(k)
            v = POINT_DEFAULT[k] if v is None or v == "" else v
            if k == "hyst":                      # hystereze se zadává i se znaménkem minus (−0,01 V) → bere se velikost
                v = abs(_num(v, f"Bod {i + 1} · hystereze", -0.1, 0.1))
            x = _num(v, f"Bod {i + 1} · {k}", lo, hi)
            row[k] = int(x) if k == "cycles" else x
        pts.append(row)
    for i in range(1, len(pts)):
        if pts[i]["soc"] <= pts[i - 1]["soc"]:
            raise ValueError(f"Bod {i + 1}: SoC musí být vyšší než u bodu {i}")
        if pts[i]["u_max"] < pts[i - 1]["u_max"]:
            raise ValueError(f"Bod {i + 1}: strop článku nesmí být nižší než u bodu {i}")
    for i, pt in enumerate(pts):
        if pt["u_max"] > out["cell_vtop"]:
            raise ValueError(f"Bod {i + 1}: strop {pt['u_max']:g} V je nad stropem článku {out['cell_vtop']:g} V")
    out["points"] = pts
    return out


def norm(params: dict | None) -> dict:
    """Doplní výchozí hodnoty a převede starší záznam (do 1.12.6: `dis_ratio` = poměr DOBY vybíjení)."""
    src = dict(params or {})
    if src.get("mode") == "vmax":
        try:
            return _clean_vmax(None, src)
        except ValueError:
            return {"mode": "vmax", **{k: src.get(k, v) for k, v in DEFAULTS_V.items()}}
    if "dis_t_ratio" not in src and src.get("dis_ratio") is not None:
        src["dis_t_ratio"] = src["dis_ratio"]
    return {"mode": "delta", **{k: src.get(k, v) for k, v in DEFAULTS.items()}}


def clean_params(raw: dict | None, base: dict | None = None) -> dict:
    mode = (raw or {}).get("mode") or (base or {}).get("mode") or "delta"
    if mode == "vmax":
        return _clean_vmax(raw, base if (base or {}).get("mode") == "vmax" else None)
    out = norm({k: v for k, v in (base or {}).items() if k != "mode"} if (base or {}).get("mode") != "vmax" else None)
    for k, (lo, hi) in LIMITS.items():
        if raw and raw.get(k) is not None:
            try:
                v = float(raw[k])
            except (TypeError, ValueError):
                raise ValueError(f"Parametr {k}: neplatné číslo")
            if not (lo <= v <= hi):
                raise ValueError(f"Parametr {k} = {v:g} je mimo rozsah {lo:g}–{hi:g}")
            out[k] = v
    if out["delta_resume_v"] >= out["delta_stop_v"]:
        raise ValueError("Mez návratu musí být menší než mez zastavení nabíjení")
    if out["delta_final_v"] > out["delta_stop_v"]:
        raise ValueError("Finální rozpětí nesmí být větší než mez zastavení nabíjení (cyklus by ho nemohl splnit)")
    if out["p_min_kw"] > out["p_max_kw"]:
        raise ValueError("Minimální výkon nesmí být větší než plný výkon")
    return out


# ---------------------------------------------------------------- DB
async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bms_balance (
                id SERIAL PRIMARY KEY, bms_module_id TEXT NOT NULL, inverter_id TEXT NOT NULL, locality_id INTEGER,
                block_idx INTEGER, status TEXT NOT NULL DEFAULT 'running', phase TEXT NOT NULL DEFAULT 'charge',
                cycle INTEGER NOT NULL DEFAULT 1, params JSONB NOT NULL, state JSONB NOT NULL DEFAULT '{}'::jsonb,
                result JSONB, created_by TEXT, started_at TIMESTAMPTZ NOT NULL DEFAULT now(), ended_at TIMESTAMPTZ,
                heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE TABLE IF NOT EXISTS bms_balance_samples (
                balance_id INTEGER NOT NULL, t TIMESTAMPTZ NOT NULL, phase TEXT, cycle INTEGER, p_set REAL, p_bat REAL,
                vmax INTEGER, vmin INTEGER, vavg REAL, delta INTEGER, nmax INTEGER, nmin INTEGER, soc REAL);
            ALTER TABLE bms_balance_samples ADD COLUMN IF NOT EXISTS ulim INTEGER;
            CREATE INDEX IF NOT EXISTS bms_balance_samples_idx ON bms_balance_samples (balance_id, t);
            CREATE TABLE IF NOT EXISTS bms_balance_defaults (bms_module_id TEXT PRIMARY KEY, params JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_by TEXT);""")


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("params", "state", "result"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    if isinstance(d.get("params"), dict):
        d["params"] = norm(d["params"])
    for k in ("started_at", "ended_at", "heartbeat_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


async def _fetch(sql: str, *a) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return [_row(r) for r in await conn.fetch(sql, *a)]


async def running() -> list[dict]:
    return await _fetch("SELECT * FROM bms_balance WHERE status='running' ORDER BY id")


async def running_modules() -> set[str]:
    """Moduly měniče, které právě řídí balancování (zámek pro plánovač / pravidla / ruční povely)."""
    try:
        return {b["inverter_id"] for b in await running()}
    except Exception:
        return set()


async def get(bid: int) -> dict | None:
    r = await _fetch("SELECT * FROM bms_balance WHERE id=$1", bid)
    return r[0] if r else None


async def _update(bid: int, **f) -> None:
    cols, vals = ["heartbeat_at=now()"], [bid]
    for k, v in f.items():
        vals.append(json.dumps(v) if k in ("params", "state", "result") else v)
        cols.append(f"{k}=${len(vals)}" + ("::jsonb" if k in ("params", "state", "result") else ""))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE bms_balance SET {', '.join(cols)} WHERE id=$1", *vals)


async def samples(bid: int, since: datetime | None = None) -> dict:
    """Sloupcově (úsporné pro graf): t = epoch ms."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT t, phase, cycle, p_set, p_bat, vmax, vmin, vavg, delta, nmax, nmin, soc, ulim FROM bms_balance_samples "
            "WHERE balance_id=$1 AND ($2::timestamptz IS NULL OR t > $2) ORDER BY t", bid, since)
    cols = ["phase", "cycle", "p_set", "p_bat", "vmax", "vmin", "vavg", "delta", "nmax", "nmin", "soc", "ulim"]
    out = {"t": [int(r["t"].timestamp() * 1000) for r in rows]}
    for c in cols:
        out[c] = [r[c] for r in rows]
    return out


def _defaults_key(bms_module_id: str, mode: str) -> str:
    return bms_module_id if mode != "vmax" else f"{bms_module_id}#vmax"


async def saved_defaults(bms_module_id: str, mode: str = "delta") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchval("SELECT params FROM bms_balance_defaults WHERE bms_module_id=$1", _defaults_key(bms_module_id, mode))
    stored = json.loads(r) if isinstance(r, str) else (r or {})
    try:
        return clean_params({**stored, "mode": mode})
    except ValueError:
        return clean_params({"mode": mode})


async def _announce(locality_id, title: str, detail: str) -> None:
    """Událost do provozního deníku → e-mail odběratelům lokality (rozešle kolektor). Kroky cyklů se neoznamují."""
    try:
        from ems.alerts import db as alerts_db
        await alerts_db.record_event(locality_id, "control", title, detail)
    except Exception as exc:
        logger.debug("balancování oznámení: %s", exc)


# ---------------------------------------------------------------- povely měniči
async def _force(b: dict, action: str, power_kw: float, reason: str) -> None:
    """Drží na měniči požadovaný režim; nový povel jen když se stav liší (jako test baterie)."""
    mod = b["inverter_id"]
    reg = int(round(power_kw * 100))                       # jednotka 10 W
    st = (await control_db.get_states([mod])).get(mod) or {}
    p = st.get("params") or {}
    if isinstance(p, str):
        p = json.loads(p) if p else {}
    if st.get("action") == action and st.get("source") in (SRC, "export_guard") and p.get("power_req", p.get("power")) == reg:
        return
    await control_db.enqueue(mod, action, {"power": reg, "source": SRC, "reason": f"balancování: {reason}"}, username=SRC)


async def _release(inverter_id: str, why: str) -> None:
    await control_db.enqueue(inverter_id, "stop", {"source": SRC, "reason": f"balancování: {why}"}, username=SRC)


async def _breaker_cap(b: dict, want_kw: float, inv: dict) -> float:
    """Nabíjení ze sítě nesmí přetížit hlavní jistič: P ≤ limit − odběr domu mimo baterii."""
    try:
        from ems.localities import db as loc_db
        loc = await loc_db.get(b["locality_id"]) or {}
        br = loc.get("main_breaker_a")
        if not br:
            return want_kw
        limit = int(loc.get("main_breaker_phases") or 3) * 230 * float(br) * BREAKER_PF / 1000
        grid = float(inv.get("grid_power") or 0) / 1000
        bat = max(0.0, float(inv.get("battery_power") or 0) / 1000)
        return round(min(want_kw, max(0.3, limit - max(0.0, grid - bat))), 1)
    except Exception:
        return want_kw


# ---------------------------------------------------------------- automat
def _secs(iso: str | None, now: datetime) -> float:
    return (now - datetime.fromisoformat(iso)).total_seconds() if iso else 0.0


def next_power(p_kw: float, params: dict) -> float:
    """Nabíjecí výkon dalšího cyklu = výkon tohoto cyklu × chg_ratio, nejvýš p_max."""
    return round(min(float(params["p_max_kw"]), p_kw * float(params["chg_ratio"])), 2)


async def _finish(b: dict, status: str, reason: str, now: datetime) -> None:
    st = b["state"]
    st.setdefault("log", []).append({"t": now.isoformat(), "text": f"Konec: {reason}"})
    pool = await get_pool()
    async with pool.acquire() as conn:
        agg = await conn.fetchrow(
            "SELECT count(*) n, min(t) t0, max(t) t1, max(delta) dmax, "
            "(array_agg(delta ORDER BY t))[1] d0, (array_agg(delta ORDER BY t DESC))[1] d1, "
            "(array_agg(soc ORDER BY t))[1] soc0, (array_agg(soc ORDER BY t DESC))[1] soc1, "
            "(array_agg(vavg ORDER BY t))[1] v0, (array_agg(vavg ORDER BY t DESC))[1] v1, "
            "coalesce(sum(greatest(p_bat,0)),0)*$2/3600.0 e_chg, coalesce(sum(greatest(-p_bat,0)),0)*$2/3600.0 e_dis "
            "FROM bms_balance_samples WHERE balance_id=$1", b["id"], float(TICK_S))
    cyc = st.get("cycles") or []
    rets = [c["t_return_s"] for c in cyc if c.get("t_return_s") is not None]
    result = {"reason": reason, "status": status, "cycles": len(cyc), "samples": agg["n"],
              "duration_s": round((agg["t1"] - agg["t0"]).total_seconds()) if agg["n"] else 0,
              "delta_start_mv": agg["d0"], "delta_end_mv": agg["d1"], "delta_max_mv": agg["dmax"],
              "soc_start": agg["soc0"], "soc_end": agg["soc1"], "vavg_start_mv": agg["v0"], "vavg_end_mv": agg["v1"],
              "e_charged_kwh": round(float(agg["e_chg"]), 2), "e_discharged_kwh": round(float(agg["e_dis"]), 2),
              "p_first_kw": cyc[0]["p_kw"] if cyc else None, "p_last_kw": cyc[-1]["p_kw"] if cyc else None,
              "t_return_avg_s": round(sum(rets) / len(rets)) if rets else None,
              "t_return_last_s": rets[-1] if rets else None}
    ce = st.get("cell_e") or {}
    if ce.get("in"):
        ratio = [round(o / i * 100, 2) if i > 0.5 else None for i, o in zip(ce["in"], ce["out"])]
        ok = [(r, n + 1) for n, r in enumerate(ratio) if r is not None]
        result["cell_energy"] = {"in_wh": [round(x, 3) for x in ce["in"]], "out_wh": [round(x, 3) for x in ce["out"]],
                                 "ratio_pct": ratio, "per_module": st.get("per_module"),
                                 "ratio_min": min(ok) if ok else None, "ratio_max": max(ok) if ok else None,
                                 "ratio_avg": round(sum(r for r, _ in ok) / len(ok), 2) if ok else None}
    await _update(b["id"], status=status, state=st, result=result, ended_at=now)
    await _release(b["inverter_id"], reason)
    word = {"done": "dokončeno", "stopped": "zastaveno", "aborted": "PŘERUŠENO"}.get(status, status)
    await _announce(b.get("locality_id"), f"⚖ Balancování B{b.get('block_idx') or '?'} {word}",
                    f"{reason}. Trvání {result['duration_s'] // 60} min, cyklů {result['cycles']}, rozpětí článků "
                    f"{result['delta_start_mv']} → {result['delta_end_mv']} mV, nabito {result['e_charged_kwh']} kWh, vybito "
                    f"{result['e_discharged_kwh']} kWh. Řízení baterie se vrací plánovači a pravidlům; oznámení o vynuceném "
                    f"nabíjení a vybíjení se opět posílají.")
    logger.info("balancování #%s: %s (%s)", b["id"], status, reason)


async def _tick_one(b: dict, now: datetime) -> None:
    from ems.battest import db as bt_db
    p, st, bid = norm(b["params"]), b["state"], b["id"]
    live.touch(b["bms_module_id"])                                   # EMSBOX čte články à 5 s po celou dobu
    lv = live.latest(b["bms_module_id"])
    mv = [int(round(x)) for x in ((lv[1].get("bms_cells_mv") if lv else None) or [])]
    age = (now - lv[0]).total_seconds() if lv else 1e9
    if not mv or age > STALE_PAUSE_S:
        st["stale_since"] = st.get("stale_since") or now.isoformat()
        if _secs(st["stale_since"], now) > STALE_ABORT_S:
            return await _finish(b, "aborted", f"BMS neposlal články déle než {STALE_ABORT_S} s", now)
        await _force(b, "force_charge", float(p["p_idle_kw"]), "čekám na data z BMS")
        return await _update(bid, state=st)
    st.pop("stale_since", None)
    vmax, vmin = max(mv), min(mv)
    vavg, delta = sum(mv) / len(mv), max(mv) - min(mv)
    if vmax > CELL_MAX_MV or vmin < CELL_MIN_MV:
        return await _finish(b, "aborted", f"článek mimo meze ({vmin}–{vmax} mV)", now)
    if _secs(b["started_at"], now) > float(p["max_hours"]) * 3600:
        return await _finish(b, "done", f"uplynula nejdelší doba {p['max_hours']:g} h", now)

    inv = await bt_db.latest_metrics(b["inverter_id"], ["grid_power", "battery_power", f"battery_power_{b['block_idx'] or 1}"], 120)
    bms = await bt_db.latest_metrics(b["bms_module_id"], ["bms_soc"], 600)
    soc = bms.get("bms_soc")
    p_bat = inv.get(f"battery_power_{b['block_idx'] or 1}", inv.get("battery_power"))
    # v1.12.11: energie do/z každého článku. Články jsou v sérii → stejný proud; podíl článku na výkonu bloku = U_článku / ΣU.
    # E_článku += P_bloku × U_článku / ΣU × Δt  (P_bloku z měniče, + nabíjení / − vybíjení; mrtvé pásmo ±30 W).
    ce = st.get("cell_e")
    if not ce or len(ce.get("in") or []) != len(mv):
        ce = st["cell_e"] = {"in": [0.0] * len(mv), "out": [0.0] * len(mv)}
    dt = min(15.0, _secs(st.get("e_at"), now)) if st.get("e_at") else float(TICK_S)
    st["e_at"] = now.isoformat()
    n_mod = len((lv[1].get("bms_modules_cv") if lv else None) or []) or 1
    st["per_module"] = max(1, len(mv) // n_mod)
    if p_bat is not None and abs(float(p_bat)) >= 30:
        key, tot, wh = ("in" if float(p_bat) > 0 else "out"), float(sum(mv)), abs(float(p_bat)) * dt / 3600.0
        ce[key] = [round(e + wh * v / tot, 4) for e, v in zip(ce[key], mv)]
    phase, cycle = b["phase"], b["cycle"]
    is_v = p.get("mode") == "vmax"
    p_kw = float(st.get("p_kw") or (p["p_in_kw"] if is_v else p["p_max_kw"]))
    ulim = None
    t_phase = _secs(st.get("phase_at"), now)
    p_set = 0.0
    st["cycle_dmax"] = max(int(st.get("cycle_dmax") or 0), delta)      # největší rozpětí v běžícím cyklu
    log = st.setdefault("log", [])
    cycles = st.setdefault("cycles", [])

    def go(new_phase: str, text: str) -> None:
        nonlocal phase
        phase = new_phase
        st["phase_at"] = now.isoformat()
        log.append({"t": now.isoformat(), "text": text})
        del log[:-400]

    if is_v:
        cycle, p_set, ulim, end = await _vmax_step(b, p, st, now, phase, cycle, p_kw, vmax, soc, t_phase, inv, go, cycles)
        if end:
            await _update(bid, phase=phase, cycle=cycle, state=st)
            b["state"] = st
            return await _finish(b, "done", end, now)
    elif phase == "charge":
        hit_delta = delta >= float(p["delta_stop_v"]) * 1000
        hit_top = vmax >= float(p["cell_vtop"]) * 1000
        hit_full = soc is not None and soc >= 99.5 and t_phase > 180     # BMS hlásí plno → dál se nenabije
        if hit_delta or hit_top or hit_full:
            cycles.append({"n": cycle, "p_kw": p_kw, "t_charge_s": round(t_phase), "charge_from": st.get("phase_at"),
                           "delta_stop_mv": delta, "vmax_mv": vmax, "vmin_mv": vmin, "stop_by": "rozpětí" if hit_delta else ("strop článku" if hit_top else "plné nabití")})
            why = (f"rozpětí {delta} mV ≥ {p['delta_stop_v'] * 1000:g} mV" if hit_delta
                   else f"článek {vmax} mV na stropu" if hit_top else f"BMS hlásí {soc:g} %")
            go("wait", f"Cyklus {cycle}: nabíjení {p_kw:g} kW zastaveno po {round(t_phase)} s — {why}")
            await _force(b, "force_charge", float(p["p_idle_kw"]), "čekání na návrat")
            p_set = float(p["p_idle_kw"])
        else:
            p_set = await _breaker_cap(b, p_kw, inv)
            await _force(b, "force_charge", p_set, f"cyklus {cycle} nabíjení")
    elif phase == "wait":
        p_set = float(p["p_idle_kw"])
        back = delta < float(p["delta_resume_v"]) * 1000
        timeout = t_phase >= float(p["max_wait_min"]) * 60
        if back or timeout:
            c = cycles[-1] if cycles else {}
            c.update({"t_return_s": round(t_phase), "return_timeout": bool(timeout and not back), "delta_resume_mv": delta})
            t_dis = round(float(c.get("t_charge_s") or 0) * float(p["dis_t_ratio"]))
            p_dis = round(p_kw * float(p["dis_p_ratio"]), 2)
            c["t_discharge_plan_s"], c["p_dis_kw"] = t_dis, p_dis
            msg = (f"Cyklus {cycle}: návrat pod {p['delta_resume_v'] * 1000:g} mV za {round(t_phase)} s" if back
                   else f"Cyklus {cycle}: rozpětí {delta} mV se do {p['max_wait_min']:g} min pod mez nevrátilo")
            if t_dis >= TICK_S and p_dis >= 0.05 and (soc is None or soc > SOC_DIS_FLOOR):
                go("discharge", msg + f" → vybíjení {p_dis:g} kW ({p['dis_p_ratio']:g} × {p_kw:g}) na {t_dis} s "
                                      f"({p['dis_t_ratio']:g} × {c.get('t_charge_s')} s)")
                await _force(b, "force_discharge", p_dis, f"cyklus {cycle} vybíjení")
                p_set = -p_dis
            else:
                go("discharge", msg + " → vybíjení přeskočeno")
                c["t_discharge_plan_s"] = 0
        else:
            await _force(b, "force_charge", p_set, "čekání na návrat")
    elif phase == "discharge":
        c = cycles[-1] if cycles else {}
        plan = float(c.get("t_discharge_plan_s") or 0)
        if t_phase >= plan or (soc is not None and soc <= SOC_DIS_FLOOR):
            c["t_discharge_s"] = round(min(t_phase, plan)) if plan else 0
            nxt = next_power(p_kw, p)
            c["p_next_kw"] = nxt
            c["delta_max_mv"] = int(st.get("cycle_dmax") or 0)
            if c["delta_max_mv"] <= float(p["delta_final_v"]) * 1000:
                await _update(bid, phase=phase, cycle=cycle, state=st)
                b["state"] = st
                return await _finish(b, "done", f"vybalancováno: v cyklu {cycle} rozpětí nepřekročilo {p['delta_final_v'] * 1000:g} mV "
                                                f"(nejvýš {c['delta_max_mv']} mV)", now)
            st["cycle_dmax"] = 0
            if nxt < float(p["p_min_kw"]):
                await _update(bid, phase=phase, cycle=cycle, state=st)
                b["state"] = st
                return await _finish(b, "done", f"výkon dalšího cyklu {nxt:g} kW je pod minimem {p['p_min_kw']:g} kW", now)
            st["p_kw"] = nxt
            cycle += 1
            go("charge", f"Cyklus {cycle}: nabíjení {nxt:g} kW ({p['chg_ratio']:g} × {p_kw:g} kW; doba návratu minule {c.get('t_return_s')} s)")
            p_set = await _breaker_cap(b, nxt, inv)
            await _force(b, "force_charge", p_set, f"cyklus {cycle} nabíjení")
        else:
            p_dis = float(c.get("p_dis_kw") or p_kw)
            p_set = -p_dis
            await _force(b, "force_discharge", p_dis, f"cyklus {cycle} vybíjení")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bms_balance_samples (balance_id,t,phase,cycle,p_set,p_bat,vmax,vmin,vavg,delta,nmax,nmin,soc,ulim) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
            bid, now, phase, cycle, p_set, (float(p_bat) / 1000 if p_bat is not None else None), vmax, vmin, round(vavg, 2), delta,
            mv.index(vmax) + 1, mv.index(vmin) + 1, soc, ulim)
    await _update(bid, phase=phase, cycle=cycle, state=st)


def _start_point(points: list[dict], soc: float | None) -> int:
    """Bod, kterým se začíná: první, jehož SoC je nad aktuálním SoC (jinak poslední)."""
    for i, pt in enumerate(points):
        if soc is None or soc < float(pt["soc"]):
            return i
    return len(points) - 1


async def _vmax_step(b, p, st, now, phase, cycle, p_kw, vmax, soc, t_phase, inv, go, cycles):
    """Jeden krok logiky „vmax“. Vrací (cyklus, povel kW, strop bodu mV, důvod konce | None)."""
    pts = p["points"]
    if "pt" not in st:
        st.update({"pt": _start_point(pts, soc), "pt_cycles": 0, "p_kw": float(p["p_in_kw"]), "step_at": now.isoformat(),
                   "cyc_at": now.isoformat(), "cyc_steps": [float(p["p_in_kw"])]})
        p_kw = float(p["p_in_kw"])
        st["log"].append({"t": now.isoformat(), "text": f"Začínám bodem {st['pt'] + 1} (SoC {soc if soc is not None else '?'} %, "
                                                        f"cíl {pts[st['pt']]['soc']:g} %, strop {pts[st['pt']]['u_max']:g} V)"})
    i = min(int(st["pt"]), len(pts) - 1)
    pt, last_pt = pts[i], i == len(pts) - 1
    ulim = int(round(pt["u_max"] * 1000))
    thr = ulim - int(round(pt["hyst"] * 1000))
    p_min = float(pt["p_min_kw"])
    target_soc = min(float(pt["soc"]), 99.5)
    p_set = 0.0
    if phase not in ("charge", "discharge"):
        go("charge", "Pokračuji nabíjením")
        phase = "charge"
    if phase == "charge" and not last_pt and soc is not None and soc >= float(pt["soc"]) and vmax < thr:
        # v1.13.6: SoC už je nad hodnotou bodu a jeho strop přitom nabíjení neomezuje (článek je pod strop − hystereze)
        # → bod nemá co balancovat, jde se dál. Dřív se čekalo na dokončený cyklus, který při nedosaženém stropu nikdy nepřišel.
        nxt = pts[i + 1]
        st.update({"pt": i + 1, "pt_cycles": 0, "p_kw": float(p["p_in_kw"]), "step_at": now.isoformat()})
        st.setdefault("cyc_steps", []).append(float(p["p_in_kw"]))
        st["log"].append({"t": now.isoformat(), "text": f"Bod {i + 2}: SoC {soc:g} % ≥ {pt['soc']:g} % a strop bodu {i + 1} neomezoval "
                          f"(článek {vmax} mV < {thr} mV) → strop {nxt['u_max']:g} V, cíl {nxt['soc']:g} %, nabíjení {p['p_in_kw']:g} kW"})
        p_set = await _breaker_cap(b, float(p["p_in_kw"]), inv)
        await _force(b, "force_charge", p_set, f"bod {i + 2} cyklus {cycle} nabíjení")
        return cycle, p_set, int(round(nxt["u_max"] * 1000)), None
    if phase == "charge":
        t_step = _secs(st.get("step_at"), now)
        at_min = p_kw <= p_min + 1e-6
        hit_top = vmax >= float(p["cell_vtop"]) * 1000
        full = soc is not None and soc >= 99.5 and t_phase > 180
        if (vmax >= ulim and at_min) or hit_top or full:
            drop_mv = int(round(float(pt["dis_drop_v"]) * 1000))
            dis_target = ulim - drop_mv                      # vybíjí se, dokud nejvyšší článek neklesne sem
            t_dis = 1 if drop_mv > 0 else 0                  # 0 = nevybíjet; jinak bez časového limitu, končí napětím
            p_dis = round(p_kw * float(p["dis_p_ratio"]), 2)
            c = {"n": cycle, "pt": i + 1, "p_start_kw": (st.get("cyc_steps") or [p_kw])[0], "p_kw": p_kw, "steps": list(st.get("cyc_steps") or []),
                 "t_charge_s": round(_secs(st.get("cyc_at"), now)), "t_last_s": round(t_step), "vmax_mv": vmax, "soc": soc,
                 "u_max_mv": ulim, "stop_by": "strop článku 3,60 V" if hit_top and vmax < ulim else ("plné nabití" if full and vmax < ulim else "strop bodu"),
                 "p_dis_kw": p_dis, "t_discharge_plan_s": t_dis, "dis_target_mv": dis_target}
            cycles.append(c)
            del cycles[:-300]
            if last_pt and soc is not None and soc >= target_soc and int(st.get("pt_cycles") or 0) + 1 >= int(pt["cycles"]):
                c["t_discharge_plan_s"] = 0
                return cycle, 0.0, ulim, f"nabito na {soc:g} % při stropu článku {pt['u_max']:g} V (bod {i + 1}, cyklus {cycle})"
            msg = f"Bod {i + 1} · cyklus {cycle}: článek {vmax} mV na stropu {ulim} mV při {p_kw:g} kW"
            if t_dis and p_dis >= 0.05 and (soc is None or soc > SOC_DIS_FLOOR):
                go("discharge", msg + f" → vybíjení {p_dis:g} kW, dokud článek neklesne na {dis_target} mV (strop − {drop_mv} mV)")
                await _force(b, "force_discharge", p_dis, f"bod {i + 1} cyklus {cycle} vybíjení")
                p_set = -p_dis
            else:
                c["t_discharge_plan_s"] = 0
                go("discharge", msg + " → vybíjení přeskočeno")
        elif vmax >= thr and not at_min and t_step >= (10 if vmax >= ulim else float(p["settle_s"])):
            new_p = max(p_min, round(p_kw * float(p["chg_ratio"]), 2))
            st["p_kw"], st["step_at"] = new_p, now.isoformat()
            st.setdefault("cyc_steps", []).append(new_p)
            st["log"].append({"t": now.isoformat(), "text": f"Bod {i + 1}: článek {vmax} mV ≥ {thr} mV → výkon {p_kw:g} → {new_p:g} kW"
                                                            + (" (minimum bodu)" if new_p <= p_min + 1e-6 else "")})
            p_set = await _breaker_cap(b, new_p, inv)
            await _force(b, "force_charge", p_set, f"bod {i + 1} cyklus {cycle} nabíjení")
        else:
            p_set = await _breaker_cap(b, p_kw, inv)
            await _force(b, "force_charge", p_set, f"bod {i + 1} cyklus {cycle} nabíjení")
    elif phase == "discharge":
        c = cycles[-1] if cycles else {}
        plan = float(c.get("t_discharge_plan_s") or 0)
        dis_target = c.get("dis_target_mv")
        reached = dis_target is not None and vmax <= int(dis_target) and t_phase >= 10      # 10 s = ať povel stihne zabrat
        low_soc = soc is not None and soc <= SOC_DIS_FLOOR
        if reached or not plan or low_soc:
            c["t_discharge_s"] = round(t_phase) if plan else 0
            c["dis_end_mv"], c["dis_timeout"] = vmax, False
            if low_soc and not reached:
                st["log"].append({"t": now.isoformat(), "text": f"Bod {i + 1} · cyklus {cycle}: vybíjení ukončeno při SoC {soc:g} % "
                                                                f"(pojistka {SOC_DIS_FLOOR:g} %), článek {vmax} mV"})
            st["pt_cycles"] = int(st.get("pt_cycles") or 0) + 1
            reached = soc is not None and soc >= target_soc and st["pt_cycles"] >= int(pt["cycles"])
            if reached and last_pt:
                return cycle, 0.0, ulim, f"nabito na {soc:g} % při stropu článku {pt['u_max']:g} V (bod {i + 1}, {st['pt_cycles']} cyklů)"
            cycle += 1
            if reached:
                st.update({"pt": i + 1, "pt_cycles": 0, "p_kw": float(p["p_in_kw"])})
                nxt = pts[i + 1]
                txt = (f"Bod {i + 2}: SoC {soc:g} % ≥ {pt['soc']:g} % a odjeto {int(pt['cycles'])}+ cyklů → strop {nxt['u_max']:g} V, "
                       f"cíl {nxt['soc']:g} %, nabíjení {p['p_in_kw']:g} kW")
                ulim = int(round(nxt["u_max"] * 1000))
            else:
                why = [] if st["pt_cycles"] >= int(pt["cycles"]) else [f"cyklus {st['pt_cycles']} z min. {int(pt['cycles'])}"]
                if soc is None or soc < target_soc:
                    why.append(f"SoC {soc if soc is not None else '?'} % < {pt['soc']:g} %")
                txt = f"Bod {i + 1} · cyklus {cycle}: nabíjení {float(st['p_kw']):g} kW ({', '.join(why)})"
            st["step_at"] = st["cyc_at"] = now.isoformat()
            st["cyc_steps"] = [float(st["p_kw"])]
            go("charge", txt)
            p_set = await _breaker_cap(b, float(st["p_kw"]), inv)
            await _force(b, "force_charge", p_set, f"bod {int(st['pt']) + 1} cyklus {cycle} nabíjení")
        else:
            p_dis = float(c.get("p_dis_kw") or 0)
            p_set = -p_dis
            await _force(b, "force_discharge", p_dis, f"bod {i + 1} cyklus {cycle} vybíjení")
    return cycle, p_set, ulim, None


async def run_loop() -> None:
    """Řídicí smyčka v API procesu."""
    await asyncio.sleep(8)
    while True:
        try:
            now = datetime.now(timezone.utc)
            for b in await running():
                try:
                    await _tick_one(b, now)
                except Exception as exc:
                    logger.warning("balancování #%s tick: %s", b["id"], exc)
        except Exception as exc:
            logger.debug("balancování smyčka: %s", exc)
        await asyncio.sleep(TICK_S)


async def watchdog() -> None:
    """Volá kolektor: běžící balancování bez tepu déle než WATCHDOG_S → měnič zpět do Self-Use, záznam přerušit."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE bms_balance SET status='aborted', ended_at=now(), "
            "result = jsonb_build_object('status','aborted','reason','řídicí smyčka neodpovídala (restart serveru?)') "
            "WHERE status='running' AND heartbeat_at < now() - make_interval(secs => $1) "
            "RETURNING id, inverter_id, locality_id, block_idx", WATCHDOG_S)
    for r in rows:
        await _release(r["inverter_id"], "řídicí smyčka neodpovídala")
        await _announce(r["locality_id"], f"⚖ Balancování B{r['block_idx'] or '?'} PŘERUŠENO",
                        "Řídicí smyčka neodpovídala (restart serveru?). Měnič se vrací do běžného režimu, řízení baterie má opět "
                        "plánovač a pravidla; oznámení o vynuceném nabíjení a vybíjení se opět posílají.")
        logger.warning("balancování #%s: bez tepu > %s s → stop", r["id"], WATCHDOG_S)


# ---------------------------------------------------------------- API
router = APIRouter(prefix="/api/bms-balance", tags=["bms-balance"])
read = require_permission("read")


async def controller(user: dict = Depends(get_current_user)) -> dict:
    if "control" not in user["permissions"]:
        raise HTTPException(status_code=403, detail="Chybí právo řídit zařízení (control).")
    return user


class StartBody(BaseModel):
    bms_module_id: str
    params: dict = {}
    confirmed: bool = False


class ParamsBody(BaseModel):
    params: dict


async def _context(bms_module_id: str) -> dict:
    """BMS modul → lokalita, blok, modul měniče."""
    from ems.modules import db as modules_db
    from ems.localities import db as loc_db
    from ems.api.db import list_devices
    mod = await modules_db.get(bms_module_id)
    if mod is None or getattr(mod, "adapter", None) != "pylontech_sc0500":
        raise HTTPException(status_code=404, detail="BMS modul nenalezen")
    pool = await get_pool()
    async with pool.acquire() as conn:
        loc = await conn.fetchval("SELECT locality_id FROM modules WHERE id=$1", bms_module_id)
    if loc is None:
        raise HTTPException(status_code=409, detail="BMS modul nemá přiřazenou lokalitu")
    devs = {d["device_id"]: d for d in await list_devices()}
    inv = next((d["id"] for d in await loc_db.devices_for_locality(loc) if (devs.get(d["id"]) or {}).get("adapter") == "solis"), None)
    if inv is None:
        raise HTTPException(status_code=409, detail="V lokalitě není měnič Solis, který by baterii řídil")
    return {"locality_id": loc, "inverter_id": inv, "block_idx": int((getattr(mod, "params", None) or {}).get("block_idx") or 1)}


@router.get("/defaults/{bms_module_id}")
async def get_defaults(bms_module_id: str, _: dict = Depends(read)) -> dict:
    return {"params": await saved_defaults(bms_module_id), "params_vmax": await saved_defaults(bms_module_id, "vmax"),
            "builtin": DEFAULTS, "limits": LIMITS, "point_default": POINT_DEFAULT}


@router.put("/defaults/{bms_module_id}")
async def put_defaults(bms_module_id: str, body: ParamsBody, user: dict = Depends(controller)) -> dict:
    try:
        params = clean_params(body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bms_balance_defaults (bms_module_id, params, updated_by) VALUES ($1,$2::jsonb,$3) "
            "ON CONFLICT (bms_module_id) DO UPDATE SET params=EXCLUDED.params, updated_at=now(), updated_by=EXCLUDED.updated_by",
            _defaults_key(bms_module_id, params.get("mode", "delta")), json.dumps(params), user.get("username"))
    return {"params": params}


@router.post("/start")
async def start(body: StartBody, user: dict = Depends(controller)) -> dict:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Spuštění vyžaduje potvrzení.")
    ctx = await _context(body.bms_module_id)
    try:
        mode = "vmax" if (body.params or {}).get("mode") == "vmax" else "delta"
        params = clean_params({**body.params, "mode": mode}, await saved_defaults(body.bms_module_id, mode))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from ems.battest import db as bt_db
    if ctx["inverter_id"] in await bt_db.running_modules():
        raise HTTPException(status_code=409, detail="Měnič je právě obsazený testem baterie nebo jiným balancováním.")
    lv = live.latest(body.bms_module_id)
    now = datetime.now(timezone.utc)
    p0 = params["p_in_kw"] if mode == "vmax" else params["p_max_kw"]
    state = {"p_kw": p0, "phase_at": now.isoformat(), "cycles": [], "params_log": [],
             "log": [{"t": now.isoformat(), "text": f"Spuštěno ({user.get('username')}), logika "
                      f"{'napětí nejvyššího článku (body podle SoC)' if mode == 'vmax' else 'rozpětí článků'}, nabíjení {p0:g} kW"}],
             "had_live": bool(lv)}
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO bms_balance (bms_module_id, inverter_id, locality_id, block_idx, params, state, created_by) "
            "VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7) RETURNING *",
            body.bms_module_id, ctx["inverter_id"], ctx["locality_id"], ctx["block_idx"], json.dumps(params), json.dumps(state),
            user.get("username"))
    live.touch(body.bms_module_id)
    await _announce(ctx["locality_id"], f"⚖ Balancování B{ctx['block_idx']} spuštěno",
                    f"Spustil {user.get('username')}. Po dobu balancování je řízení baterie NADŘAZENO všemu ostatnímu — plánovač, "
                    f"časový plán, pravidla i ruční povely k měniči jsou pozastavené. Baterie se cyklicky nabíjí (až "
                    f"{p0:g} kW ze sítě), čeká a vybíjí; baterie během toho nekryje spotřebu domu. Jednotlivé kroky "
                    f"se neoznamují, další zpráva přijde po skončení. "
                    + (f"Logika: napětí nejvyššího článku, {len(params['points'])} bodů až do {params['points'][-1]['soc']:g} % SoC / "
                       f"{params['points'][-1]['u_max']:g} V, nejdéle {params['max_hours']:g} h." if mode == "vmax" else
                       f"Meze: stop {params['delta_stop_v'] * 1000:g} mV, návrat {params['delta_resume_v'] * 1000:g} mV, "
                       f"finál {params['delta_final_v'] * 1000:g} mV, nejdéle {params['max_hours']:g} h."))
    return _row(r)


@router.get("/active/{bms_module_id}")
async def active(bms_module_id: str, _: dict = Depends(read)) -> dict | None:
    r = await _fetch("SELECT * FROM bms_balance WHERE bms_module_id=$1 AND status='running' ORDER BY id DESC LIMIT 1", bms_module_id)
    return r[0] if r else None


@router.get("/history/{bms_module_id}")
async def history(bms_module_id: str, _: dict = Depends(read)) -> list[dict]:
    rows = await _fetch("SELECT id, status, phase, cycle, params, result, created_by, started_at, ended_at "
                        "FROM bms_balance WHERE bms_module_id=$1 ORDER BY id DESC LIMIT 100", bms_module_id)
    return rows


@router.get("/run/{bid}")
async def run_detail(bid: int, since: int | None = None, _: dict = Depends(read)) -> dict:
    b = await get(bid)
    if not b:
        raise HTTPException(status_code=404, detail="Balancování nenalezeno")
    ts = datetime.fromtimestamp(since / 1000, tz=timezone.utc) if since else None
    return {"run": b, "samples": await samples(bid, ts), "phases": PHASES, "tick_s": TICK_S}


@router.put("/run/{bid}/params")
async def change_params(bid: int, body: ParamsBody, user: dict = Depends(controller)) -> dict:
    b = await get(bid)
    if not b or b["status"] != "running":
        raise HTTPException(status_code=409, detail="Balancování neběží")
    try:
        params = clean_params(body.params, b["params"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    old = norm(b["params"])
    changed = {k: [old.get(k), v] for k, v in params.items() if old.get(k) != v and k != "points"}
    if params.get("mode") == "vmax" and old.get("points") != params.get("points"):
        changed["points"] = [len(old.get("points") or []), len(params["points"])]
    if changed:
        now = datetime.now(timezone.utc).isoformat()
        st = b["state"]
        st.setdefault("params_log", []).append({"t": now, "by": user.get("username"), "changed": changed})
        txt = ", ".join("body upraveny" if k == "points" else f"{k} {a:g} → {v:g}" for k, (a, v) in changed.items())
        st.setdefault("log", []).append({"t": now, "text": f"Změna parametrů ({user.get('username')}): {txt}"})
        if "p_max_kw" in changed and float(st.get("p_kw") or 0) > params["p_max_kw"]:
            st["p_kw"] = params["p_max_kw"]
        await _update(bid, params=params, state=st)
    return await get(bid)


@router.post("/run/{bid}/stop")
async def stop(bid: int, user: dict = Depends(controller)) -> dict:
    b = await get(bid)
    if not b:
        raise HTTPException(status_code=404, detail="Balancování nenalezeno")
    if b["status"] == "running":
        await _finish(b, "stopped", f"zastaveno uživatelem {user.get('username')}", datetime.now(timezone.utc))
    return await get(bid)
