"""Uložení eWeLink OAuth tokenu (přežije restart). Jeden řádek (id=1)."""
from __future__ import annotations

import datetime as dt

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ewelink_token (
                id            INTEGER PRIMARY KEY DEFAULT 1,
                access_token  TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                region        TEXT NOT NULL,
                at_expire     TIMESTAMPTZ,
                rt_expire     TIMESTAMPTZ,
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ewelink_token_single CHECK (id = 1)
            )
            """
        )


async def get_token() -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ewelink_token WHERE id = 1")
    return dict(row) if row else None


async def save_token(access_token: str, refresh_token: str, region: str,
                     at_expire: dt.datetime | None, rt_expire: dt.datetime | None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ewelink_token (id, access_token, refresh_token, region, at_expire, rt_expire, updated_at)
            VALUES (1, $1, $2, $3, $4, $5, now())
            ON CONFLICT (id) DO UPDATE SET
                access_token=EXCLUDED.access_token, refresh_token=EXCLUDED.refresh_token,
                region=EXCLUDED.region, at_expire=EXCLUDED.at_expire, rt_expire=EXCLUDED.rt_expire,
                updated_at=now()
            """,
            access_token, refresh_token, region, at_expire, rt_expire,
        )


async def clear() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ewelink_token WHERE id = 1")
