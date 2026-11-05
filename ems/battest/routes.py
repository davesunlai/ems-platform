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
            return await _with_live(await db.get(t["id"]))
    return None


@router.get("/{locality_id}/list")
async def list_tests(locality_id: int, limit: int = 50, _: dict = Depends(read)):
    return await db.list_tests(locality_id, limit)


async def _with_live(t: dict) -> dict:
    """Doplní živý stav (SoC, výkon, energie v aktuální fázi) a sérii po minutě pro graf."""
    from datetime import datetime, timezone
    t0 = datetime.fromisoformat(t["started_at"]); t1 = datetime.fromisoformat(t["ended_at"]) if t.get("ended_at") else datetime.now(timezone.utc)
    # začátek každé fáze z protokolu → t_from prvního snímku fáze
    marks = {m["phase"]: datetime.fromisoformat(m["ts"]) for m in await db.phase_marks(t["id"])}
    t["series"] = await db.series(t["module_id"], t0, t1)
    t["phase_marks"] = await db.phase_marks(t["id"])
    # energie po packách mezi snímky (pack 1 / pack 2) — dopočet při čtení z battery_power_1/2
    prev = {}
    for s in t.get("snapshots") or []:
        ph = s["phase"]; ts = datetime.fromisoformat(s["ts"])
        start = prev.get(ph) or marks.get(ph) or (datetime.fromisoformat(t["phase_started_at"]) if ph == t["status"] and t.get("phase_started_at") else None)
        s["t_from"] = start.isoformat() if start else None
        if start and (ts - start).total_seconds() > 30:
            c1, d1 = await db.energy_kwh(t["module_id"], start, ts, "battery_power_1")
            c2, d2 = await db.energy_kwh(t["module_id"], start, ts, "battery_power_2")
            up = ph in ("charge", "hold")
            s["e1_kwh"] = round(c1 if up else d1, 3); s["e2_kwh"] = round(c2 if up else d2, 3)
        prev[ph] = ts
        if s.get("cell_vmin_1") is None:      # starší snímky: dopočet z telemetrie k času snímku
            cm = await db.metrics_at(t["module_id"], ["battery_cell_vmin_1", "battery_cell_vmax_1", "battery_cell_vmin_2", "battery_cell_vmax_2"], ts)
            s["cell_vmin_1"], s["cell_vmax_1"] = cm.get("battery_cell_vmin_1"), cm.get("battery_cell_vmax_1")
            s["cell_vmin_2"], s["cell_vmax_2"] = cm.get("battery_cell_vmin_2"), cm.get("battery_cell_vmax_2")
    if t["status"] in db.RUNNING and t.get("phase_started_at"):
        m = await db.latest_metrics(t["module_id"], ["battery_soc", "battery_power", "battery_power_1", "battery_power_2", "grid_power"], 300)
        ps = datetime.fromisoformat(t["phase_started_at"])
        chg, dis = await db.energy_kwh(t["module_id"], ps, t1)
        t["live"] = {"soc": m.get("battery_soc"), "bat_w": m.get("battery_power"), "bat1_w": m.get("battery_power_1"), "bat2_w": m.get("battery_power_2"), "grid_w": m.get("grid_power"),
                     "e_phase_chg_kwh": round(chg, 2), "e_phase_dis_kwh": round(dis, 2),
                     "phase_elapsed_min": round((t1 - ps).total_seconds() / 60)}
    return t


@router.get("/test/{test_id}")
async def get_test(test_id: int, _: dict = Depends(read)):
    t = await db.get(test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test nenalezen")
    return await _with_live(t)
