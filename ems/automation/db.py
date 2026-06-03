"""DB vrstva automatizačních pravidel."""
from __future__ import annotations

import json

from ems.api.db import get_pool
from .models import Rule


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS automation_rules (
                id             TEXT PRIMARY KEY,
                type           TEXT NOT NULL DEFAULT 'spot_charge',
                enabled        BOOLEAN NOT NULL DEFAULT TRUE,
                params         JSONB NOT NULL DEFAULT '{}',
                last_decision  TEXT,
                last_action    TEXT,
                last_action_at TIMESTAMPTZ,
                last_eval_at   TIMESTAMPTZ,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _row(r) -> Rule:
    return Rule(
        id=r["id"], type=r["type"], enabled=r["enabled"],
        params=json.loads(r["params"]) if isinstance(r["params"], str) else r["params"],
        last_decision=r["last_decision"], last_action=r["last_action"],
        last_action_at=r["last_action_at"].isoformat() if r["last_action_at"] else None,
        last_eval_at=r["last_eval_at"].isoformat() if r["last_eval_at"] else None,
    )


async def list_all() -> list[Rule]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM automation_rules ORDER BY id")
    return [_row(r) for r in rows]


async def list_enabled() -> list[Rule]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM automation_rules WHERE enabled = TRUE ORDER BY id")
    return [_row(r) for r in rows]


async def create(rule_id: str, rtype: str, enabled: bool, params: dict) -> Rule:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO automation_rules (id, type, enabled, params) "
            "VALUES ($1, $2, $3, $4::jsonb) RETURNING *",
            rule_id, rtype, enabled, json.dumps(params),
        )
    return _row(row)


async def update(rule_id: str, patch: dict) -> Rule | None:
    sets, args = [], []
    if patch.get("enabled") is not None:
        args.append(patch["enabled"]); sets.append(f"enabled = ${len(args)}")
    if patch.get("params") is not None:
        args.append(json.dumps(patch["params"])); sets.append(f"params = ${len(args)}::jsonb")
    if not sets:
        return None
    args.append(rule_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE automation_rules SET {', '.join(sets)} WHERE id = ${len(args)} RETURNING *", *args
        )
    return _row(row) if row else None


async def delete(rule_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM automation_rules WHERE id = $1", rule_id)
    return res.endswith("1")


async def mark_eval(rule_id: str, decision: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE automation_rules SET last_decision = $1, last_eval_at = now() WHERE id = $2",
            decision, rule_id,
        )


async def mark_action(rule_id: str, action: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE automation_rules SET last_action = $1, last_action_at = now() WHERE id = $2",
            action, rule_id,
        )
