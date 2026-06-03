"""Endpointy trhu (spotová cena)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db
from .spot import fetch_current_price_czk, fetch_day_prices

router = APIRouter(prefix="/api", tags=["market"])


class ManualPrice(BaseModel):
    price: float


@router.get("/market/spot")
async def spot(_: dict = Depends(require_permission("read"))):
    return await db.get_state()


@router.get("/market/spot-curve")
async def spot_curve(days: int = 1, _: dict = Depends(require_permission("read"))):
    days = max(1, min(days, 30))
    return {"days": days, "slots": await db.history_window(days)}


@router.post("/admin/market/manual")
async def set_manual(body: ManualPrice, _: dict = Depends(require_permission("admin"))):
    await db.set_manual(body.price)
    return await db.get_state()


@router.delete("/admin/market/manual")
async def clear_manual(_: dict = Depends(require_permission("admin"))):
    await db.clear_manual()
    # okamžitě natáhni živou cenu (a křivku), ať se nečeká na refresh cyklus
    try:
        price = await fetch_current_price_czk()
        if price is not None:
            await db.set_live_price(price)
        curve = await fetch_day_prices()
        if curve is not None:
            await db.set_curve(curve)
    except Exception:
        pass
    return await db.get_state()
