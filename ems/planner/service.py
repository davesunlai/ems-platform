"""Spojení plánovače s daty: predikce + ceny + stav baterie → plán do DB.
Plán se počítá vždy (poradně); řízení (enqueue) řeší kolektor podle `enabled`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from ems.api.db import get_pool, list_devices
from ems.forecast import db as fdb
from ems.localities import db as loc_db
from ems.pricing import db as pricing_db
from ems.pricing import cost as pricing_cost
from . import core, db as pdb

logger = logging.getLogger("ems.planner")


def _key(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()


async def _soc_now(device_ids: list[str]) -> float | None:
    if not device_ids:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT avg(v) FROM (SELECT DISTINCT ON (device_id) value AS v FROM samples "
            "WHERE device_id = ANY($1::text[]) AND metric='battery_soc' "
            "AND time > now() - interval '20 minutes' ORDER BY device_id, time DESC) t",
            device_ids)
    return float(v) if v is not None else None


async def run_locality(locality_id: int) -> dict:
    cfg = await pdb.get_config(locality_id)
    pv = await fdb.latest_pv(locality_id, "avg")
    if len(pv) < 2:
        return {"ok": False, "reason": "chybí predikce výroby"}
    load_rows = await fdb.latest_load(locality_id)
    spot = await fdb.spot_window_hourly(48)
    tariff = await pricing_db.get_effective(locality_id)

    load_map = {_key(datetime.fromisoformat(r["ts"])): r["load_w"] for r in load_rows}
    spot_map = {_key(datetime.fromisoformat(r["ts"])): r["czk_mwh"] for r in spot}

    now = datetime.now(timezone.utc)
    ts_list, pv_a, load_a, pimp, pexp = [], [], [], [], []
    for p in pv:
        t = datetime.fromisoformat(p["ts"])
        if t < now - timedelta(hours=1):
            continue
        if len(ts_list) >= int(cfg["horizon_h"]):
            break
        k = _key(t)
        sp = spot_map.get(k)
        price = pricing_cost.price_czk_kwh(tariff, t, sp)
        ts_list.append(t)
        pv_a.append((p["pv_w"] or 0) / 1000.0)
        load_a.append((load_map.get(k, 0) or 0) / 1000.0)
        pimp.append(price["import_czk"])
        pexp.append(price["export_czk"])

    if len(ts_list) < 2:
        return {"ok": False, "reason": "krátký horizont (málo predikce)"}

    devs = [d["id"] for d in await loc_db.devices_for_locality(locality_id)]
    soc_now = await _soc_now(devs)
    if soc_now is None:
        soc_now = max(cfg["soc_min_pct"], 30.0)        # bez telemetrie konzervativně
    floor = float(cfg["soc_min_pct"]) + float(cfg["outage_reserve_pct"])

    rows = core.plan(
        ts_list, pv_a, load_a, pimp, pexp,
        cap_kwh=float(cfg["capacity_kwh"]), soc_now_pct=soc_now, floor_pct=floor,
        max_charge_kwh=float(cfg["max_charge_kw"]), max_discharge_kwh=float(cfg["max_discharge_kw"]),
        allow_grid_discharge=bool(cfg["allow_grid_discharge"]))

    await pdb.write_schedule(locality_id, rows, now)
    return {"ok": True, "points": len(rows), "soc_now": round(soc_now, 1)}


async def _next_local_hour(now, hour: int):
    from zoneinfo import ZoneInfo
    pr = ZoneInfo("Europe/Prague")
    now_pr = now.astimezone(pr)
    loc = now_pr.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    if loc <= now_pr:
        loc = loc + timedelta(days=1)
    return loc.astimezone(timezone.utc)


async def amplitudes(locality_id: int, *, spiral_target_kwh: float | None = None,
                     spiral_power_kw: float = 6.0, spiral_deadline_h: int = 7,
                     breaker_kw: float = 22.0, max_windows: int = 4,
                     threshold_pct: float = 33.0) -> dict:
    """Spodní (valley/import) a horní (peak/export) amplitudy na EFEKTIVNÍ ceně + volitelně
    plán 6 kW spirály (binární deferrable). Čte stejné vstupy jako run_locality."""
    from . import amplitude
    cfg = await pdb.get_config(locality_id)
    pv = await fdb.latest_pv(locality_id, "avg")
    if len(pv) < 2:
        return {"ok": False, "reason": "chybí predikce výroby"}
    load_rows = await fdb.latest_load(locality_id)
    spot = await fdb.spot_window_hourly(48)
    tariff = await pricing_db.get_effective(locality_id)
    load_map = {_key(datetime.fromisoformat(r["ts"])): r["load_w"] for r in load_rows}
    spot_map = {_key(datetime.fromisoformat(r["ts"])): r["czk_mwh"] for r in spot}

    now = datetime.now(timezone.utc)
    ts_list, pv_a, load_a, pimp, pexp = [], [], [], [], []
    for p in pv:
        t = datetime.fromisoformat(p["ts"])
        if t < now - timedelta(hours=1):
            continue
        if len(ts_list) >= int(cfg["horizon_h"]):
            break
        k = _key(t)
        price = pricing_cost.price_czk_kwh(tariff, t, spot_map.get(k))
        ts_list.append(t)
        pv_a.append((p["pv_w"] or 0) / 1000.0)
        load_a.append((load_map.get(k, 0) or 0) / 1000.0)
        pimp.append(price["import_czk"]); pexp.append(price["export_czk"])
    if len(ts_list) < 2:
        return {"ok": False, "reason": "krátký horizont (málo predikce)"}

    amp = amplitude.find_amplitudes(ts_list, pimp, pexp, max_windows=max_windows, threshold_pct=threshold_pct)
    out = {"ok": True, "valley": amp["valley"], "peak": amp["peak"], "horizon_h": len(ts_list)}
    if spiral_target_kwh and spiral_target_kwh > 0:
        pv_surplus = [max(0.0, pv_a[i] - load_a[i]) for i in range(len(ts_list))]
        # MVP strop jističe: jistič − zátěž (souběžné nabíjení baterie zohledníme po napojení na plán)
        headroom = [max(0.0, float(breaker_kw) - load_a[i]) for i in range(len(ts_list))]
        deadline = await _next_local_hour(now, spiral_deadline_h)
        sp = amplitude.schedule_spiral_binary(
            ts_list, pimp, pv_surplus, energy_target_kwh=float(spiral_target_kwh),
            max_power_kw=float(spiral_power_kw), deadline=deadline,
            breaker_headroom_kw=headroom, now=now)
        sp["deadline"] = deadline
        out["spiral"] = sp
    return out


async def run_all() -> None:
    try:
        locs = await loc_db.list_all()
    except Exception as exc:
        logger.debug("planner run_all: %s", exc)
        return
    for loc in locs:
        lid = loc["id"] if isinstance(loc, dict) else getattr(loc, "id", None)
        if lid is None:
            continue
        try:
            await run_locality(lid)
        except Exception as exc:
            logger.warning("Planner lokalita %s: %s", lid, exc)


async def controlled_devices() -> dict[int, list[str]]:
    """{locality_id: [solis device_ids]} pro lokality se zapnutým plánovačem."""
    enabled = set(await pdb.all_enabled())
    if not enabled:
        return {}
    out: dict[int, list[str]] = {}
    for d in await list_devices():
        lid = d.get("locality_id")
        if lid in enabled and d.get("adapter") == "solis" and (d.get("control_enabled") or []):
            out.setdefault(lid, []).append(d["device_id"])
    return out
