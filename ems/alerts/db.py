"""Operační události (vynucené nabíjení/vybíjení, sepnutí spotřebiče…).

Krátkodobé události, které se na ~1 h zařadí mezi výstrahy → projeví se v zvonečku,
browser notifikaci i e-mailu (přes stejný dispatcher, dedup dle id 'event:<n>').
"""
from __future__ import annotations

from ems.api.db import get_pool

EVENT_TTL_MIN = 60


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS operational_events ("
            " id BIGSERIAL PRIMARY KEY,"
            " locality_id INTEGER,"
            " kind TEXT NOT NULL,"
            " title TEXT NOT NULL,"
            " detail TEXT,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS operational_events_ts ON operational_events (created_at DESC)")


async def record_event(locality_id, kind: str, title: str, detail: str = "") -> None:
    if locality_id is None:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO operational_events (locality_id, kind, title, detail) VALUES ($1,$2,$3,$4)",
            int(locality_id), kind, title, detail)


async def recent_events(locality_ids: list[int]) -> list[dict]:
    if not locality_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, locality_id, kind, title, detail, created_at FROM operational_events "
            f"WHERE locality_id = ANY($1::int[]) AND created_at > now() - interval '{EVENT_TTL_MIN} minutes' "
            f"ORDER BY created_at DESC LIMIT 50", locality_ids)
    return [dict(r) for r in rows]
