"""Historie energií pro LCD panel (sloupce den / měsíc / rok): z denních čítačů měniče (energy_*_today) — max za pražský den
přes samples_15m, součet přes zařízení lokality. Odolné proti výpadkům kolektoru (čítač drží měnič)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from ems.api.db import get_pool
from ems.auth.deps import require_permission

router = APIRouter(prefix="/api/localities", tags=["energy-history"])
read = require_permission("read")
TZ = ZoneInfo("Europe/Prague")
METRICS = {"energy_today": "pv", "energy_bat_charge_today": "bat_chg", "energy_bat_discharge_today": "bat_dis",
           "energy_import_today": "imp", "energy_export_today": "exp", "energy_load_today": "load"}


async def _device_ids(locality_id: int) -> list[str]:
    from ems.localities import db as loc_db
    return [d["id"] for d in await loc_db.devices_for_locality(locality_id)]


@router.get("/{locality_id}/energy-history")
async def energy_history(locality_id: int, period: str = "day", at: str | None = None, _: dict = Depends(read)) -> dict:
    """period=day&at=YYYY-MM → dny měsíce; period=month&at=YYYY → měsíce roku; period=year → roky."""
    ids = await _device_ids(locality_id)
    today = datetime.now(TZ).date()
    if period == "day":
        y, m = map(int, (at or today.strftime("%Y-%m")).split("-"))
        start = date(y, m, 1); end = date(y + (m == 12), (m % 12) + 1, 1)
        trunc = "day"; fmt = "DD"; labels = [str(d) for d in range(1, (end - start).days + 1)]
    elif period == "month":
        y = int(at or today.year)
        start = date(y, 1, 1); end = date(y + 1, 1, 1)
        trunc = "month"; fmt = "MM"; labels = [str(i) for i in range(1, 13)]
    elif period == "year":
        start = date(2000, 1, 1); end = date(today.year + 1, 1, 1)
        trunc = "year"; fmt = "YYYY"; labels = None
    else:
        raise HTTPException(status_code=400, detail="period: day | month | year")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT to_char(date_trunc('{trunc}', day), '{fmt}') AS k, metric, sum(day_kwh) AS kwh FROM (
                SELECT device_id, metric, date_trunc('day', bucket AT TIME ZONE 'Europe/Prague') AS day, max(max) AS day_kwh
                FROM samples_15m
                WHERE device_id = ANY($1::text[]) AND metric = ANY($2::text[])
                  AND bucket >= ($3::date::timestamp AT TIME ZONE 'Europe/Prague') AND bucket < ($4::date::timestamp AT TIME ZONE 'Europe/Prague')
                GROUP BY device_id, metric, day) t
            GROUP BY 1, 2 ORDER BY 1""", ids, list(METRICS), start, end)
    data: dict[str, dict] = {}
    for r in rows:
        k = r["k"].lstrip("0") if trunc != "year" else r["k"]
        data.setdefault(k, {})[METRICS[r["metric"]]] = round(float(r["kwh"] or 0), 1)
    if labels is None:
        labels = sorted(data) or [str(today.year)]
    out = [{"label": k, **{v: data.get(k, {}).get(v, 0.0) for v in METRICS.values()}} for k in labels]
    totals = {v: round(sum(x[v] for x in out), 1) for v in METRICS.values()}
    return {"period": period, "at": at, "rows": out, "totals": totals,
            "prev": _shift(period, at or (today.strftime("%Y-%m") if period == "day" else str(today.year)), -1),
            "next": _shift(period, at or (today.strftime("%Y-%m") if period == "day" else str(today.year)), +1)}


def _shift(period: str, at: str, d: int) -> str | None:
    if period == "year":
        return None
    if period == "day":
        y, m = map(int, at.split("-")); m += d
        if m == 0: y, m = y - 1, 12
        if m == 13: y, m = y + 1, 1
        return f"{y:04d}-{m:02d}"
    return str(int(at) + d)
