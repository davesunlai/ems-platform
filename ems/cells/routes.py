"""API: konfigurace hlídání článků per lokalita + ruční kontrola."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db, service

router = APIRouter(prefix="/api/localities", tags=["cells"])
admin = require_permission("admin")
read = require_permission("read")


class CellAlertIn(BaseModel):
    enabled: bool | None = None
    soc_low: float | None = None
    delta_low_mv: float | None = None
    soc_high: float | None = None
    delta_high_mv: float | None = None
    check_hour: int | None = None
    y_min: float | None = None
    y_max: float | None = None


@router.get("/{locality_id}/cell-alert")
async def get_cfg(locality_id: int, _: dict = Depends(read)):
    return await db.get_config(locality_id)


@router.put("/{locality_id}/cell-alert")
async def put_cfg(locality_id: int, body: CellAlertIn, user: dict = Depends(admin)):
    cfg = await db.put_config(locality_id, body.model_dump(exclude_unset=True))
    try:
        from ems.alerts import db as alerts_db
        await alerts_db.record_event(locality_id, "config", "Hlídání článků baterie",
                                     f"{'ZAPNUTO' if cfg['enabled'] else 'VYPNUTO'} · SoC<{cfg['soc_low']:g} % → Δ>{cfg['delta_low_mv']:g} mV; "
                                     f"SoC>{cfg['soc_high']:g} % → Δ>{cfg['delta_high_mv']:g} mV · uživatel {user.get('username', '?')}")
    except Exception:
        pass
    return cfg


@router.post("/{locality_id}/cell-alert/check")
async def run_check(locality_id: int, notify: bool = False, _: dict = Depends(admin)):
    """Spustí kontrolu hned (výchozí bez odeslání upozornění — jen náhled výsledku)."""
    return await service.check_locality(locality_id, notify=notify)
