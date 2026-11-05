"""API testu baterie. Právo: `control` + prvek UI `ctl:battery_test` nesmí být pro roli skrytý (správa rolí)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import get_current_user, require_permission
from ems.auth import roles as _roles
from . import db, engine

router = APIRouter(prefix="/api/battery-test", tags=["battery-test"])
read = require_permission("read")
UI_KEY = "ctl:battery_test"


async def tester(user: dict = Depends(get_current_user)) -> dict:
    if "control" not in user["permissions"] or UI_KEY in _roles.hidden_for(user["role"]):
        raise HTTPException(status_code=403, detail="Chybí právo spouštět test baterie (role → 🧪 Test baterie).")
    return user


class Params(BaseModel):
    p_chg_kw: float
    p_dis_kw: float
    hold_min: int = 60
    floor_pct: float = 10
    ceil_pct: float = 100
    capacity_kwh: float


class StartBody(BaseModel):
    module_id: str
    params: Params
    confirmed: bool = False


async def _solis_modules(locality_id: int) -> list[str]:
    from ems.localities import db as loc_db
    from ems.api.db import list_devices
    devs = {d["device_id"]: d for d in await list_devices()}
    return [d["id"] for d in await loc_db.devices_for_locality(locality_id) if (devs.get(d["id"]) or {}).get("adapter") == "solis"]


def _check(p: Params) -> None:
    if not (0.5 <= p.p_chg_kw <= 50 and 0.5 <= p.p_dis_kw <= 50):
        raise HTTPException(status_code=400, detail="Výkony 0,5–50 kW")
    if not (5 <= p.floor_pct < p.ceil_pct <= 100):
        raise HTTPException(status_code=400, detail="Dno 5–95 %, strop ≤ 100 %, dno < strop")
    if not (0 <= p.hold_min <= 24 * 60):
        raise HTTPException(status_code=400, detail="Výdrž 0–1440 min")


@router.get("/{locality_id}/defaults")
async def defaults(locality_id: int, _: dict = Depends(read)):
    from ems.planner import db as planner_db
    cfg = await planner_db.get_config(locality_id) or {}
    cap = float(cfg.get("capacity_kwh") or 52.8)
    return {"modules": await _solis_modules(locality_id), "params": engine.default_params(cap)}


@router.post("/{locality_id}/precheck")
async def precheck(locality_id: int, body: StartBody, _: dict = Depends(tester)):
    _check(body.params)
    return await engine.precheck(locality_id, body.module_id, body.params.model_dump())


@router.post("/{locality_id}/start")
async def start(locality_id: int, body: StartBody, user: dict = Depends(tester)):
    _check(body.params)
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Spuštění vyžaduje potvrzení (confirmed=true).")
    if body.module_id not in await _solis_modules(locality_id):
        raise HTTPException(status_code=404, detail="Modul nepatří lokalitě nebo není Solis.")
    try:
        return await engine.start(locality_id, body.module_id, body.params.model_dump(), user.get("username"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/test/{test_id}/abort")
async def abort(test_id: int, user: dict = Depends(tester)):
    t = await engine.abort(test_id, f"přerušeno uživatelem {user.get('username')}", user.get("username"))
    if not t:
        raise HTTPException(status_code=404, detail="Test nenalezen")
    return t


@router.get("/{locality_id}/current")
async def current(locality_id: int, _: dict = Depends(read)):
    for t in await db.running():
        if t["locality_id"] == locality_id:
            return await db.get(t["id"])
    return None


@router.get("/{locality_id}/list")
async def list_tests(locality_id: int, limit: int = 50, _: dict = Depends(read)):
    return await db.list_tests(locality_id, limit)


@router.get("/test/{test_id}")
async def get_test(test_id: int, _: dict = Depends(read)):
    t = await db.get(test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test nenalezen")
    return t
