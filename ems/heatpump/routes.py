"""API tepelného čerpadla — v0.64.0: state pro kartu na dashboardu."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.localities import db as loc_db
from . import db as hp_db

router = APIRouter(prefix="/api/localities", tags=["heat-pump"])
read = require_permission("read")


async def _hp_modules(locality_id: int) -> list[str]:
    devs = await loc_db.devices_for_locality(locality_id)
    return [d["id"] for d in devs if (d.get("device_type") or d.get("type")) == "heat_pump"]


@router.get("/{locality_id}/heat-pump/state")
async def hp_state(locality_id: int, _: dict = Depends(read)) -> dict:
    mods = await _hp_modules(locality_id)
    if not mods:
        raise HTTPException(status_code=404, detail="lokalita nemá modul heat_pump")
    row = await hp_db.latest_for_modules(mods)
    if not row:
        return {"module_ids": mods, "state": None}
    row["ts"] = row["ts"].isoformat()
    return {"module_ids": mods, "state": row}
