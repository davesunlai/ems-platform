"""Audit povelů — kdo, kdy, co, výsledek."""
from __future__ import annotations

import json

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS command_audit (
                id        SERIAL PRIMARY KEY,
                time      TIMESTAMPTZ NOT NULL DEFAULT now(),
                username  TEXT,
                module_id TEXT,
                action    TEXT,
                params    JSONB,
                ok        BOOLEAN,
                result    JSONB
            )
            """
        )


async def record(username, module_id, action, params, ok, result) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO command_audit (username, module_id, action, params, ok, result)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
            """,
            username, module_id, action, json.dumps(params), ok, json.dumps(result),
        )


async def list_recent(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, time, username, module_id, action, params, ok, result "
            "FROM command_audit ORDER BY time DESC LIMIT $1",
            limit,
        )
    out = []
    for r in rows:
        d = dict(r)
        d["time"] = d["time"].isoformat()
        for k in ("params", "result"):
            if isinstance(d[k], str):
                d[k] = json.loads(d[k])
        out.append(d)
    return out
