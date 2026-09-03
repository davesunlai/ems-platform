"""EMSBOX — párování, config pull (box) + CRUD boxů a alert pravidel (uživatel)."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db
from .auth import box_auth

router = APIRouter(prefix="/api", tags=["emsbox"])
read = require_permission("read")
control = require_permission("control")


class PairBody(BaseModel):
    code: str
    hw_info: dict | None = None


@router.post("/emsbox/pair")
async def pair(body: PairBody) -> dict:
    """Public + párovací kód (1 h platnost, jednorázový)."""
    res = await db.pair(body.code, body.hw_info)
    if not res:
        raise HTTPException(status_code=400, detail="neplatný nebo expirovaný párovací kód")
    return res


@router.get("/emsbox/{box_id}/config")
async def box_config(box_id: int, request: Request, box: dict = Depends(box_auth)):
    """Config pull (ETag) — server je zdroj pravdy pro definici zařízení."""
    if box_id != box["id"]:
        raise HTTPException(status_code=403, detail="box_id nesouhlasí s tokenem")
    mods = await db.modules_for_box(box_id)
    devices = []
    for m in mods:
        tp = m.get("transport_params") or {}
        devices.append({
            "device_uid": m["id"],
            "name": m["name"],
            "adapter": m["adapter"],
            "transport": tp.get("transport", "modbus_tcp"),
            "params": {**(m.get("params") or {}), **{k: v for k, v in tp.items() if k != "transport"}},
            "poll_s": tp.get("poll_s", 30),
        })
    payload = {"box_id": box_id, "devices": devices,
               "settings": {"heartbeat_s": 60, "config_poll_s": 300, "max_batch_rows": db.MAX_BATCH_ROWS}}
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    etag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(content=body, media_type="application/json", headers={"ETag": etag})


# --- uživatelské CRUD -------------------------------------------------------
class BoxCreate(BaseModel):
    name: str = "EMSBOX"


@router.get("/localities/{locality_id}/emsboxes")
async def list_boxes(locality_id: int, _: dict = Depends(read)) -> list[dict]:
    return await db.list_boxes(locality_id)


@router.post("/localities/{locality_id}/emsboxes")
async def create_box(locality_id: int, body: BoxCreate, _: dict = Depends(control)) -> dict:
    """Vytvoří párovací kód — box se založí až při spárování."""
    return await db.create_pairing_code(locality_id, body.name.strip() or "EMSBOX")


@router.delete("/emsbox/{box_id}")
async def delete_box(box_id: int, _: dict = Depends(control)) -> dict:
    await db.disable_box(box_id)
    return {"ok": True}


class AlertRuleIn(BaseModel):
    scope: str                      # locality | emsbox | device
    target_id: int | None = None
    kind: str                       # offline | fault | rtc_drift | buffer_high
    threshold_min: int = 15
    channel: str = "email"
    recipients: list[str] | None = None
    enabled: bool = True


def _validate_rule(d: AlertRuleIn) -> None:
    if d.scope not in ("locality", "emsbox", "device"):
        raise HTTPException(status_code=400, detail="scope: locality|emsbox|device")
    if d.kind not in ("offline", "fault", "rtc_drift", "buffer_high"):
        raise HTTPException(status_code=400, detail="kind: offline|fault|rtc_drift|buffer_high")
    if d.scope != "locality" and d.target_id is None:
        raise HTTPException(status_code=400, detail="scope emsbox/device vyžaduje target_id")


@router.get("/localities/{locality_id}/alert-rules")
async def rules_list(locality_id: int, _: dict = Depends(read)) -> list[dict]:
    return await db.alert_rules(locality_id)


@router.post("/localities/{locality_id}/alert-rules")
async def rules_create(locality_id: int, body: AlertRuleIn, _: dict = Depends(control)) -> dict:
    _validate_rule(body)
    rid = await db.alert_rule_create(locality_id, body.model_dump())
    return {"id": rid}


@router.put("/alert-rules/{rule_id}")
async def rules_update(rule_id: int, body: dict, _: dict = Depends(control)) -> dict:
    await db.alert_rule_update(rule_id, body)
    return {"ok": True}


@router.delete("/alert-rules/{rule_id}")
async def rules_delete(rule_id: int, _: dict = Depends(control)) -> dict:
    await db.alert_rule_delete(rule_id)
    return {"ok": True}
