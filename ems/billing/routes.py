"""Endpoint pro zúčtovací období lokality (souhrn po měsících + součet)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.localities import db as loc_db
from . import db as billing_db
from .period import current_period

router = APIRouter(tags=["billing"])


@router.get("/api/localities/{loc_id}/billing")
async def locality_billing(loc_id: int, _: dict = Depends(require_permission("read"))):
    loc = await loc_db.get(loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    settings = {
        "billing_start": loc.get("billing_start").isoformat() if loc.get("billing_start") else None,
        "billing_months": loc.get("billing_months") or 12,
        "export_limit_kwh": loc.get("export_limit_kwh"),
        "alert_enabled": bool(loc.get("alert_enabled")),
        "autolimit_enabled": bool(loc.get("autolimit_enabled")),
        "alert_email": loc.get("alert_email"),
    }
    if not loc.get("billing_start"):
        return {"configured": False, "settings": settings}

    start, end = current_period(loc["billing_start"], settings["billing_months"], date.today())
    devs = [d["id"] for d in await loc_db.devices_for_locality(loc_id)]
    months = await billing_db.monthly_energy(devs, start, end)
    totals = {k: round(sum(r[k] for r in months), 1)
              for k in ("prod_kwh", "cons_kwh", "export_kwh", "import_kwh")}
    return {
        "configured": True,
        "settings": settings,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "months": months,
        "totals": totals,
    }
