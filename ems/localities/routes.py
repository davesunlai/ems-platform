"""Endpointy lokalit a párování (admin)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from . import db
from ems.outages.service import query_kind
from .models import AssignDevice, AssignUser, BillingSettings, LocalityCreate, LocalityUpdate

router = APIRouter(prefix="/api/admin/localities", tags=["localities"])


async def _enrich(loc: dict) -> dict:
    loc = dict(loc)
    loc.pop("created_at", None)
    loc["users"] = await db.users_for_locality(loc["id"])
    loc["devices"] = await db.devices_for_locality(loc["id"])
    loc["outage_by"] = query_kind(loc)
    return loc


@router.get("")
async def list_localities(_: dict = Depends(require_permission("admin"))):
    return [await _enrich(l) for l in await db.list_all()]


@router.post("", status_code=201)
async def create_locality(body: LocalityCreate, _: dict = Depends(require_permission("admin"))):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Název lokality nesmí být prázdný")
    return await _enrich(await db.create(body.name, body.address, body.region, body.note))


@router.patch("/{loc_id}")
async def update_locality(loc_id: int, body: LocalityUpdate, _: dict = Depends(require_permission("admin"))):
    updated = await db.update(loc_id, body.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    return await _enrich(updated)


@router.delete("/{loc_id}", status_code=204)
async def delete_locality(loc_id: int, _: dict = Depends(require_permission("admin"))):
    if not await db.delete(loc_id):
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")


@router.post("/{loc_id}/users")
async def add_user(loc_id: int, body: AssignUser, _: dict = Depends(require_permission("admin"))):
    if not await db.get(loc_id):
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    await db.assign_user(loc_id, body.user_id)
    return await _enrich(await db.get(loc_id))


@router.delete("/{loc_id}/users/{user_id}")
async def remove_user(loc_id: int, user_id: int, _: dict = Depends(require_permission("admin"))):
    await db.unassign_user(loc_id, user_id)
    return await _enrich(await db.get(loc_id))


@router.put("/{loc_id}/users/{user_id}/notify")
async def set_user_notify(loc_id: int, user_id: int, body: dict, _: dict = Depends(require_permission("admin"))):
    await db.set_user_notify(loc_id, user_id, bool(body.get("notify")))
    return await _enrich(await db.get(loc_id))


@router.post("/{loc_id}/devices")
async def add_device(loc_id: int, body: AssignDevice, _: dict = Depends(require_permission("admin"))):
    if not await db.get(loc_id):
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    await db.assign_device(loc_id, body.module_id)
    return await _enrich(await db.get(loc_id))


@router.delete("/{loc_id}/devices/{module_id}")
async def remove_device(loc_id: int, module_id: str, _: dict = Depends(require_permission("admin"))):
    await db.unassign_device(module_id)
    return await _enrich(await db.get(loc_id))


@router.put("/{loc_id}/billing")
async def set_billing(loc_id: int, body: BillingSettings,
                      _: dict = Depends(require_permission("admin"))):
    patch = body.model_dump(exclude_unset=True)
    if "baseline_export_kwh" in patch or "baseline_import_kwh" in patch:
        from datetime import date
        from ems.billing.period import current_period
        cur = await db.get(loc_id)
        bstart = patch.get("billing_start") or (cur and cur.get("billing_start"))
        months = patch.get("billing_months") or (cur and cur.get("billing_months")) or 12
        if bstart:
            start, _e = current_period(bstart, months, date.today())
            patch["baseline_period_start"] = start
    loc = await db.set_billing(loc_id, patch)
    if not loc:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    return await _enrich(loc)
