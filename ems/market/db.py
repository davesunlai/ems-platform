"""Stav trhu (aktuální spotová cena) v DB — jednořádkový cache."""
from __future__ import annotations

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_state (
                id         INT PRIMARY KEY DEFAULT 1,
                price      DOUBLE PRECISION,
                currency   TEXT NOT NULL DEFAULT 'CZK/MWh',
                manual     BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute("INSERT INTO market_state (id) VALUES (1) ON CONFLICT DO NOTHING")


async def get_state() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT price, currency, manual, updated_at FROM market_state WHERE id = 1")
    if not row:
        return {"price": None, "currency": "CZK/MWh", "manual": False, "updated_at": None}
    d = dict(row)
    d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
    return d


async def set_live_price(price: float) -> None:
    """Zapíše cenu z živého feedu (jen pokud není aktivní ruční override)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE market_state SET price = $1, updated_at = now() WHERE id = 1 AND manual = FALSE",
            price,
        )


async def set_manual(price: float) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE market_state SET price = $1, manual = TRUE, updated_at = now() WHERE id = 1",
            price,
        )


async def clear_manual() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE market_state SET manual = FALSE, updated_at = now() WHERE id = 1")
