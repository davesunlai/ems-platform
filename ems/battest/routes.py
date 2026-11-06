"""API testu baterie. Právo: `control` + prvek UI `ctl:battery_test` nesmí být pro roli skrytý (správa rolí)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import get_current_user, require_permission
from ems.auth import roles as _roles
from . import db, engine, blocks as blocks_mod

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
    mods = await _solis_modules(locality_id)
    blocks = {}
    for m in mods:
        bl = await blocks_mod.list_blocks(m)
        if bl:
            blocks[m] = bl
            cap_b = sum(float(b["capacity_kwh"]) for b in bl)
            if cap_b > 0:
                cap = cap_b
    return {"modules": mods, "params": engine.default_params(cap), "blocks": blocks}


# ---------- bateriové bloky ----------
class BlockIn(BaseModel):
    name: str | None = None
    capacity_kwh: float | None = None
    modules_count: int | None = None
    module_model: str | None = None
    module_kwh: float | None = None
    cells_per_module: int | None = None
    installed: str | None = None
    note: str | None = None


@router.get("/blocks/{module_id}")
async def get_blocks(module_id: str, _: dict = Depends(read)):
    return await blocks_mod.list_blocks(module_id)


@router.put("/blocks/{module_id}")
async def put_blocks(module_id: str, body: list[BlockIn], user: dict = Depends(get_current_user)):
    if "admin" not in user["permissions"] and "control" not in user["permissions"]:
        raise HTTPException(status_code=403, detail="Chybí právo měnit nastavení bloků.")
    for b in body:
        if (b.capacity_kwh or 0) <= 0 and not (b.modules_count and b.module_kwh):
            raise HTTPException(status_code=400, detail="U každého bloku zadej kapacitu kWh, nebo počet modulů × kWh modulu.")
    return await blocks_mod.save_blocks(module_id, [b.model_dump() for b in body])


# ---------- vyhodnocení a export ----------
async def _report_ctx(test_id: int, user: dict | None = None, with_chart: bool = True) -> dict:
    from ems import __version__
    from ems.localities import db as loc_db
    from . import assess as assess_mod, report
    t = await db.get(test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test nenalezen")
    t = await _with_live(t)
    a = (t.get("result") or {}).get("assess")
    if not a or not a.get("blocks"):
        a = await assess_mod.assess(t, t.get("result"))
    loc = await loc_db.get(int(t["locality_id"])) if t.get("locality_id") else None
    from ems.api.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        mrow = await conn.fetchrow("SELECT id, name, adapter, device_type FROM modules WHERE id=$1", t["module_id"])
    mod = dict(mrow) if mrow else {"id": t["module_id"]}
    from datetime import datetime, timezone
    t0 = datetime.fromisoformat(t["started_at"]); t1 = datetime.fromisoformat(t["ended_at"]) if t.get("ended_at") else datetime.now(timezone.utc)
    packs = [int(b["idx"]) for b in (t["params"].get("blocks") or [])] or [1, 2]
    cell_rows = await assess_mod.series_cells(t["module_id"], t0, t1, packs)
    ctx = {"test": t, "assess": a, "locality": loc, "module": mod, "version": __version__, "user": (user or {}).get("username"),
           "log": t.get("log") or [], "cell_rows": cell_rows}
    if with_chart:
        try:
            ctx["chart"] = report.chart_png(t, cell_rows)
        except Exception as exc:   # graf není důvod report nevydat
            import logging; logging.getLogger("ems.battest").warning("report chart: %s", exc)
    return ctx


@router.get("/test/{test_id}/assess")
async def get_assess(test_id: int, recompute: bool = False, _: dict = Depends(read)):
    from . import assess as assess_mod
    t = await db.get(test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test nenalezen")
    a = (t.get("result") or {}).get("assess")
    if recompute or not a or not a.get("blocks"):
        t = await _with_live(t)
        a = await assess_mod.assess(t, t.get("result"))
        if t["status"] in ("done", "aborted"):
            res = dict(t.get("result") or {}); res["assess"] = a
            res["blocks"] = [{k: b.get(k) for k in ("idx", "name", "nominal_kwh", "e_chg_kwh", "e_hold_kwh", "e_dis_kwh", "capacity_est_kwh", "soh_pct", "efficiency_pct", "level")}
                             for b in a["blocks"]]
            await db.update(test_id, result=res)
    return a


def _fname(t: dict, ext: str) -> str:
    from datetime import datetime
    d = datetime.fromisoformat(t["started_at"]).strftime("%Y-%m-%d")
    return f"test-baterie-{t['id']}-{d}.{ext}"


@router.get("/test/{test_id}/report.docx")
async def report_docx(test_id: int, user: dict = Depends(read)):
    from fastapi.responses import Response
    from . import report
    ctx = await _report_ctx(test_id, user)
    data = report.build_docx(ctx)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(ctx["test"], "docx")}"'})


@router.get("/test/{test_id}/report.xlsx")
async def report_xlsx(test_id: int, user: dict = Depends(read)):
    from fastapi.responses import Response
    from . import report
    ctx = await _report_ctx(test_id, user, with_chart=False)
    data = report.build_xlsx(ctx)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(ctx["test"], "xlsx")}"'})


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
    # rekapitulace kroků: příjem/výdej celkem a po packách, SoC od → do, délka
    pm = t["phase_marks"]; ser = t["series"]
    def soc_at(ts):
        best = None
        for p in ser:
            if p.get("soc") is None:
                continue
            d = abs((datetime.fromisoformat(p["ts"]) - ts).total_seconds())
            if best is None or d < best[0]:
                best = (d, p["soc"])
        return round(best[1]) if best and best[0] <= 180 else None
    steps = []
    for i, mk in enumerate(pm):
        a = datetime.fromisoformat(mk["ts"]); b = datetime.fromisoformat(pm[i + 1]["ts"]) if i + 1 < len(pm) else t1
        running = i + 1 == len(pm) and not t.get("ended_at")
        chg, dis = await db.energy_kwh(t["module_id"], a, b)
        c1, d1 = await db.energy_kwh(t["module_id"], a, b, "battery_power_1")
        c2, d2 = await db.energy_kwh(t["module_id"], a, b, "battery_power_2")
        steps.append({"phase": mk["phase"], "t_from": a.isoformat(), "t_to": b.isoformat(), "running": running,
                      "minutes": round((b - a).total_seconds() / 60), "soc_from": soc_at(a), "soc_to": soc_at(b),
                      "e_chg_kwh": round(chg, 2), "e_dis_kwh": round(dis, 2), "e1_chg_kwh": round(c1, 2), "e1_dis_kwh": round(d1, 2),
                      "e2_chg_kwh": round(c2, 2), "e2_dis_kwh": round(d2, 2)})
    t["steps"] = steps
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
        if s.get("cell_vmin_1") is None or s.get("cell_nmin_1") is None:      # starší snímky: dopočet z telemetrie k času snímku
            cm = await db.metrics_at(t["module_id"], ["battery_cell_vmin_1", "battery_cell_vmax_1", "battery_cell_vmin_2", "battery_cell_vmax_2",
                                                      "battery_cell_nmin_1", "battery_cell_nmax_1", "battery_cell_nmin_2", "battery_cell_nmax_2",
                                                      "battery_bms_cells_per_module_1", "battery_bms_cells_per_module_2"], ts, 900)
            for p in (1, 2):
                for k in ("vmin", "vmax", "nmin", "nmax"):
                    if s.get(f"cell_{k}_{p}") is None:
                        s[f"cell_{k}_{p}"] = cm.get(f"battery_cell_{k}_{p}")
                if s.get(f"cpm_{p}") is None:
                    s[f"cpm_{p}"] = cm.get(f"battery_bms_cells_per_module_{p}")
    if t["status"] in db.RUNNING and t.get("phase_started_at"):
        m = await db.latest_metrics(t["module_id"], ["battery_soc", "battery_power", "battery_power_1", "battery_power_2", "grid_power"], 300)
        ps = datetime.fromisoformat(t["phase_started_at"])
        chg, dis = await db.energy_kwh(t["module_id"], ps, t1)
        c1, d1 = await db.energy_kwh(t["module_id"], ps, t1, "battery_power_1")
        c2, d2 = await db.energy_kwh(t["module_id"], ps, t1, "battery_power_2")
        t["live"] = {"e1_chg_kwh": round(c1, 2), "e1_dis_kwh": round(d1, 2), "e2_chg_kwh": round(c2, 2), "e2_dis_kwh": round(d2, 2),"soc": m.get("battery_soc"), "bat_w": m.get("battery_power"), "bat1_w": m.get("battery_power_1"), "bat2_w": m.get("battery_power_2"), "grid_w": m.get("grid_power"),
                     "e_phase_chg_kwh": round(chg, 2), "e_phase_dis_kwh": round(dis, 2),
                     "phase_elapsed_min": round((t1 - ps).total_seconds() / 60)}
    return t


@router.get("/test/{test_id}")
async def get_test(test_id: int, _: dict = Depends(read)):
    t = await db.get(test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test nenalezen")
    return await _with_live(t)
