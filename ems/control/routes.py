"""Endpointy povelové roviny. Vyžadují oprávnění 'control'."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.api.db import get_pool, list_devices
from ems.modules import db as modules_db
from . import db
from .goodwe_control import read_battery_mode, set_battery_mode
from .models import BatteryModeCommand, CommandRequest, CommandResult, SOLIS_ACTIONS

logger = logging.getLogger("ems.control")
router = APIRouter(prefix="/api/control", tags=["control"])


async def _has_battery(device_id: str, days: int = 7) -> bool:
    """Řiditelná baterie = měnič v posledních dnech hlásil battery_soc (hybrid ano, grid-tie ne)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT 1 FROM samples WHERE device_id=$1 AND metric='battery_soc' "
            "AND time > now() - ($2 || ' days')::interval LIMIT 1",
            device_id, str(days))
    return v is not None


@router.get("/modules")
async def controllable_modules(_: dict = Depends(require_permission("control"))):
    """Řiditelné moduly s lokalitou — Solis (control_enabled) i goodwe (s baterií)."""
    devs = await list_devices()
    out = []
    for d in devs:
        adapter = d.get("adapter")
        ce = d.get("control_enabled") or []
        if adapter == "solis" and ce:
            out.append({"id": d["device_id"], "name": d["device_id"], "adapter": "solis",
                        "locality_id": d.get("locality_id"), "locality": d.get("locality"),
                        "control_enabled": ce})
        elif adapter == "goodwe" and await _has_battery(d["device_id"]):
            out.append({"id": d["device_id"], "name": d["device_id"], "adapter": "goodwe",
                        "locality_id": d.get("locality_id"), "locality": d.get("locality"),
                        "control_enabled": ["force_charge", "force_discharge", "stop"]})
    return out


async def _get_controllable(module_id: str):
    mods = await modules_db.list_all()
    m = next((x for x in mods if x.id == module_id), None)
    if not m:
        raise HTTPException(status_code=404, detail="Modul nenalezen")
    if m.adapter != "goodwe":
        raise HTTPException(status_code=400, detail="Řízení podporuje zatím jen adaptér goodwe")
    if not await _has_battery(module_id):
        raise HTTPException(status_code=400, detail="Tento měnič nemá řiditelnou baterii (grid-tie).")
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
async def audit(limit: int = 50, offset: int = 0, q: str = "", _: dict = Depends(require_permission("control"))):
    return await db.list_recent(limit=limit, offset=offset, q=q)


@router.get("/states")
async def states(ids: str = "", _: dict = Depends(require_permission("read"))):
    """Aktuální vynucený stav modulů (pro zvýraznění na dashboardu)."""
    module_ids = [x for x in ids.split(",") if x]
    return {"states": await db.get_states(module_ids)}


# --- Solis (a další adaptéry s jediným spojením): povely jdou FRONTOU,
#     kterou vyřizuje kolektor (drží jediné Modbus spojení na měnič). ---
async def _get_solis(module_id: str):
    mods = await modules_db.list_all()
    m = next((x for x in mods if x.id == module_id), None)
    if not m:
        raise HTTPException(status_code=404, detail="Modul nenalezen")
    if m.adapter != "solis":
        raise HTTPException(status_code=400, detail="Fronta povelů je zatím pro adaptér solis")
    if not m.enabled:
        raise HTTPException(status_code=400, detail="Modul není aktivní (čtecí)")
    return m


def _validate_command(action: str, params: dict) -> None:
    if action not in SOLIS_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Neznámý povel '{action}'")
    if action in ("force_charge", "force_discharge"):
        p = params.get("power")
        if p is not None and (not isinstance(p, int) or not (0 <= p <= 65535)):
            raise HTTPException(status_code=400, detail="power musí být celé číslo 0–65535 (syrová hodnota registru)")
    if action == "set_work_mode" and not isinstance(params.get("word"), int):
        raise HTTPException(status_code=400, detail="set_work_mode vyžaduje celé číslo 'word'")
    if action in ("set_charge_current", "set_discharge_current"):
        a = params.get("amps")
        if not isinstance(a, (int, float)) or not (0 <= a <= 200):
            raise HTTPException(status_code=400, detail="amps musí být 0–200 A")
    if action in ("set_soc_backup", "set_soc_force"):
        pct = params.get("pct")
        if not isinstance(pct, (int, float)) or not (0 <= pct <= 100):
            raise HTTPException(status_code=400, detail="pct musí být 0–100 %")
    if action == "write_holding":
        if not isinstance(params.get("addr"), int) or not isinstance(params.get("value"), int):
            raise HTTPException(status_code=400, detail="write_holding vyžaduje celé 'addr' a 'value'")


@router.post("/{module_id}/command")
async def enqueue_command(module_id: str, body: CommandRequest,
                          user: dict = Depends(require_permission("control"))):
    """Zařadí povel do fronty; kolektor ho provede do ~jednoho cyklu (~10 s).
    Stav lze pollovat na /api/control/command/{id}."""
    await _get_solis(module_id)
    _validate_command(body.action, body.params)
    await db.ensure_queue_schema()
    cmd_id = await db.enqueue(module_id, body.action, body.params, user["username"])
    await db.record(user["username"], module_id, body.action, body.params, True, {"queued": cmd_id})
    return {"id": cmd_id, "status": "pending"}


@router.get("/command/{cmd_id}")
async def command_status(cmd_id: int, _: dict = Depends(require_permission("control"))):
    c = await db.get_command(cmd_id)
    if not c:
        raise HTTPException(status_code=404, detail="Povel nenalezen")
    return c
