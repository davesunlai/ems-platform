"""Endpointy spínacích výstupů."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db
from . import engine

router = APIRouter(prefix="/api/outputs", tags=["outputs"])


class OutputBody(BaseModel):
    name: str
    enabled: bool = False
    locality_id: int | None = None
    output_kind: str          # goodwe_contact | ewelink
    target: str
    trigger: str              # soc | surplus
    params: dict = {}


class PatchBody(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    locality_id: int | None = None
    output_kind: str | None = None
    target: str | None = None
    trigger: str | None = None
    params: dict | None = None


class TestBody(BaseModel):
    on: bool


@router.get("")
async def list_outputs(_: dict = Depends(require_permission("read"))):
    return await db.list_all()


@router.post("")
async def create_output(body: OutputBody, _: dict = Depends(require_permission("control"))):
    return await db.create(body.model_dump())


@router.put("/{out_id}")
async def update_output(out_id: int, body: PatchBody, _: dict = Depends(require_permission("control"))):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    r = await db.update(out_id, patch)
    if not r:
        raise HTTPException(status_code=404, detail="Výstup nenalezen")
    return r


@router.delete("/{out_id}")
async def delete_output(out_id: int, _: dict = Depends(require_permission("control"))):
    await db.delete(out_id)
    return {"ok": True}


@router.post("/{out_id}/unlock")
async def unlock_output(out_id: int, _: dict = Depends(require_permission("control"))):
    await db.set_lock(out_id, None)
    return {"ok": True}


@router.post("/{out_id}/test")
async def test_output(out_id: int, body: TestBody, _: dict = Depends(require_permission("control"))):
    o = await db.get(out_id)
    if not o:
        raise HTTPException(status_code=404, detail="Výstup nenalezen")
    try:
        res = await engine._actuate(o, body.on)
        await db.set_state(out_id, body.on, f"ruční test → {'sepnuto' if body.on else 'rozepnuto'}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True, "result": res}


# --- Sync skutečného stavu z eWeLinku (i když bylo sepnuto mimo TERA EMS) ----
# Serverový throttle: víc otevřených schémat sdílí jeden dotaz (min. 100 s mezi voláními).
_SYNC_MIN_S = 100
_sync_cache: dict = {"at": 0.0, "result": None}


@router.post("/sync-ewelink")
async def sync_ewelink(_: dict = Depends(require_permission("read"))) -> dict:
    import time
    from ems.ewelink import client as ew
    now = time.monotonic()
    if _sync_cache["result"] is not None and now - _sync_cache["at"] < _SYNC_MIN_S:
        return {**_sync_cache["result"], "cached": True}
    if not ew.configured():
        return {"ok": False, "reason": "eWeLink není nakonfigurován", "devices": {}, "updated": []}
    try:
        devs = await ew.list_devices()
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "devices": {}, "updated": []}
    by_id = {d["deviceid"]: d for d in devs if d.get("deviceid")}
    updated = []
    for o in await db.list_all():
        if o.get("output_kind") != "ewelink":
            continue
        d = by_id.get(o.get("target"))
        if not d or d.get("switch") not in ("on", "off"):
            continue
        real_on = d["switch"] == "on"
        if bool(o.get("is_on")) != real_on:
            await db.set_state(o["id"], real_on, "sync: stav z eWeLinku (sepnuto mimo TERA EMS)")
            updated.append({"id": o["id"], "name": o["name"], "is_on": real_on})
    result = {"ok": True, "updated": updated,
              "devices": {did: {"on": d.get("switch") == "on", "online": d.get("online"),
                                "power_w": d.get("power")} for did, d in by_id.items()}}
    _sync_cache.update(at=now, result=result)
    return {**result, "cached": False}
