"""Edge detektor relací nabíjení (ev_sessions) — brief §2.

Relace začíná hranou car 1→(2|3|4) (auto připojeno), končí car→1 (odpojeno). Průběžně
se akumuluje: doba nabíjení, max výkon, max fází, wh (max session_wh), rozdělení energie
síť/FVE podle okamžité bilance lokality (grid_power > 0 → podíl ze sítě) a cena
(grid podíl × efektivní cena importu z ceníku + spot). Stav v DB → restart-safe (adopce
otevřené relace), osiřelá relace se uzavře posledním ts.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from ems.api.db import get_pool

logger = logging.getLogger(__name__)
_mem: dict[str, dict] = {}   # module_id -> {sid, last_ts(monotonic), last_power_w, last_wh}


async def _grid_share(locality_id: int | None, ev_w: float) -> float:
    """Podíl výkonu auta kryté ze sítě (0–1) podle aktuálního importu lokality."""
    if not locality_id or ev_w <= 0:
        return 0.0
    try:
        from ems.localities import db as loc_db
        from ems.api.db import aggregate_now
        devs = [d["id"] for d in await loc_db.devices_for_locality(locality_id)]
        agg = await aggregate_now(devs)
        imp = max(0.0, float(agg.get("grid_w") or 0.0))
        return max(0.0, min(1.0, imp / ev_w))
    except Exception:
        return 0.0


async def _import_price(locality_id: int | None, ts: datetime) -> float:
    try:
        from ems.pricing import db as pricing_db
        from ems.pricing import cost as pricing_cost
        from ems.market import db as market_db
        tariff = await pricing_db.get_effective(locality_id) if locality_id else None
        spot = await market_db.current_slot_price()
        return float(pricing_cost.price_czk_kwh(tariff, ts, spot)["import_czk"])
    except Exception:
        return 0.0


async def on_snapshot(module_id: str, d: dict, locality_id: int | None = None) -> None:
    pool = await get_pool()
    car = d.get("car")
    if car is None:
        return
    connected = car in (2, 3, 4)
    now_m = time.monotonic()
    m = _mem.get(module_id)
    async with pool.acquire() as conn:
        if m is None:
            row = await conn.fetchrow(
                "SELECT id FROM ev_sessions WHERE module_id=$1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1", module_id)
            if row and connected:
                m = {"sid": row["id"]}
                logger.info("Wallbox %s: adoptuji otevřenou relaci #%s", module_id, row["id"])
            else:
                if row:
                    last = await conn.fetchval("SELECT max(ts) FROM ev_telemetry WHERE module_id=$1", module_id)
                    await conn.execute(
                        "UPDATE ev_sessions SET ended_at=$2, wh=wh_max, ended_reason='orphan' WHERE id=$1",
                        row["id"], last or datetime.now(timezone.utc))
                m = {"sid": None}
            m.update(last_ts=now_m, last_power_w=float(d.get("power_w") or 0))
            _mem[module_id] = m

        sid = m.get("sid")
        if connected and sid is None:
            sid = await conn.fetchval(
                "INSERT INTO ev_sessions (module_id, started_at, eto_start, last_model_status, phases) "
                "VALUES ($1, now(), $2, $3, $4) RETURNING id",
                module_id, d.get("energy_total_wh"), d.get("model_status"), d.get("phases_active"))
            m.update(sid=sid, last_ts=now_m, last_power_w=float(d.get("power_w") or 0))
            logger.info("Wallbox %s: nová relace #%s (car=%s)", module_id, sid, car)
            return
        if sid is None:
            m.update(last_ts=now_m, last_power_w=float(d.get("power_w") or 0))
            return

        # průběžná akumulace (lichoběžník z posledního výkonu)
        dt = max(0.0, min(120.0, now_m - m.get("last_ts", now_m)))
        p_prev = float(m.get("last_power_w") or 0)
        p_now = float(d.get("power_w") or 0)
        kwh = (p_prev + p_now) / 2.0 * dt / 3.6e6
        grid_kwh = pv_kwh = cost = 0.0
        if kwh > 0:
            share = await _grid_share(locality_id, p_now)
            grid_kwh = kwh * share
            pv_kwh = kwh - grid_kwh
            cost = grid_kwh * await _import_price(locality_id, datetime.now(timezone.utc))
        await conn.execute(
            """UPDATE ev_sessions SET charging_s = charging_s + $2, wh_max = GREATEST(wh_max, $3),
                   max_power_w = GREATEST(max_power_w, $4), phases = GREATEST(COALESCE(phases,0), $5),
                   grid_kwh = grid_kwh + $6, pv_kwh = pv_kwh + $7, cost_czk = cost_czk + $8, last_model_status = $9
               WHERE id = $1""",
            sid, int(dt) if car == 2 else 0, float(d.get("session_wh") or 0), p_now,
            int(d.get("phases_active") or 0), grid_kwh, pv_kwh, cost, d.get("model_status"))
        m.update(last_ts=now_m, last_power_w=p_now)

        if not connected:
            reason = "error" if car in (0, 5) else "unplugged"
            await conn.execute(
                "UPDATE ev_sessions SET ended_at=now(), wh=GREATEST(wh_max, $2), ended_reason=$3 WHERE id=$1",
                sid, float(d.get("session_wh") or 0), reason)
            logger.info("Wallbox %s: relace #%s ukončena (%s)", module_id, sid, reason)
            m.update(sid=None)
