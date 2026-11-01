"""API 🚘 Auta: účty (admin), vozidla, stav (read)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db, service

router = APIRouter(prefix="/api/cars", tags=["cars"])
read = require_permission("read")
admin = require_permission("admin")


class AccountIn(BaseModel):
    client_id: str
    locality_id: int | None = None


class VehiclePatch(BaseModel):
    name: str | None = None
    locality_id: int | None = None
    wallbox_module_id: str | None = None
    capacity_kwh: float | None = None
    key_map: dict | None = None
    enabled: bool | None = None


def _acc_public(a: dict) -> dict:
    keep = ("id", "locality_id", "client_id", "gcid", "status", "last_error", "user_code", "verification_uri",
            "device_expires_at", "access_expires_at", "refresh_expires_at", "stream_status", "stream_since",
            "stream_msgs", "rest_calls_today", "rest_day", "container_id", "created_at")
    d = {k: a.get(k) for k in keep}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


@router.get("/accounts")
async def accounts(_: dict = Depends(admin)):
    return [_acc_public(a) for a in await db.list_accounts()]


@router.post("/accounts")
async def create_account(body: AccountIn, _: dict = Depends(admin)):
    a = await db.create_account(body.locality_id, body.client_id)
    return _acc_public(a)


@router.delete("/accounts/{aid}")
async def delete_account(aid: int, _: dict = Depends(admin)):
    await db.delete_account(aid)
    return {"ok": True}


@router.post("/accounts/{aid}/connect")
async def connect(aid: int, _: dict = Depends(admin)):
    try:
        return await service.start_device_flow(aid)
    except service.CarDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/accounts/{aid}/poll")
async def poll(aid: int, _: dict = Depends(admin)):
    return await service.poll_device_flow(aid)


@router.post("/accounts/{aid}/sync")
async def sync(aid: int, _: dict = Depends(admin)):
    try:
        return await service.sync_vehicles(aid)
    except service.CarDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/vehicles")
async def vehicles(locality_id: int | None = None, _: dict = Depends(read)):
    out = []
    for v in await db.list_vehicles(locality_id):
        st = await db.state(v["vin"])
        cv = service.car_view(v, st)
        cv["km_today"] = None
        if isinstance(cv.get("odometer_km"), (int, float)):
            base = await db.odometer_at_day_start(v["vin"], cv["key_map_odometer"])
            cv["km_today"] = round(max(0.0, float(cv["odometer_km"]) - base), 1) if base is not None else None
        out.append({**cv, "enabled": v.get("enabled", True), "key_map": {**db.DEFAULT_KEY_MAP, **(v.get("key_map") or {})}})
    return out


@router.patch("/vehicles/{vin}")
async def patch_vehicle(vin: str, body: VehiclePatch, _: dict = Depends(admin)):
    await db.update_vehicle(vin, body.model_dump(exclude_unset=True))
    return {"ok": True}


@router.get("/vehicles/{vin}/state")
async def vehicle_state(vin: str, _: dict = Depends(read)):
    """Všechny přijaté deskriptory (pro mapování rolí a diagnostiku)."""
    return await db.state(vin)


@router.get("/vehicles/{vin}/history")
async def vehicle_history(vin: str, key: str, hours: int = 48, _: dict = Depends(read)):
    return await db.history(vin, key, max(1, min(hours, 24 * 31)))


@router.get("/roles")
async def roles(_: dict = Depends(read)):
    return {"roles": db.ROLES, "role_labels": db.ROLE_LABELS, "default_key_map": db.DEFAULT_KEY_MAP,
            "stream_keys": [{"key": k, "why": w} for k, w in db.STREAM_KEYS]}
