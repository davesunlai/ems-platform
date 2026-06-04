"""Konfigurace a stav spínání kontaktu dle SOC (per zařízení)."""
from __future__ import annotations

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_config (
                device_id      TEXT PRIMARY KEY,
                enabled        BOOLEAN NOT NULL DEFAULT FALSE,
                upper_soc      INTEGER NOT NULL DEFAULT 100,
                lower_soc      INTEGER NOT NULL DEFAULT 95,
                contact_on     BOOLEAN NOT NULL DEFAULT FALSE,
                last_decision  TEXT,
                last_action_at TIMESTAMPTZ
            )
            """
        )


async def get(device_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM contact_config WHERE device_id = $1", device_id)
    return dict(row) if row else None


async def list_all() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM contact_config ORDER BY device_id")
    return [dict(r) for r in rows]


async def upsert(device_id: str, patch: dict) -> dict:
    cur = await get(device_id) or {}
    enabled = patch.get("enabled", cur.get("enabled", False))
    upper = patch.get("upper_soc", cur.get("upper_soc", 100))
    lower = patch.get("lower_soc", cur.get("lower_soc", 95))
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO contact_config (device_id, enabled, upper_soc, lower_soc)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (device_id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                upper_soc = EXCLUDED.upper_soc,
                lower_soc = EXCLUDED.lower_soc
            RETURNING *
            """,
            device_id, enabled, upper, lower,
        )
    return dict(row)


async def set_state(device_id: str, on: bool, decision: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE contact_config SET contact_on = $2, last_decision = $3, "
            "last_action_at = now() WHERE device_id = $1",
            device_id, on, decision,
        )


async def set_decision(device_id: str, decision: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE contact_config SET last_decision = $2 WHERE device_id = $1",
            device_id, decision,
        )
