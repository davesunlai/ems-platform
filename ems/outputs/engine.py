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
            "export_kw": max(0.0, float(grid or 0) / 1000.0),  # kladné grid_power = export
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
    """True, pokud se po CELÝCH posledních `minutes` bral ze sítě import > kw."""
    ids = await _loc_device_ids(locality_id)
    if not ids:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT max(value) AS worst, min(time) AS first, count(*) AS n FROM samples "
            "WHERE device_id=ANY($1::text[]) AND metric='grid_power' "
            f"AND time > now() - interval '{int(minutes)} minutes'", ids)
    if not row or not row["n"] or row["worst"] is None:
        return False
    # data musí pokrýt aspoň 80 % okna, jinak nevíme
    span = (datetime.now(timezone.utc) - row["first"]).total_seconds() / 60.0
    if span < minutes * 0.8:
        return False
    # kladné grid_power = export → import je záporné; "po celou dobu import > kw"
    # = i ten nejmenší import (nejvyšší grid_power) je pod -kw*1000 W
    return float(row["worst"]) <= -kw * 1000.0


async def _decide_soc(o: dict, soc: float) -> tuple[bool, object, str]:
    """Vrací (desired, lock_until|None, reason). lock_until = nastavit zámek po hlídači sítě."""
    p = o["params"]
    upper = float(p.get("upper_soc", 100)); lower = float(p.get("lower_soc", 95))
    on = o["is_on"]
    now_utc = datetime.now(timezone.utc)

    # 1) zámek po hlídači sítě – drž vypnuto
    lock = o.get("off_lock_until")
    if lock and now_utc < lock:
        return False, None, f"uzamčeno hlídačem sítě do {lock.astimezone(_PRAGUE):%H:%M}"

    # 2) denní okno (lokální čas) – mimo něj vypnout
    ds, de = p.get("day_start"), p.get("day_end")
    if ds not in (None, "") and de not in (None, ""):
        h = datetime.now(_PRAGUE).hour
        if not (float(ds) <= h < float(de)):
            return False, None, f"mimo denní okno {ds}–{de} h (teď {h})"

    # 3) hlídač sítě – jen když je sepnuto: import > kw po celé okno → vypnout + zámek
    gk, gm = p.get("grid_guard_kw"), p.get("grid_guard_min")
    if on and gk not in (None, "") and gm not in (None, "") and float(gk) > 0 and float(gm) > 0:
        if await _grid_import_sustained(o["locality_id"], float(gk), float(gm)):
            lock_min = float(p.get("guard_lock_min", 120))
            return (False, now_utc + timedelta(minutes=lock_min),
                    f"hlídač sítě: import >{gk} kW déle než {gm} min → vypnuto (zámek {lock_min:.0f} min)")

    # 4) SoC hystereze
    if not on and soc >= upper:
        on = True
    elif on and soc <= lower:
        on = False
    return on, None, f"SoC={soc:.0f} % (mez {lower:.0f}–{upper:.0f})"


def _decide_surplus(o: dict, tele: dict, spot) -> tuple[bool, str]:
    p = o["params"]
    need_kw = float(p.get("surplus_kw", 1.0))
    soc_min = float(p.get("soc_min", 0))
    spot_max = p.get("spot_max", None)
    min_on_min = float(p.get("min_on_min", 0))
    exp = tele["export_kw"]; soc = tele["soc"]
    if exp is None or soc is None:
        return o["is_on"], "no_data:telemetrie lokality"

    spot_force = spot_max is not None and spot is not None and float(spot) <= float(spot_max)
    on = o["is_on"]
    if not on:
        desired = (exp >= need_kw and soc >= soc_min) or spot_force
    else:
        # drž, dokud je aspoň poloviční přebytek (hystereze), nebo levný spot
        desired = (exp >= need_kw * 0.5 and soc >= max(0.0, soc_min - 5)) or spot_force

    # minimální doba sepnutí
    if on and not desired and min_on_min > 0 and o.get("on_since"):
        elapsed = (datetime.now(timezone.utc) - o["on_since"]).total_seconds() / 60.0
        if elapsed < min_on_min:
            desired = True
    reason = f"přebytek={exp:.1f} kW (práh {need_kw:.1f}), SoC={soc:.0f}≥{soc_min:.0f}"
    if spot_max is not None:
        reason += f", spot={spot if spot is not None else '?'}≤{spot_max}{' →sepnout' if spot_force else ''}"
    return desired, reason


async def evaluate_outputs() -> None:
    spot = await _spot_price()
    for o in await out_db.list_all():
        if not o["enabled"]:
            continue
        try:
            if o["trigger"] == "soc":
                soc = (await _loc_telemetry(o["locality_id"]))["soc"] if o["locality_id"] else await _device_soc(o["target"])
                if soc is None:
                    await out_db.set_decision(o["id"], "no_data:soc")
                    continue
                desired, lock_until, reason = await _decide_soc(o, soc)
                if lock_until is not None:
                    await out_db.set_lock(o["id"], lock_until)
            else:  # surplus
                tele = await _loc_telemetry(o["locality_id"])
                desired, reason = _decide_surplus(o, tele, spot)
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
                                    {"on": desired, "trigger": o["trigger"]}, True, res)
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
                                    {"on": desired}, False, {"error": str(exc)})
            await out_db.set_decision(o["id"], f"přepnutí selhalo: {exc}")
            logger.warning("Výstup [%s] přepnutí selhalo: %s", o["name"], exc)
