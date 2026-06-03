"""Endpointy automatizace (pravidla)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from . import db
from .models import Rule, RuleCreate, RuleUpdate

router = APIRouter(prefix="/api", tags=["automation"])


@router.get("/automation", response_model=list[Rule])
async def list_rules(_: dict = Depends(require_permission("control"))):
    return await db.list_all()


@router.post("/admin/automation", response_model=Rule, status_code=201)
async def create_rule(body: RuleCreate, _: dict = Depends(require_permission("admin"))):
    if not body.id or not body.id.strip():
        raise HTTPException(status_code=400, detail="ID pravidla nesmí být prázdné")
    if any(r.id == body.id for r in await db.list_all()):
        raise HTTPException(status_code=409, detail="Pravidlo s tímto id už existuje")
    return await db.create(body.id, body.type.value, body.enabled, body.params)


@router.patch("/admin/automation/{rule_id}", response_model=Rule)
async def update_rule(rule_id: str, body: RuleUpdate, _: dict = Depends(require_permission("admin"))):
    updated = await db.update(rule_id, body.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Pravidlo nenalezeno nebo nic ke změně")
    return updated


@router.delete("/admin/automation/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, _: dict = Depends(require_permission("admin"))):
    if not await db.delete(rule_id):
        raise HTTPException(status_code=404, detail="Pravidlo nenalezeno")
