"""eWeLink endpointy: OAuth připojení, výpis a ovládání zařízení."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import client

router = APIRouter(prefix="/api/ewelink", tags=["ewelink"])


@router.get("/devices")
async def devices(_: dict = Depends(require_permission("admin"))):
    if not client.configured():
        return {"configured": False, "connected": False, "devices": []}
    if not await client.connected():
        return {"configured": True, "connected": False, "devices": []}
    try:
        return {"configured": True, "connected": True, "devices": await client.list_devices()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/auth-url")
async def auth_url(_: dict = Depends(require_permission("admin"))):
    if not client.configured():
        raise HTTPException(status_code=400, detail="Chybí EMS_EWELINK_APPID/SECRET v .env")
    return {"url": client.build_login_url()}


@router.get("/callback")
async def callback(code: str = "", region: str = "", state: str = ""):
    base = os.getenv("EMS_BASE_URL", "http://localhost:8080").rstrip("/")
    if not code:
        return RedirectResponse(url=f"{base}/ewelink?ewelink=error")
    try:
        await client.exchange_code(code, region or None)
    except Exception:
        return RedirectResponse(url=f"{base}/ewelink?ewelink=error")
    return RedirectResponse(url=f"{base}/ewelink?ewelink=connected")


class SwitchBody(BaseModel):
    deviceid: str
    on: bool


@router.post("/switch")
async def switch(body: SwitchBody, _: dict = Depends(require_permission("control"))):
    try:
        await client.set_switch(body.deviceid, body.on)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True}
