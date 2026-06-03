"""eWeLink endpointy (test připojení + výpis zařízení)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from . import client

router = APIRouter(prefix="/api/ewelink", tags=["ewelink"])


@router.get("/devices")
async def devices(_: dict = Depends(require_permission("admin"))):
    if not client.configured():
        return {"configured": False, "devices": []}
    try:
        return {"configured": True, "devices": await client.list_devices()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
