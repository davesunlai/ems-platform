"""Endpointy povelové roviny. Vyžadují oprávnění 'control'."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.modules import db as modules_db
from . import db
from .goodwe_control import read_battery_mode, set_battery_mode
from .models import BatteryModeCommand, CommandResult

logger = logging.getLogger("ems.control")
router = APIRouter(prefix="/api/control", tags=["control"])


@router.get("/modules")
async def controllable_modules(_: dict = Depends(require_permission("control"))):
    mods = await modules_db.list_all()
    return [{"id": m.id, "name": m.name} for m in mods if m.adapter == "goodwe" and m.enabled]


async def _get_controllable(module_id: str):
    mods = await modules_db.list_all()
    m = next((x for x in mods if x.id == module_id), None)
    if not m:
        raise HTTPException(status_code=404, detail="Modul nenalezen")
    if m.adapter != "goodwe":
        raise HTTPException(status_code=400, detail="Řízení podporuje zatím jen adaptér goodwe")
    host = m.params.get("host")
    if not host:
        raise HTTPException(status_code=400, detail="Modul nemá nastavenou IP (host)")
    return m, host, int(m.params.get("port", 8899))


@router.get("/{module_id}/mode")
async def get_mode(module_id: str, _: dict = Depends(require_permission("control"))):
    _, host, port = await _get_controllable(module_id)
    try:
        mode = await read_battery_mode(host, port)
        return {"module_id": module_id, "mode": mode}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Čtení režimu selhalo: {exc}")


@router.post("/{module_id}/battery-mode", response_model=CommandResult)
async def set_mode(module_id: str, body: BatteryModeCommand,
                   user: dict = Depends(require_permission("control"))):
    _, host, port = await _get_controllable(module_id)
    params = body.model_dump()
    try:
        res = await set_battery_mode(host, port, body.mode.value, body.power_pct, body.target_soc)
        ok = True
        msg = f"Nastaveno {res['requested']}, ověřeno: {res.get('confirmed')}"
        result = CommandResult(ok=ok, module_id=module_id, requested=res["requested"],
                               confirmed_mode=res.get("confirmed"), message=msg)
    except Exception as exc:
        ok = False
        result = CommandResult(ok=False, module_id=module_id, requested=body.mode.value,
                               message=f"Povel selhal: {exc}")
    # audit vždy (úspěch i selhání)
    await db.record(user["username"], module_id, "battery-mode", params, ok, result.model_dump())
    if not ok:
        raise HTTPException(status_code=502, detail=result.message)
    return result


@router.get("/audit")
async def audit(_: dict = Depends(require_permission("control"))):
    return await db.list_recent()
