"""Ingest API pro EMSBOX: telemetrie (store-and-forward) + heartbeat. Auth box tokenem."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ems.core.model import Metric, UNIT_OF
from . import db
from .auth import box_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingest/v1", tags=["emsbox-ingest"])

_UNITS = {m.value: UNIT_OF.get(m, "") for m in Metric}


class TelemetryRow(BaseModel):
    device_uid: str
    ts: str
    metrics: dict[str, float]


class TelemetryBody(BaseModel):
    box_id: int
    batch_id: str
    box_time: str | None = None
    rows: list[TelemetryRow] = Field(default_factory=list)


@router.post("/telemetry")
async def ingest_telemetry(body: TelemetryBody, box: dict = Depends(box_auth)) -> dict:
    if body.box_id != box["id"]:
        raise HTTPException(status_code=403, detail="box_id nesouhlasí s tokenem")
    if len(body.rows) > db.MAX_BATCH_ROWS:
        raise HTTPException(status_code=413, detail=f"max {db.MAX_BATCH_ROWS} řádků / batch")
    if await db.batch_already_seen(body.batch_id, box["id"]):
        return {"ack": body.batch_id, "accepted": 0, "duplicates": len(body.rows), "note": "batch už přijat"}
    allowed = {m["id"] for m in await db.modules_for_box(box["id"])}
    rows, skipped = [], 0
    for r in body.rows:
        if r.device_uid not in allowed:          # bezpečnost: jen moduly tohoto boxu
            skipped += 1
            continue
        try:
            ts = datetime.fromisoformat(r.ts.replace("Z", "+00:00"))
        except ValueError:
            skipped += 1
            continue
        for metric, val in r.metrics.items():
            rows.append((ts, r.device_uid, metric, val, _UNITS.get(metric, "")))
    accepted = await db.insert_rows(rows)
    await db.touch_ingest(box["id"], accepted)
    dup = len(rows) - accepted
    if skipped:
        logger.warning("EMSBOX %s: %s řádků odmítnuto (cizí device_uid / vadný ts)", box["id"], skipped)
    return {"ack": body.batch_id, "accepted": accepted, "duplicates": dup, "skipped": skipped}


@router.post("/heartbeat")
async def ingest_heartbeat(body: dict, box: dict = Depends(box_auth)) -> dict:
    if body.get("box_id") != box["id"]:
        raise HTTPException(status_code=403, detail="box_id nesouhlasí s tokenem")
    await db.heartbeat(box["id"], body)
    return {"ok": True}


# --- povelový kanál (varianta B): box čte i VYKONÁVÁ povely — jediný klient na střídači
CMD_MAX_AGE_MIN = 15


@router.get("/commands")
async def box_commands(box: dict = Depends(box_auth)) -> dict:
    """Čekající povely pro moduly tohoto boxu. Povely starší CMD_MAX_AGE_MIN
    (box byl offline) server rovnou zneplatní — stará force okna nesmí ožít."""
    from ems.control import db as control_db
    from ems.api.db import get_pool
    from .routes import build_config
    _, cfg_etag = await build_config(box["id"])
    mods = [m["id"] for m in await db.modules_for_box(box["id"])]
    cmds = await control_db.fetch_pending(mods)
    if not cmds:
        return {"commands": [], "config_etag": cfg_etag}
    pool = await get_pool()
    fresh = []
    async with pool.acquire() as conn:
        for c in cmds:
            age_min = await conn.fetchval(
                "SELECT EXTRACT(EPOCH FROM (now() - created_at)) / 60 FROM control_queue WHERE id = $1", c["id"])
            if age_min is not None and age_min > CMD_MAX_AGE_MIN:
                await control_db.complete(c["id"], False,
                                          {"error": f"expiroval ({age_min:.0f} min) — box byl offline"})
            else:
                fresh.append(c)
    return {"commands": fresh, "config_etag": cfg_etag}


class CommandResult(BaseModel):
    id: int
    module_id: str
    action: str
    params: dict = Field(default_factory=dict)
    username: str | None = None
    ok: bool
    result: dict = Field(default_factory=dict)


@router.post("/command-result")
async def box_command_result(body: CommandResult, box: dict = Depends(box_auth)) -> dict:
    from ems.control import db as control_db
    mods = {m["id"] for m in await db.modules_for_box(box["id"])}
    if body.module_id not in mods:
        raise HTTPException(status_code=403, detail="modul nepatří tomuto boxu")
    await control_db.complete(body.id, body.ok, body.result)
    if body.ok and body.action in ("force_charge", "force_discharge", "stop", "spiral"):
        # zrcadlí process_queue: stav + notifikace operace
        try:
            act = "idle" if body.action == "stop" else body.action
            await control_db.set_state(body.module_id, act, body.params,
                                       source=(body.params or {}).get("source", "manual"),
                                       username=body.username)
        except Exception:
            pass
        try:
            from ems.alerts import db as alerts_db
            from ems.notify import dispatch as notify_dispatch
            from ems.api.db import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                loc_id = await conn.fetchval("SELECT locality_id FROM modules WHERE id = $1", body.module_id)
            p = body.params or {}
            pw = p.get("power")
            label = {"force_charge": "Vynucené nabíjení", "force_discharge": "Vybíjení do sítě",
                     "spiral": "Spirála", "stop": "Návrat do Self-Use (stop)"}[body.action]
            src = p.get("source") or "manual"
            parts = []
            if body.action == "stop":
                parts.append("řízení zastaveno")
            elif pw is not None:
                parts.append(f"{pw/100:.1f} kW")
            parts.append("ručně" if src == "manual" else src)
            if p.get("reason"):
                parts.append(p["reason"])
            parts.append("přes EMSBOX")
            kind = "stop" if body.action == "stop" else body.action
            await alerts_db.record_event(loc_id, kind, f"{label} – {body.module_id}", " · ".join(parts))
            await notify_dispatch.notify_new_alerts()
        except Exception as exc:
            logger.debug("notifikace povelu přes box: %s", exc)
    return {"ok": True}
