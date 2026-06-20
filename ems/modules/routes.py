"""Admin endpointy pro správu modulů."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from . import db
from .models import Module, ModuleCreate, ModuleUpdate

router = APIRouter(prefix="/api/admin", tags=["modules"])

ADAPTERS = ["goodwe", "solis", "mock"]  # dostupné adaptéry pro UI


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
