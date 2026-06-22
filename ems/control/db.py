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


# --- Fronta povelů (pro adaptéry s jediným spojením, např. Solis přes kolektor) ---
async def ensure_queue_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS control_queue (
                id          SERIAL PRIMARY KEY,
                module_id   TEXT NOT NULL,
                action      TEXT NOT NULL,
                params      JSONB,
                status      TEXT NOT NULL DEFAULT 'pending',
                result      JSONB,
                username    TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                executed_at TIMESTAMPTZ
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS control_queue_pending "
            "ON control_queue (module_id) WHERE status='pending'"
        )


async def enqueue(module_id: str, action: str, params: dict, username: str | None = None) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO control_queue (module_id, action, params, username) "
            "VALUES ($1, $2, $3::jsonb, $4) RETURNING id",
            module_id, action, json.dumps(params or {}), username)


async def fetch_pending(module_ids: list[str]) -> list[dict]:
    if not module_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, module_id, action, params, username FROM control_queue "
            "WHERE status='pending' AND module_id = ANY($1::text[]) ORDER BY id",
            module_ids)
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["params"], str):
            d["params"] = json.loads(d["params"])
        out.append(d)
    return out


async def complete(cmd_id: int, ok: bool, result: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE control_queue SET status=$2, result=$3::jsonb, executed_at=now() WHERE id=$1",
            cmd_id, "done" if ok else "error", json.dumps(result))


async def get_command(cmd_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, module_id, action, params, status, result, created_at, executed_at "
            "FROM control_queue WHERE id=$1", cmd_id)
    if not r:
        return None
    d = dict(r)
    for k in ("params", "result"):
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    for k in ("created_at", "executed_at"):
        if d[k]:
            d[k] = d[k].isoformat()
    return d


# --- aktuální vynucený stav modulu (co EMS reálně nařídil) -------------------
async def ensure_state_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS control_state (
                module_id  TEXT PRIMARY KEY,
                action     TEXT NOT NULL DEFAULT 'idle',   -- idle|force_charge|force_discharge|set_work_mode|...
                params     JSONB,
                source     TEXT,                           -- 'manual' | 'planner' | 'rule'
                username   TEXT,
                since      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


async def set_state(module_id: str, action: str, params: dict | None,
                    source: str = "manual", username: str | None = None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control_state (module_id, action, params, source, username, since) "
            "VALUES ($1,$2,$3::jsonb,$4,$5, now()) "
            "ON CONFLICT (module_id) DO UPDATE SET "
            "action=EXCLUDED.action, params=EXCLUDED.params, source=EXCLUDED.source, "
            "username=EXCLUDED.username, "
            # since přepiš jen když se akce změnila (jinak drž původní začátek)
            "since = CASE WHEN control_state.action IS DISTINCT FROM EXCLUDED.action THEN now() ELSE control_state.since END",
            module_id, action, json.dumps(params or {}), source, username)


async def get_states(module_ids: list[str]) -> dict[str, dict]:
    if not module_ids:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT module_id, action, params, source, username, since "
            "FROM control_state WHERE module_id = ANY($1::text[])", module_ids)
    out = {}
    for r in rows:
        d = dict(r)
        if isinstance(d["params"], str):
            d["params"] = json.loads(d["params"])
        d["since"] = d["since"].isoformat() if d["since"] else None
        out[d["module_id"]] = d
    return out
