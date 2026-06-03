"""Endpointy trhu (spotová cena)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db

router = APIRouter(prefix="/api", tags=["market"])


class ManualPrice(BaseModel):
    price: float


@router.get("/market/spot")
async def spot(_: dict = Depends(require_permission("read"))):
    return await db.get_state()


@router.post("/admin/market/manual")
async def set_manual(body: ManualPrice, _: dict = Depends(require_permission("admin"))):
    await db.set_manual(body.price)
    return await db.get_state()


@router.delete("/admin/market/manual")
async def clear_manual(_: dict = Depends(require_permission("admin"))):
    await db.clear_manual()
    return await db.get_state()
