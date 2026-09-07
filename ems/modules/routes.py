"""Admin endpointy pro správu modulů."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from . import db
from .models import Module, ModuleCreate, ModuleUpdate

router = APIRouter(prefix="/api/admin", tags=["modules"])

ADAPTERS = ["goodwe", "solis", "uvr_cmi", "mock"]  # dostupné adaptéry pro UI


@router.get("/adapters")
async def adapters(_: dict = Depends(require_permission("admin"))) -> list[str]:
    return ADAPTERS


@router.get("/modules")
async def list_modules(_: dict = Depends(require_permission("admin"))):
    return await db.list_all_with_status()


@router.post("/modules", response_model=Module, status_code=201)
async def create_module(body: ModuleCreate, _: dict = Depends(require_permission("admin"))):
    if not body.id or not body.id.strip():
        raise HTTPException(status_code=400, detail="ID modulu nesmí být prázdné")
    existing = await db.list_all()
    if any(m.id == body.id for m in existing):
        raise HTTPException(status_code=409, detail="Modul s tímto id už existuje")
    return await db.create(Module(**body.model_dump()))


@router.patch("/modules/{module_id}", response_model=Module)
async def update_module(module_id: str, body: ModuleUpdate, _: dict = Depends(require_permission("admin"))):
    updated = await db.update(module_id, body.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Modul nenalezen nebo nic ke změně")
    return updated


@router.delete("/modules/{module_id}", status_code=204)
async def delete_module(module_id: str, _: dict = Depends(require_permission("admin"))):
    if not await db.delete(module_id):
        raise HTTPException(status_code=404, detail="Modul nenalezen")


async def _ep_rows(query: str, module_id: str, hours: int):
    from ems.api.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, module_id, hours)


@router.get("/modules/{module_id}/diagnostics")
async def module_diagnostics(module_id: str, hours: int = 24,
                             _: dict = Depends(require_permission("read"))):
    """🔬 Diagnostika modulu: dostupnost čtení, díry v datech (komunikace/restart),
    čerstvost metrik, stav na EMSBOXu, timeline povelů. Vše z existujících dat —
    žádné nové čtení ze zařízení (na to je read_controls v Řízení)."""
    from ems.api.db import get_pool
    import json as _json
    hours = max(1, min(int(hours), 168))
    pool = await get_pool()
    async with pool.acquire() as conn:
        mod = await conn.fetchrow(
            "SELECT id, name, adapter, enabled, emsbox_id, locality_id, params FROM modules WHERE id = $1", module_id)
        if not mod:
            raise HTTPException(status_code=404, detail="modul neexistuje")
        # pokrytí: minuty s aspoň jedním vzorkem / minuty okna
        cov = await conn.fetchrow(
            """SELECT count(DISTINCT date_trunc('minute', time)) AS mins, count(*) AS samples,
                      min(time) AS first_t, max(time) AS last_t
               FROM samples WHERE device_id = $1 AND time > now() - make_interval(hours => $2)""",
            module_id, hours)
        # díry > 2 min (výpadek komunikace NEBO restart zařízení/boxu)
        gaps = await conn.fetch(
            """WITH t AS (SELECT DISTINCT time FROM samples
                          WHERE device_id = $1 AND time > now() - make_interval(hours => $2))
               SELECT prev AS od, time AS do_, EXTRACT(EPOCH FROM (time - prev)) AS trvani_s
               FROM (SELECT time, lag(time) OVER (ORDER BY time) AS prev FROM t) x
               WHERE prev IS NOT NULL AND time - prev > interval '2 minutes'
               ORDER BY prev DESC LIMIT 50""", module_id, hours)
        # čerstvost per metrika
        fresh = await conn.fetch(
            """SELECT DISTINCT ON (metric) metric, value, time
               FROM samples WHERE device_id = $1 AND time > now() - interval '7 days'
               ORDER BY metric, time DESC""", module_id)
        # povely modulu (timeline zásahů)
        cmds = await conn.fetch(
            """SELECT id, action, status, username, params, result, created_at, executed_at,
                      EXTRACT(EPOCH FROM (executed_at - created_at)) AS latence_s
               FROM control_queue WHERE module_id = $1
               ORDER BY id DESC LIMIT 30""", module_id)
        # stav řízení
        st = await conn.fetchrow("SELECT action, source, username, since FROM control_state WHERE module_id = $1",
                                 module_id)
        # EMSBOX pohled (per-zařízení ok/error z heartbeatu)
        box = None
        if mod["emsbox_id"]:
            b = await conn.fetchrow(
                "SELECT id, name, status, last_heartbeat, heartbeat_devices FROM emsbox WHERE id = $1",
                mod["emsbox_id"])
            if b:
                devs = b["heartbeat_devices"]
                if isinstance(devs, str):
                    try:
                        devs = _json.loads(devs)
                    except Exception:
                        devs = []
                mine = next((d for d in (devs or []) if d.get("device_uid") == module_id), None)
                box = {"id": b["id"], "name": b["name"], "status": b["status"],
                       "last_heartbeat": b["last_heartbeat"].isoformat() if b["last_heartbeat"] else None,
                       "device": mine}
    total_min = hours * 60
    params = mod["params"]
    if isinstance(params, str):
        try:
            params = _json.loads(params)
        except Exception:
            params = {}
    def iso(v):
        return v.isoformat() if v is not None else None
    return {
        "module": {"id": mod["id"], "name": mod["name"], "adapter": mod["adapter"], "enabled": mod["enabled"],
                   "emsbox_id": mod["emsbox_id"], "locality_id": mod["locality_id"],
                   "control_sources": (params or {}).get("control_sources") or {},
                   "transport": (params or {}).get("serial_port") and "RS485" or None},
        "window_hours": hours,
        "coverage": {"pct": round(100.0 * (cov["mins"] or 0) / total_min, 1),
                     "samples": cov["samples"], "minutes": cov["mins"],
                     "first": iso(cov["first_t"]), "last": iso(cov["last_t"])},
        "gaps": [{"od": iso(g["od"]), "do": iso(g["do_"]), "trvani_s": int(g["trvani_s"])} for g in gaps],
        "metrics": [{"metric": f["metric"], "value": f["value"], "time": iso(f["time"])} for f in fresh],
        "state": ({"action": st["action"], "source": st["source"], "username": st["username"],
                   "since": iso(st["since"])} if st else None),
        "commands": [{"id": c["id"], "action": c["action"], "status": c["status"], "username": c["username"],
                      "created_at": iso(c["created_at"]), "latence_s": (round(c["latence_s"], 1) if c["latence_s"] is not None else None),
                      "reason": ((_json.loads(c["params"]) if isinstance(c["params"], str) else (c["params"] or {})) or {}).get("reason"),
                      "source": ((_json.loads(c["params"]) if isinstance(c["params"], str) else (c["params"] or {})) or {}).get("source"),
                      "result_short": str(c["result"])[:160] if c["result"] else None}
                     for c in cmds],
        "box": box,
        "state_daily": [
            {"day": str(e["d"]), "count": int(e["c"])}
            for e in (await _ep_rows(
                """SELECT date_trunc('day', time AT TIME ZONE 'Europe/Prague')::date AS d, count(*) AS c
                   FROM samples
                   WHERE device_id = $1 AND metric = 'inverter_state' AND value = 4121
                     AND time > now() - make_interval(hours => GREATEST($2, 336))
                   GROUP BY 1 ORDER BY 1 DESC LIMIT 14""", module_id, hours))
        ],
        "state_episodes": [
            {"time": iso(e["t"]), "value": int(e["value"])}
            for e in (await _ep_rows(
                """SELECT time AS t, value FROM samples
                   WHERE device_id = $1 AND metric = 'inverter_state' AND value != 15
                     AND time > now() - make_interval(hours => $2)
                   ORDER BY time DESC LIMIT 60""", module_id, hours))
        ],
    }
