"""⚖ Balancování bateriového bloku podle napětí článků z BMS (v1.12.0).

Cyklus:  NABÍJENÍ výkonem P, dokud rozpětí článků (max − min) nedosáhne meze `delta_stop_v`
       → ČEKÁNÍ (baterie stojí, dům nekryje), dokud rozpětí neklesne pod `delta_resume_v`  → změří se „doba návratu“
       → VYBÍJENÍ stejným výkonem P po dobu `dis_ratio` × doba nabíjení
       → další cyklus s výkonem P × (cílová doba návratu / změřená doba návratu).
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
    "t_return_min": 10.0,         # cílová doba návratu (min)
    "dis_ratio": 0.5,             # doba vybíjení = dis_ratio × doba nabíjení
    "p_max_kw": 10.0,             # „plný výkon“ prvního cyklu a strop dalších
    "p_min_kw": 0.3,              # pod tímto výkonem balancování končí
    "p_idle_kw": 0.1,             # výkon ve fázi čekání (nucené nabíjení minimem = baterie nekryje dům)
    "max_wait_min": 60.0,         # nejdelší čekání na návrat
    "cell_vtop": 3.60,            # strop článku — nabíjení se zastaví i když rozpětí mez nedosáhlo
    "max_hours": 12.0,
}
LIMITS = {"delta_stop_v": (0.005, 0.5), "delta_resume_v": (0.001, 0.4), "delta_final_v": (0.002, 0.5), "t_return_min": (0.5, 240), "dis_ratio": (0.0, 2.0),
          "p_max_kw": (0.2, 50), "p_min_kw": (0.05, 20), "p_idle_kw": (0.0, 1.0), "max_wait_min": (1, 600),
          "cell_vtop": (3.40, 3.60), "max_hours": (0.2, 72)}
PHASES = {"charge": "Nabíjení", "wait": "Čekání na návrat", "discharge": "Vybíjení"}


def clean_params(raw: dict | None, base: dict | None = None) -> dict:
    out = dict(base or DEFAULTS)
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
            "SELECT t, phase, cycle, p_set, p_bat, vmax, vmin, vavg, delta, nmax, nmin, soc FROM bms_balance_samples "
            "WHERE balance_id=$1 AND ($2::timestamptz IS NULL OR t > $2) ORDER BY t", bid, since)
    cols = ["phase", "cycle", "p_set", "p_bat", "vmax", "vmin", "vavg", "delta", "nmax", "nmin", "soc"]
    out = {"t": [int(r["t"].timestamp() * 1000) for r in rows]}
    for c in cols:
        out[c] = [r[c] for r in rows]
    return out


async def saved_defaults(bms_module_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchval("SELECT params FROM bms_balance_defaults WHERE bms_module_id=$1", bms_module_id)
    try:
        return clean_params(json.loads(r) if isinstance(r, str) else (r or {}))
    except ValueError:
        return dict(DEFAULTS)


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


def next_power(p_kw: float, t_return_s: float, params: dict) -> float:
    """Výkon dalšího cyklu: poměrem cílová / změřená doba návratu (0,25× až 2×), nejvýš p_max."""
    target = float(params["t_return_min"]) * 60
    k = max(0.25, min(2.0, target / max(1.0, t_return_s)))
    return round(min(float(params["p_max_kw"]), p_kw * k), 2)


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
    await _update(b["id"], status=status, state=st, result=result, ended_at=now)
    await _release(b["inverter_id"], reason)
    logger.info("balancování #%s: %s (%s)", b["id"], status, reason)


async def _tick_one(b: dict, now: datetime) -> None:
    from ems.battest import db as bt_db
    p, st, bid = b["params"], b["state"], b["id"]
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
    phase, cycle = b["phase"], b["cycle"]
    p_kw = float(st.get("p_kw") or p["p_max_kw"])
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

    if phase == "charge":
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
            t_dis = round(float(c.get("t_charge_s") or 0) * float(p["dis_ratio"]))
            c["t_discharge_plan_s"] = t_dis
            msg = (f"Cyklus {cycle}: návrat pod {p['delta_resume_v'] * 1000:g} mV za {round(t_phase)} s" if back
                   else f"Cyklus {cycle}: rozpětí {delta} mV se do {p['max_wait_min']:g} min pod mez nevrátilo")
            if t_dis >= TICK_S and (soc is None or soc > SOC_DIS_FLOOR):
                go("discharge", msg + f" → vybíjení {p_kw:g} kW na {t_dis} s")
                await _force(b, "force_discharge", p_kw, f"cyklus {cycle} vybíjení")
                p_set = -p_kw
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
            nxt = next_power(p_kw, float(c.get("t_return_s") or 0) or float(p["t_return_min"]) * 60, p)
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
            go("charge", f"Cyklus {cycle}: nabíjení {nxt:g} kW (předchozí {p_kw:g} kW, doba návratu {c.get('t_return_s')} s, cíl {p['t_return_min'] * 60:g} s)")
            p_set = await _breaker_cap(b, nxt, inv)
            await _force(b, "force_charge", p_set, f"cyklus {cycle} nabíjení")
        else:
            p_set = -p_kw
            await _force(b, "force_discharge", p_kw, f"cyklus {cycle} vybíjení")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bms_balance_samples (balance_id,t,phase,cycle,p_set,p_bat,vmax,vmin,vavg,delta,nmax,nmin,soc) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
            bid, now, phase, cycle, p_set, (float(p_bat) / 1000 if p_bat is not None else None), vmax, vmin, round(vavg, 2), delta,
            mv.index(vmax) + 1, mv.index(vmin) + 1, soc)
    await _update(bid, phase=phase, cycle=cycle, state=st)


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
            "WHERE status='running' AND heartbeat_at < now() - make_interval(secs => $1) RETURNING id, inverter_id", WATCHDOG_S)
    for r in rows:
        await _release(r["inverter_id"], "řídicí smyčka neodpovídala")
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
    return {"params": await saved_defaults(bms_module_id), "builtin": DEFAULTS, "limits": LIMITS}


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
            bms_module_id, json.dumps(params), user.get("username"))
    return {"params": params}


@router.post("/start")
async def start(body: StartBody, user: dict = Depends(controller)) -> dict:
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Spuštění vyžaduje potvrzení.")
    ctx = await _context(body.bms_module_id)
    try:
        params = clean_params(body.params, await saved_defaults(body.bms_module_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from ems.battest import db as bt_db
    if ctx["inverter_id"] in await bt_db.running_modules():
        raise HTTPException(status_code=409, detail="Měnič je právě obsazený testem baterie nebo jiným balancováním.")
    lv = live.latest(body.bms_module_id)
    now = datetime.now(timezone.utc)
    state = {"p_kw": params["p_max_kw"], "phase_at": now.isoformat(), "cycles": [], "params_log": [],
             "log": [{"t": now.isoformat(), "text": f"Spuštěno ({user.get('username')}), nabíjení {params['p_max_kw']:g} kW"}],
             "had_live": bool(lv)}
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO bms_balance (bms_module_id, inverter_id, locality_id, block_idx, params, state, created_by) "
            "VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7) RETURNING *",
            body.bms_module_id, ctx["inverter_id"], ctx["locality_id"], ctx["block_idx"], json.dumps(params), json.dumps(state),
            user.get("username"))
    live.touch(body.bms_module_id)
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
    changed = {k: [b["params"].get(k), v] for k, v in params.items() if b["params"].get(k) != v}
    if changed:
        now = datetime.now(timezone.utc).isoformat()
        st = b["state"]
        st.setdefault("params_log", []).append({"t": now, "by": user.get("username"), "changed": changed})
        txt = ", ".join(f"{k} {a:g} → {v:g}" for k, (a, v) in changed.items())
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
