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
    return {"module_ids": mods, "state": row, "session": (sess[0] if sess and not sess[0].get("ended_at") else None)}


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


@router.get("/admin/modules/{module_id}/ev-timeline")
async def ev_timeline(module_id: str, hours: int = 24, _: dict = Depends(read)) -> list[dict]:
    from ems.adapters.goe_charger.adapter import MODEL_STATUS_CZ, CAR_STATE
    rows = await ev_db.status_timeline(module_id, max(1, min(hours, 168)))
    for r in rows:
        r["model_status_cz"] = MODEL_STATUS_CZ.get(r.get("model_status"), str(r.get("model_status")))
        r["car_state"] = CAR_STATE.get(r.get("car"), "unknown")
    return rows
