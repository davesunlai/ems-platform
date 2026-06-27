"""Vyhodnocení spínacích výstupů.

Cíl: suchý kontakt střídače (goodwe) NEBO eWeLink spínač.
Spouštěč:
  - 'soc'     : hystereze dle SoC (sepni ≥ upper, rozepni ≤ lower)
  - 'surplus' : přebytek FVE do sítě ≥ práh A SoC ≥ min; volitelně záporný/levný
                spot ≤ limit sepne i bez přebytku. Hystereze + min. doba sepnutí.
Stav (is_on, on_since) se drží v DB → edge-trigger, žádné poskakování.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

_PRAGUE = ZoneInfo("Europe/Prague")


def _hm_to_min(v):
    """ "HH:MM" -> minuty od půlnoci; staré celé hodiny (číslo) -> hodiny*60; jinak None."""
    if v in (None, ""):
        return None
    s = str(v).strip()
    if ":" in s:
        try:
            hh, mm = s.split(":")[:2]
            return (int(hh) % 24) * 60 + int(mm)
        except Exception:
            return None
    try:
        return int(float(s)) * 60   # zpětná kompatibilita: dřív se zadávaly celé hodiny
    except Exception:
        return None


def _min_to_hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"

from ems.api.db import get_pool
from ems.control import db as control_db
from ems.control.goodwe_control import set_load_switch
from ems.ewelink import client as ewelink
from ems.modules import db as modules_db
from . import db as out_db

logger = logging.getLogger("ems.outputs")


async def _loc_device_ids(locality_id) -> list[str]:
    if not locality_id:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM modules WHERE locality_id = $1", locality_id)
    return [r["id"] for r in rows]


async def _loc_telemetry(locality_id) -> dict:
    ids = await _loc_device_ids(locality_id)
    if not ids:
        return {"pv_kw": None, "export_kw": None, "soc": None}
    pool = await get_pool()
    async with pool.acquire() as conn:
        pv = await conn.fetchval(
            "SELECT COALESCE(SUM(v),0) FROM (SELECT DISTINCT ON (device_id) value v FROM samples "
            "WHERE device_id=ANY($1::text[]) AND metric='pv_power' AND time>now()-interval '5 minutes' "
            "ORDER BY device_id, time DESC) t", ids)
        grid = await conn.fetchval(
            "SELECT COALESCE(SUM(v),0) FROM (SELECT DISTINCT ON (device_id) value v FROM samples "
            "WHERE device_id=ANY($1::text[]) AND metric='grid_power' AND time>now()-interval '5 minutes' "
            "ORDER BY device_id, time DESC) t", ids)
        soc = await conn.fetchval(
            "SELECT AVG(v) FROM (SELECT DISTINCT ON (device_id) value v FROM samples "
            "WHERE device_id=ANY($1::text[]) AND metric='battery_soc' AND time>now()-interval '10 minutes' "
            "ORDER BY device_id, time DESC) t", ids)
    return {"pv_kw": float(pv or 0) / 1000.0,
            "export_kw": max(0.0, -float(grid or 0) / 1000.0),  # ZÁPORNÉ grid_power = export (do sítě)
            "soc": float(soc) if soc is not None else None}


async def _device_soc(device_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM samples WHERE device_id=$1 AND metric='battery_soc' "
            "AND time>now()-interval '10 minutes' ORDER BY time DESC LIMIT 1", device_id)
    return float(row["value"]) if row else None


async def _spot_price():
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT price FROM market_state WHERE id = 1")


async def _actuate(o: dict, desired: bool) -> dict:
    if o["output_kind"] == "ewelink":
        await ewelink.set_switch(o["target"], desired)
        return {"ewelink": o["target"], "on": desired}
    mod = await modules_db.get(o["target"])
    if not mod or mod.adapter != "goodwe" or not mod.params.get("host"):
        raise RuntimeError("cílový střídač nemá host/port")
    return await set_load_switch(mod.params["host"], int(mod.params.get("port", 8899)), desired)


async def _grid_import_sustained(locality_id, kw: float, minutes: float) -> bool:
    """True, pokud po CELÝCH posledních `minutes` byl výkon ze sítě ≥ práh `kw`.

    Práh `kw` i grid_power v konvenci dashboardu: + odběr ze sítě, − dodávka do sítě.
    „Po celou dobu ≥ kw" = i nejhorší okamžik (min grid_power) je ≥ kw·1000 W.
    """
    ids = await _loc_device_ids(locality_id)
    if not ids:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT min(value) AS worst, min(time) AS first, count(*) AS n FROM samples "
            "WHERE device_id=ANY($1::text[]) AND metric='grid_power' "
            f"AND time > now() - interval '{int(minutes)} minutes'", ids)
    if not row or not row["n"] or row["worst"] is None:
        return False
    # data musí pokrýt aspoň 80 % okna, jinak nevíme
    span = (datetime.now(timezone.utc) - row["first"]).total_seconds() / 60.0
    if span < minutes * 0.8:
        return False
    # + odběr / − dodávka. „Po celou dobu odběr ≥ kw" = i nejmenší okamžik (min grid_power) ≥ kw·1000 W
    return float(row["worst"]) >= kw * 1000.0


async def _grid_export_sustained(locality_id, kw: float, minutes: float) -> bool:
    """True, pokud po CELÝCH posledních `minutes` byl výkon ze sítě ≤ práh `kw` (dost dodávky).

    Práh `kw` i grid_power v konvenci dashboardu: + odběr, − dodávka.
    „Po celou dobu ≤ kw" = i nejhorší okamžik (max grid_power) je ≤ kw·1000 W.
    """
    ids = await _loc_device_ids(locality_id)
    if not ids:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT max(value) AS best, min(time) AS first, count(*) AS n FROM samples "
            "WHERE device_id=ANY($1::text[]) AND metric='grid_power' "
            f"AND time > now() - interval '{int(minutes)} minutes'", ids)
    if not row or not row["n"] or row["best"] is None:
        return False
    span = (datetime.now(timezone.utc) - row["first"]).total_seconds() / 60.0
    if span < minutes * 0.8:
        return False
    return float(row["best"]) <= kw * 1000.0


async def _decide_soc(o: dict, soc: float) -> tuple[bool, object, str, dict]:
    """Vrací (desired, lock_until|None, reason, detail). detail = naměřené hodnoty pro audit."""
    p = o["params"]
    upper = float(p.get("upper_soc", 100)); lower = float(p.get("lower_soc", 95))
    on = o["is_on"]
    now_utc = datetime.now(timezone.utc)
    nowloc = datetime.now(_PRAGUE)
    det = {"SoC_%": round(soc, 1), "sepni_pri_>=_%": upper, "rozepni_pri_<=_%": lower,
           "byl_zapnuty": on, "cas": nowloc.strftime("%H:%M")}

    # 1) zámek po hlídači sítě – drž vypnuto
    lock = o.get("off_lock_until")
    if lock and now_utc < lock:
        det["zamek_do"] = lock.astimezone(_PRAGUE).strftime("%H:%M")
        return False, None, f"uzamčeno hlídačem sítě do {det['zamek_do']}", det

    # 2) denní okno (lokální čas) – mimo něj vypnout. Podpora HH:MM i starých celých hodin.
    ds, de = _hm_to_min(p.get("day_start")), _hm_to_min(p.get("day_end"))
    if ds is not None and de is not None:
        nowm = nowloc.hour * 60 + nowloc.minute
        det["okno"] = f"{_min_to_hm(ds)}–{_min_to_hm(de)}"
        inside = (ds <= nowm < de) if ds <= de else (nowm >= ds or nowm < de)  # de<ds = přes půlnoc
        if not inside:
            return False, None, f"mimo denní okno {det['okno']} (teď {det['cas']})", det

    # 3) hlídač sítě – jen když je sepnuto. Práh v konvenci dashboardu: + odběr, − dodávka.
    #    Operátor (≥/≤) volitelný; ≥ = vypni při málo dodávky/nákupu, ≤ = vypni při hodně dodávky.
    gk, gm = p.get("grid_guard_kw"), p.get("grid_guard_min")
    gop = p.get("grid_guard_op", "ge")
    if on and gk not in (None, "") and gm not in (None, "") and float(gm) > 0:
        fn = _grid_import_sustained if gop == "ge" else _grid_export_sustained
        if await fn(o["locality_id"], float(gk), float(gm)):
            lock_min = float(p.get("guard_lock_min", 30))
            gkf = float(gk); op_txt = "≥" if gop == "ge" else "≤"
            det["hlidac_op"] = op_txt; det["hlidac_prah_kW"] = gkf
            det["hlidac_min"] = float(gm); det["hlidac_zamek_min"] = lock_min
            return (False, now_utc + timedelta(minutes=lock_min),
                    f"hlídač sítě: výkon ze sítě {op_txt} {gkf:g} kW po {gm:g} min → vypnuto (nezapínat {lock_min:.0f} min)", det)

    # 4) SoC hystereze (+ volitelná ZAPÍNACÍ podmínka na výkon ze sítě, operátor ≤/≥)
    gon_kw, gon_min = p.get("grid_on_kw"), p.get("grid_on_min")
    gon_op = p.get("grid_on_op", "le")
    if not on and soc >= upper:
        gate_ok = True
        if gon_kw not in (None, "") and gon_min not in (None, "") and float(gon_min) > 0:
            fn = _grid_import_sustained if gon_op == "ge" else _grid_export_sustained
            gate_ok = await fn(o["locality_id"], float(gon_kw), float(gon_min))
            op_txt = "≥" if gon_op == "ge" else "≤"
            det["zapinaci_op"] = op_txt; det["zapinaci_prah_kW"] = float(gon_kw); det["zapinaci_min"] = float(gon_min)
        if gate_ok:
            on = True
            reason = f"SoC {soc:.0f} % ≥ {upper:.0f} % → zapnuto"
        else:
            reason = (f"SoC {soc:.0f} % ≥ {upper:.0f} %, ale čeká na síť "
                      f"({op_txt} {float(gon_kw):g} kW po {float(gon_min):g} min)")
    elif on and soc <= lower:
        on = False
        reason = f"SoC {soc:.0f} % ≤ {lower:.0f} % → vypnuto"
    else:
        reason = f"SoC {soc:.0f} % v pásmu {lower:.0f}–{upper:.0f} % → beze změny ({'zapnuto' if on else 'vypnuto'})"
    return on, None, reason, det


def _decide_surplus(o: dict, tele: dict, spot) -> tuple[bool, str, dict]:
    p = o["params"]
    need_kw = float(p.get("surplus_kw", 1.0))
    soc_min = float(p.get("soc_min", 0))
    spot_max = p.get("spot_max", None)
    min_on_min = float(p.get("min_on_min", 0))
    exp = tele["export_kw"]; soc = tele["soc"]
    if exp is None or soc is None:
        return o["is_on"], "no_data:telemetrie lokality", {"export_kw": exp, "SoC_%": soc}

    spot_force = spot_max is not None and spot is not None and float(spot) <= float(spot_max)
    on = o["is_on"]
    if not on:
        desired = (exp >= need_kw and soc >= soc_min) or spot_force
    else:
        # drž, dokud je aspoň poloviční přebytek (hystereze), nebo levný spot
        desired = (exp >= need_kw * 0.5 and soc >= max(0.0, soc_min - 5)) or spot_force

    forced_min_on = False
    # minimální doba sepnutí
    if on and not desired and min_on_min > 0 and o.get("on_since"):
        elapsed = (datetime.now(timezone.utc) - o["on_since"]).total_seconds() / 60.0
        if elapsed < min_on_min:
            desired = True
            forced_min_on = True
    det = {"export_kW": round(exp, 2), "prah_kW": need_kw, "SoC_%": round(soc, 1), "SoC_min_%": soc_min}
    if spot_max is not None:
        det["spot"] = spot; det["spot_max"] = spot_max; det["spot_levny"] = spot_force
    if forced_min_on:
        det["drzeno_min_doba_min"] = min_on_min
    reason = f"přebytek {exp:.1f} kW (práh {need_kw:.1f}), SoC {soc:.0f} % ≥ {soc_min:.0f} %"
    if spot_max is not None:
        reason += f", spot {spot if spot is not None else '?'} ≤ {spot_max}{' → sepnout' if spot_force else ''}"
    if forced_min_on:
        reason += f" (drženo min. dobou {min_on_min:.0f} min)"
    return desired, reason, det


async def force_output(out_id: int, desired: bool, reason: str) -> bool:
    """Vynutí stav spínaného výstupu (vlastník = planner / Smart Control). Edge-trigger:
    zasáhne jen při změně. Vrací True, pokud reálně přepnul."""
    o = await out_db.get(out_id)
    if not o:
        return False
    if bool(o["is_on"]) == bool(desired):
        return False
    res = await _actuate(o, desired)
    await out_db.set_state(out_id, desired, f"Chytré řízení: {reason} → {'sepnuto' if desired else 'rozepnuto'}")
    await control_db.record("output:planner", o["target"], "switch",
                            {"on": desired, "name": o["name"], "reason": reason, "source": "planner"}, True, res)
    try:
        from ems.alerts import db as alerts_db
        await alerts_db.record_event(o.get("locality_id"), "output_on" if desired else "output_off",
                                     f"Spotřebič {o['name']} {'sepnut' if desired else 'rozepnut'} (chytré řízení)", reason)
        from ems.notify import dispatch as notify_dispatch
        await notify_dispatch.notify_new_alerts()
    except Exception:
        pass
    return True


async def evaluate_outputs() -> None:
    spot = await _spot_price()
    from ems.planner import db as planner_db
    claimed = await planner_db.claimed_output_ids()    # výstupy vlastněné zapnutým plannerem
    for o in await out_db.list_all():
        if not o["enabled"]:
            continue
        if o["id"] in claimed:
            continue   # řídí Chytré řízení (planner) — reaktivní pravidlo se nemíchá
        det = {}
        try:
            if o["trigger"] == "soc":
                soc = (await _loc_telemetry(o["locality_id"]))["soc"] if o["locality_id"] else await _device_soc(o["target"])
                if soc is None:
                    await out_db.set_decision(o["id"], "no_data:soc")
                    continue
                desired, lock_until, reason, det = await _decide_soc(o, soc)
                if lock_until is not None:
                    await out_db.set_lock(o["id"], lock_until)
            else:  # surplus
                tele = await _loc_telemetry(o["locality_id"])
                desired, reason, det = _decide_surplus(o, tele, spot)
        except Exception as exc:
            await out_db.set_decision(o["id"], f"chyba: {exc}")
            continue

        if desired == o["is_on"]:
            await out_db.set_decision(o["id"], f"{reason}; {'sepnuto' if o['is_on'] else 'rozepnuto'}")
            continue

        try:
            res = await _actuate(o, desired)
            await out_db.set_state(o["id"], desired, f"{reason} → {'sepnuto' if desired else 'rozepnuto'}")
            await control_db.record("output:auto", o["target"], "switch",
                                    {"on": desired, "trigger": o["trigger"], "name": o["name"], "reason": reason, "values": det}, True, res)
            try:
                from ems.alerts import db as alerts_db
                await alerts_db.record_event(
                    o.get("locality_id"), "output_on" if desired else "output_off",
                    f"Spotřebič {o['name']} {'sepnut' if desired else 'rozepnut'}", reason)
                from ems.notify import dispatch as notify_dispatch
                await notify_dispatch.notify_new_alerts()   # upozornění hned, ne až za 60 s
            except Exception:
                pass
            logger.info("Výstup [%s] → %s (%s)", o["name"], "ON" if desired else "OFF", reason)
        except Exception as exc:
            await control_db.record("output:auto", o["target"], "switch",
                                    {"on": desired, "trigger": o["trigger"], "name": o["name"], "reason": reason, "values": det}, False, {"error": str(exc)})
            await out_db.set_decision(o["id"], f"přepnutí selhalo: {exc}")
            logger.warning("Výstup [%s] přepnutí selhalo: %s", o["name"], exc)
