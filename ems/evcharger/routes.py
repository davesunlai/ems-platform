"""API wallboxu: stav, relace, denní kWh, timeline modelStatus, série výkonu."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Prague")


def _month_range(month: str) -> tuple[datetime, datetime]:
    y, m = (int(x) for x in month.split("-")[:2])
    start = datetime(y, m, 1, tzinfo=_TZ)
    end = datetime(y + (m // 12), (m % 12) + 1, 1, tzinfo=_TZ)
    return start, end

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.localities import db as loc_db
from . import db as ev_db

router = APIRouter(prefix="/api", tags=["ev-charger"])
read = require_permission("read")


async def _ev_modules(locality_id: int) -> list[str]:
    devs = await loc_db.devices_for_locality(locality_id)
    return [d["id"] for d in devs if (d.get("device_type") or d.get("type")) == "ev_charger"]


def _need(mods):
    if not mods:
        raise HTTPException(status_code=404, detail="lokalita nemá modul ev_charger")


@router.get("/localities/{locality_id}/ev/state")
async def ev_state(locality_id: int, _: dict = Depends(read)) -> dict:
    mods = await _ev_modules(locality_id); _need(mods)
    row = await ev_db.latest_for_modules(mods)
    if row:
        row["ts"] = row["ts"].isoformat()
        from ems.adapters.goe_charger.adapter import MODEL_STATUS_CZ, CAR_STATE
        row["model_status_cz"] = MODEL_STATUS_CZ.get(row.get("model_status"), str(row.get("model_status")))
        row["car_state"] = CAR_STATE.get(row.get("car"), "unknown")
    sess = await ev_db.sessions(mods, 1)
    open_s = sess[0] if sess and not sess[0].get("ended_at") else None
    if row is not None:
        row["car_vin"] = open_s.get("car_vin") if open_s else None       # auto přiřazené kolektorem k běžící relaci
        row["car_name"] = open_s.get("car_name") if open_s else None
    return {"module_ids": mods, "state": row, "session": open_s}


@router.put("/ev/sessions/{session_id}/car")
async def ev_session_set_car(session_id: int, body: dict, _: dict = Depends(require_permission("control"))):
    """Ruční určení auta u relace wallboxu (když CarData nedává důkaz). body: {vin} nebo {vin: null}."""
    from ems.cars import db as cars_db
    vin = (body or {}).get("vin")
    name = None
    if vin:
        v = next((x for x in await cars_db.list_vehicles() if x["vin"] == vin), None)
        if not v:
            raise HTTPException(status_code=404, detail="VIN nenalezen")
        name = v.get("name") or v.get("model") or vin[-6:]
    await ev_db.set_session_car(session_id, vin, name)
    return {"ok": True, "session_id": session_id, "car_vin": vin, "car_name": name}


@router.get("/localities/{locality_id}/ev/sessions")
async def ev_sessions(locality_id: int, limit: int = 50, month: str | None = None, _: dict = Depends(read)) -> list[dict]:
    mods = await _ev_modules(locality_id); _need(mods)
    if month:
        try:
            s, e = _month_range(month)
        except Exception:
            raise HTTPException(status_code=400, detail="month = YYYY-MM")
        return await ev_db.sessions(mods, max(1, min(limit, 500)), s, e)
    return await ev_db.sessions(mods, max(1, min(limit, 500)))


@router.get("/localities/{locality_id}/ev/daily")
async def ev_daily(locality_id: int, days: int = 31, month: str | None = None, _: dict = Depends(read)) -> list[dict]:
    mods = await _ev_modules(locality_id); _need(mods)
    if month:
        try:
            s, e = _month_range(month)
        except Exception:
            raise HTTPException(status_code=400, detail="month = YYYY-MM")
        return await ev_db.daily(mods, s, e, live=True)
    end = datetime.now(timezone.utc) + timedelta(days=1)
    return await ev_db.daily(mods, end - timedelta(days=max(1, min(days, 366))), end)


@router.get("/localities/{locality_id}/ev/series")
async def ev_series(locality_id: int, hours: int = 24, _: dict = Depends(read)) -> list[dict]:
    mods = await _ev_modules(locality_id); _need(mods)
    return await ev_db.series(mods, max(1, min(hours, 720)))


@router.get("/localities/{locality_id}/ev/month")
async def ev_month(locality_id: int, month: str, _: dict = Depends(read)) -> dict:
    """Měsíční přehled: dny (kWh z čítače) + úseky nabíjení rozdělené po dnech (z telemetrie)."""
    mods = await _ev_modules(locality_id); _need(mods)
    try:
        s, e = _month_range(month)
    except Exception:
        raise HTTPException(status_code=400, detail="month = YYYY-MM")
    daily = await ev_db.daily(mods, s, e, live=True)
    runs = await ev_db.charging_runs(mods, s, e)
    return {"month": month, "daily": daily, "runs": runs}


@router.get("/localities/{locality_id}/ev/day")
async def ev_day(locality_id: int, date: str, _: dict = Depends(read)) -> dict:
    """Detail dne: průběh výkonu po minutě, úseky nabíjení, relace zasahující do dne."""
    mods = await _ev_modules(locality_id); _need(mods)
    try:
        y, m, d = (int(x) for x in date.split("-")[:3])
        s = datetime(y, m, d, tzinfo=_TZ); e = s + timedelta(days=1)
    except Exception:
        raise HTTPException(status_code=400, detail="date = YYYY-MM-DD")
    series = await ev_db.day_series(mods, s, e)
    runs = await ev_db.charging_runs(mods, s, e)
    from ems.api.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        srows = await conn.fetch(
            "SELECT * FROM ev_sessions WHERE module_id = ANY($1::text[]) AND started_at < $3 AND COALESCE(ended_at, now()) >= $2 ORDER BY started_at",
            mods, s, e)
    sessions = []
    for r in srows:
        dd = dict(r)
        for k in ("started_at", "ended_at"):
            if dd.get(k):
                dd[k] = dd[k].isoformat()
        sessions.append(dd)
    for r in runs:   # auto k úseku = relace (kabel), do které úsek spadá
        sess = next((x for x in srows if x["started_at"].isoformat() <= r["end"] and (x["ended_at"] is None or x["ended_at"].isoformat() >= r["start"])), None)
        r["car_vin"], r["car_name"] = (sess["car_vin"], sess["car_name"]) if sess else (None, None)
    tot = round(sum(r["kwh"] for r in runs), 2)
    return {"date": date, "series": series, "runs": runs, "sessions": sessions, "kwh_runs": tot}


@router.get("/admin/modules/{module_id}/ev-timeline")
async def ev_timeline(module_id: str, hours: int = 24, _: dict = Depends(read)) -> list[dict]:
    from ems.adapters.goe_charger.adapter import MODEL_STATUS_CZ, CAR_STATE
    rows = await ev_db.status_timeline(module_id, max(1, min(hours, 168)))
    for r in rows:
        r["model_status_cz"] = MODEL_STATUS_CZ.get(r.get("model_status"), str(r.get("model_status")))
        r["car_state"] = CAR_STATE.get(r.get("car"), "unknown")
    return rows
