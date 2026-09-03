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
