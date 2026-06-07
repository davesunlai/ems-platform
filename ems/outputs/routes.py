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
