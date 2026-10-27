"""API predikce: čtení cache, ruční přepočet, správa PV bloků, geokódování."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ems.auth.deps import require_permission
from ems.localities import db as loc_db
from ems.pricing import db as pricing_db
from ems.pricing import cost as pricing_cost
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


class DarkFloorIn(BaseModel):
    dark_enabled: bool | None = None
    dark_slope: float | None = None
    dark_offset_kwh: float | None = None     # None = auto (0,32 kWh/kWp)


async def _dark_view(locality_id: int) -> dict:
    from .model import DARK_OFFSET_PER_KWP, DARK_SLOPE_DEFAULT
    cfg = await fdb.get_dark_cfg(locality_id)
    loc = await loc_db.get(locality_id) or {}
    kwp = float(loc.get("pv_kwp_total") or 0)
    eff = cfg["dark_offset_kwh"] if cfg["dark_offset_kwh"] is not None else DARK_OFFSET_PER_KWP * kwp
    cfg["effective_offset_kwh"] = round(float(eff), 1)
    cfg["auto_offset_per_kwp"] = DARK_OFFSET_PER_KWP
    cfg["default_slope"] = DARK_SLOPE_DEFAULT
    cfg["days"] = await fdb.latest_om_days(locality_id)
    return cfg


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
    spot = await fdb.spot_window_hourly(48)
    tariff = await pricing_db.get_effective(locality_id)
    from datetime import datetime
    price = []
    for s in spot:
        ts = datetime.fromisoformat(s["ts"])
        c = pricing_cost.price_czk_kwh(tariff, ts, s["czk_mwh"])
        price.append({"ts": s["ts"], "import_czk": round(c["import_czk"], 3), "export_czk": round(c["export_czk"], 3)})
    return {
        "locality_id": locality_id,
        "lat": loc.get("lat"), "lon": loc.get("lon"),
        "pv_kwp_total": loc.get("pv_kwp_total"),
        "pricing_mode": (tariff or {}).get("mode") or loc.get("pricing_mode") or "spot",
        "pv": pv,                                  # {source: [{ts, pv_w, pv_w_lo, pv_w_hi}]}
        "load": await fdb.latest_load(locality_id),  # [{ts, load_w}]
        "spot": spot,                                # [{ts, czk_mwh}]
        "price": price,                              # [{ts, import_czk, export_czk}] reálná cena
    }


@router.post("/{locality_id}/refresh")
async def refresh(locality_id: int, _: dict = Depends(admin)):
    res = await service.refresh_locality(locality_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "přepočet selhal"))
    return res


@router.get("/{locality_id}/dark-floor")
async def get_dark_floor(locality_id: int, _: dict = Depends(read)):
    return await _dark_view(locality_id)


@router.put("/{locality_id}/dark-floor")
async def put_dark_floor(locality_id: int, body: DarkFloorIn, _: dict = Depends(admin)):
    patch = body.model_dump(exclude_unset=True)
    if "dark_slope" in patch and patch["dark_slope"] is not None and not (0 <= patch["dark_slope"] <= 1):
        raise HTTPException(status_code=400, detail="sklon musí být 0–1")
    await fdb.put_dark_cfg(locality_id, patch)
    return await _dark_view(locality_id)


@router.get("/{locality_id}/blocks")
async def get_blocks(locality_id: int, _: dict = Depends(admin)):
    return {"blocks": await fdb.list_blocks(locality_id)}


@router.put("/{locality_id}/blocks")
async def put_blocks(locality_id: int, body: PvBlocks, _: dict = Depends(admin)):
    await fdb.replace_blocks(locality_id, [b.model_dump() for b in body.blocks])
    return {"blocks": await fdb.list_blocks(locality_id)}
