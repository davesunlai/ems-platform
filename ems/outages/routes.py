"""Endpointy plánovaných odstávek."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.localities import db as loc_db
from . import db, service

router = APIRouter(tags=["outages"])


@router.get("/api/localities/{loc_id}/outages")
async def list_outages(loc_id: int, _: dict = Depends(require_permission("read"))):
    loc = await loc_db.get(loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    return {
        "locality_id": loc_id,
        "query_by": service.query_kind(loc),
        "outages": await db.list_for_locality(loc_id, upcoming_only=True),
    }


@router.post("/api/admin/localities/{loc_id}/outages/refresh")
async def refresh_outages(loc_id: int, _: dict = Depends(require_permission("admin"))):
    loc = await loc_db.get(loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    if service.query_for_locality(loc) is None:
        raise HTTPException(status_code=400, detail="Lokalita nemá vyplněný EAN, elektroměr ani adresu")
    try:
        n = await service.refresh_locality(loc)
        await service.notify_locality(loc)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ČEZ dotaz selhal: {exc}")
    return {"fetched": n, "outages": await db.list_for_locality(loc_id, upcoming_only=True)}
