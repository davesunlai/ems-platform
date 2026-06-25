"""API plánovače: konfigurace (per lokalita) + plán + ruční přepočet."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db as pdb
from . import service

router = APIRouter(prefix="/api/planner", tags=["planner"])
read = require_permission("read")
control = require_permission("control")


class PlannerConfigIn(BaseModel):
    enabled: bool | None = None
    allow_grid_discharge: bool | None = None
    capacity_kwh: float | None = None
    soc_min_pct: float | None = None
    outage_reserve_pct: float | None = None
    max_charge_kw: float | None = None
    max_discharge_kw: float | None = None
    horizon_h: int | None = None


@router.get("/controlled/devices")
async def controlled(_: dict = Depends(read)):
    """device_id moduly, které právě řídí zapnutý plánovač (pro UI precedenci)."""
    by_loc = await service.controlled_devices()
    return {"devices": [d for ds in by_loc.values() for d in ds]}


@router.get("/{locality_id}/amplitudes")
async def amplitudes(locality_id: int, spiral_target_kwh: float | None = None,
                     spiral_power_kw: float = 6.0, spiral_deadline_h: int = 7,
                     breaker_kw: float = 22.0, max_windows: int = 4,
                     threshold_pct: float = 33.0, _: dict = Depends(read)):
    """Spodní/horní amplitudy na efektivní ceně (valley/peak okna) + volitelný plán 6 kW spirály.
    spiral_target_kwh > 0 → vrátí i naplánované běhy spirály (PV přebytek → nejlevnější valley)."""
    return await service.amplitudes(
        locality_id, spiral_target_kwh=spiral_target_kwh, spiral_power_kw=spiral_power_kw,
        spiral_deadline_h=spiral_deadline_h, breaker_kw=breaker_kw,
        max_windows=max_windows, threshold_pct=threshold_pct)


@router.get("/{locality_id}")
async def get_plan(locality_id: int, _: dict = Depends(read)):
    return {
        "config": await pdb.get_config(locality_id),
        "schedule": await pdb.latest_schedule(locality_id),
        "current": await pdb.current_action(locality_id),
    }


@router.put("/{locality_id}/config")
async def put_config(locality_id: int, body: PlannerConfigIn, _: dict = Depends(control)):
    cfg = await pdb.upsert_config(locality_id, body.model_dump(exclude_unset=True))
    # po změně rovnou přepočítej plán
    try:
        await service.run_locality(locality_id)
    except Exception:
        pass
    return {"config": cfg}


@router.post("/{locality_id}/refresh")
async def refresh(locality_id: int, _: dict = Depends(control)):
    res = await service.run_locality(locality_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "přepočet selhal"))
    return res
