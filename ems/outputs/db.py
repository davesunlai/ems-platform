"""Spínací výstupy: cíl (kontakt střídače / eWeLink) + spouštěč (SOC / přebytek)."""
from __future__ import annotations

import json

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS switch_outputs (
                id             SERIAL PRIMARY KEY,
                name           TEXT NOT NULL,
                enabled        BOOLEAN NOT NULL DEFAULT FALSE,
                locality_id    INTEGER REFERENCES localities(id) ON DELETE SET NULL,
                output_kind    TEXT NOT NULL DEFAULT 'goodwe_contact',  -- goodwe_contact | ewelink
                target         TEXT NOT NULL,                            -- inverter device_id | eWeLink deviceid
                trigger        TEXT NOT NULL DEFAULT 'soc',              -- soc | surplus
                params         JSONB NOT NULL DEFAULT '{}',
                is_on          BOOLEAN NOT NULL DEFAULT FALSE,
                on_since       TIMESTAMPTZ,
                last_decision  TEXT,
                last_action_at TIMESTAMPTZ
            )
            """
        )
        await conn.execute("ALTER TABLE switch_outputs ADD COLUMN IF NOT EXISTS off_lock_until TIMESTAMPTZ")
        # jednorázová migrace starých SOC kontaktů
        n = await conn.fetchval("SELECT count(*) FROM switch_outputs")
        if n == 0:
            try:
                rows = await conn.fetch("SELECT * FROM contact_config")
            except Exception:
                rows = []
            for r in rows:
                await conn.execute(
                    "INSERT INTO switch_outputs (name, enabled, output_kind, target, trigger, params, is_on) "
                    "VALUES ($1,$2,'goodwe_contact',$3,'soc',$4::jsonb,$5)",
                    f"Kontakt {r['device_id']}", r["enabled"], r["device_id"],
                    json.dumps({"upper_soc": r["upper_soc"], "lower_soc": r["lower_soc"]}), r["contact_on"])


def _row(r) -> dict:
    d = dict(r)
    if isinstance(d.get("params"), str):
        d["params"] = json.loads(d["params"])
    return d


async def list_all() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM switch_outputs ORDER BY id")
    return [_row(r) for r in rows]


async def get(out_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM switch_outputs WHERE id = $1", out_id)
    return _row(r) if r else None


async def create(d: dict) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO switch_outputs (name, enabled, locality_id, output_kind, target, trigger, params) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb) RETURNING *",
            d["name"], d.get("enabled", False), d.get("locality_id"), d["output_kind"],
            d["target"], d["trigger"], json.dumps(d.get("params", {})))
    return _row(r)


async def update(out_id: int, patch: dict) -> dict | None:
    sets, args = [], []
    for k in ("name", "enabled", "locality_id", "output_kind", "target", "trigger"):
        if k in patch:
            args.append(patch[k]); sets.append(f"{k} = ${len(args)}")
    if "params" in patch:
        args.append(json.dumps(patch["params"])); sets.append(f"params = ${len(args)}::jsonb")
    if not sets:
        return await get(out_id)
    args.append(out_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            f"UPDATE switch_outputs SET {', '.join(sets)} WHERE id = ${len(args)} RETURNING *", *args)
    return _row(r) if r else None


async def delete(out_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM switch_outputs WHERE id = $1", out_id)


async def set_state(out_id: int, is_on: bool, decision: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE switch_outputs SET is_on=$1, last_decision=$2, last_action_at=now(), "
            "on_since = CASE WHEN $1 AND NOT is_on THEN now() WHEN NOT $1 THEN NULL ELSE on_since END "
            "WHERE id=$3", is_on, decision, out_id)


async def set_lock(out_id: int, until) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE switch_outputs SET off_lock_until=$1 WHERE id=$2", until, out_id)


async def set_decision(out_id: int, decision: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE switch_outputs SET last_decision=$1 WHERE id=$2", decision, out_id)
