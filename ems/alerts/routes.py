"""Endpoint agregovaných výstrah."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ems.auth.deps import require_permission
from . import service

router = APIRouter(tags=["alerts"])


@router.get("/api/alerts")
async def list_alerts(user: dict = Depends(require_permission("read"))):
    alerts = await service.collect_for_user(user)
    return {"count": len(alerts), "alerts": alerts}
