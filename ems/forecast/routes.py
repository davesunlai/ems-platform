"""API predikce: čtení cache, ruční přepočet, správa PV bloků, geokódování."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ems.auth.deps import require_permission
from ems.localities import db as loc_db
from . import db as fdb
from . import service
from .providers import geocode as geocode_provider

router = APIRouter(prefix="/api/forecast", tags=["forecast"])
read = require_permission("read")
admin = require_permission("admin")


class PvBlock(BaseModel):
    name: str = ""
    share_pct: float = 0
    panel_type: str = "normal"      # normal | bifacial
    tilt: float = 30
    azimuth: float = 0              # 0=J, -90=V, +90=Z, ±180=S
    pr: float = 0.8
    enabled: bool = True


class PvBlocks(BaseModel):
    blocks: list[PvBlock] = Field(default_factory=list)


@router.get("/geocode")
async def geocode(q: str, _: dict = Depends(admin)):
    if not q or len(q) < 2:
        return {"results": []}
    return {"results": await geocode_provider(q)}


@router.get("/{locality_id}")
async def get_forecast(locality_id: int, _: dict = Depends(read)):
    loc = await loc_db.get(locality_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    pv = await fdb.latest_pv_all_sources(locality_id)
    return {
        "locality_id": locality_id,
        "lat": loc.get("lat"), "lon": loc.get("lon"),
        "pv_kwp_total": loc.get("pv_kwp_total"),
        "pv": pv,                       # {source: [{ts, pv_w}]}, vč. 'avg'
    }


@router.post("/{locality_id}/refresh")
async def refresh(locality_id: int, _: dict = Depends(admin)):
    res = await service.refresh_locality(locality_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "přepočet selhal"))
    return res


@router.get("/{locality_id}/blocks")
async def get_blocks(locality_id: int, _: dict = Depends(admin)):
    return {"blocks": await fdb.list_blocks(locality_id)}


@router.put("/{locality_id}/blocks")
async def put_blocks(locality_id: int, body: PvBlocks, _: dict = Depends(admin)):
    await fdb.replace_blocks(locality_id, [b.model_dump() for b in body.blocks])
    return {"blocks": await fdb.list_blocks(locality_id)}
