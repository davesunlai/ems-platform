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


async def list_recent(limit: int = 50, offset: int = 0, q: str = "", include_reads: bool = False) -> list[dict]:
    pool = await get_pool()
    q = (q or "").strip()
    conds, args = [], [limit, offset]
    if not include_reads:
        conds.append("action <> 'read_controls'")
    if q:
        args.append(f"%{q}%")
        conds.append(f"(username ILIKE ${len(args)} OR module_id ILIKE ${len(args)} OR action ILIKE ${len(args)} "
                     f"OR params::text ILIKE ${len(args)} OR result::text ILIKE ${len(args)})")
    where = ("WHERE " + " AND ".join(conds) + " ") if conds else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, time, username, module_id, action, params, ok, result "
            f"FROM command_audit {where}ORDER BY time DESC LIMIT $1 OFFSET $2",
            *args,
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


# --- Spotové auto-vybíjení do sítě (per Solis modul, hystereze + podlaha SoC) ---
_SPOT_DEFAULT = {"enabled": False, "price_on": 4000.0, "price_off": 3000.0,
                 "power_kw": 10.0, "soc_floor": 20.0, "active": False,
                 "precharge_enabled": False, "precharge_hours": 3.0, "precharge_power_kw": 10.0,
                 "precharge_min_spread": 1000.0, "precharge_max_buy": 0.0, "precharge_active": False,
                 "charge_enabled": False, "charge_price_on": 0.0, "charge_price_off": 200.0,
                 "charge_power_kw": 10.0, "charge_soc_ceiling": 95.0, "charge_active": False}


async def ensure_spot_rule_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spot_discharge_rules (
                module_id TEXT PRIMARY KEY,
                enabled   BOOLEAN NOT NULL DEFAULT FALSE,
                price_on  DOUBLE PRECISION NOT NULL DEFAULT 4000,
                price_off DOUBLE PRECISION NOT NULL DEFAULT 3000,
                power_kw  DOUBLE PRECISION NOT NULL DEFAULT 10,
                soc_floor DOUBLE PRECISION NOT NULL DEFAULT 20,
                active    BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )
        for col, ddl in (
            ("precharge_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("precharge_hours", "DOUBLE PRECISION NOT NULL DEFAULT 3"),
            ("precharge_power_kw", "DOUBLE PRECISION NOT NULL DEFAULT 10"),
            ("precharge_min_spread", "DOUBLE PRECISION NOT NULL DEFAULT 1000"),
            ("precharge_max_buy", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("precharge_active", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("charge_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("charge_price_on", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("charge_price_off", "DOUBLE PRECISION NOT NULL DEFAULT 200"),
            ("charge_power_kw", "DOUBLE PRECISION NOT NULL DEFAULT 10"),
            ("charge_soc_ceiling", "DOUBLE PRECISION NOT NULL DEFAULT 95"),
            ("charge_active", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ):
            await conn.execute(f"ALTER TABLE spot_discharge_rules ADD COLUMN IF NOT EXISTS {col} {ddl}")


async def get_spot_rule(module_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM spot_discharge_rules WHERE module_id=$1", module_id)
    return dict(r) if r else {"module_id": module_id, **_SPOT_DEFAULT}


async def set_spot_rule(module_id: str, enabled, price_on, price_off, power_kw, soc_floor,
                        precharge_enabled=False, precharge_hours=3, precharge_power_kw=10,
                        precharge_min_spread=1000, precharge_max_buy=0,
                        charge_enabled=False, charge_price_on=0, charge_price_off=200,
                        charge_power_kw=10, charge_soc_ceiling=95) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO spot_discharge_rules (module_id, enabled, price_on, price_off, power_kw, soc_floor, "
            "  precharge_enabled, precharge_hours, precharge_power_kw, precharge_min_spread, precharge_max_buy, "
            "  charge_enabled, charge_price_on, charge_price_off, charge_power_kw, charge_soc_ceiling) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) ON CONFLICT (module_id) DO UPDATE SET "
            "enabled=EXCLUDED.enabled, price_on=EXCLUDED.price_on, price_off=EXCLUDED.price_off, "
            "power_kw=EXCLUDED.power_kw, soc_floor=EXCLUDED.soc_floor, "
            "precharge_enabled=EXCLUDED.precharge_enabled, precharge_hours=EXCLUDED.precharge_hours, "
            "precharge_power_kw=EXCLUDED.precharge_power_kw, precharge_min_spread=EXCLUDED.precharge_min_spread, "
            "precharge_max_buy=EXCLUDED.precharge_max_buy, "
            "charge_enabled=EXCLUDED.charge_enabled, charge_price_on=EXCLUDED.charge_price_on, "
            "charge_price_off=EXCLUDED.charge_price_off, charge_power_kw=EXCLUDED.charge_power_kw, "
            "charge_soc_ceiling=EXCLUDED.charge_soc_ceiling RETURNING *",
            module_id, bool(enabled), float(price_on), float(price_off), float(power_kw), float(soc_floor),
            bool(precharge_enabled), float(precharge_hours), float(precharge_power_kw),
            float(precharge_min_spread), float(precharge_max_buy),
            bool(charge_enabled), float(charge_price_on), float(charge_price_off),
            float(charge_power_kw), float(charge_soc_ceiling))
    return dict(r)


async def list_spot_rules_enabled() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM spot_discharge_rules WHERE enabled=true")
    return [dict(r) for r in rows]


async def list_spot_rules_winddown() -> list[dict]:
    """Pravidla, kde je nějaká spotová funkce vypnutá, ale příznak aktivity je stále nastaven
    (modul ji možná ještě vykonává a je třeba ji zastavit)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM spot_discharge_rules WHERE "
            "(active AND NOT enabled) OR (precharge_active AND NOT precharge_enabled) "
            "OR (charge_active AND NOT charge_enabled)")
    return [dict(r) for r in rows]


async def set_spot_rule_active(module_id: str, active: bool) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE spot_discharge_rules SET active=$2 WHERE module_id=$1", module_id, bool(active))


async def set_precharge_active(module_id: str, active: bool) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE spot_discharge_rules SET precharge_active=$2 WHERE module_id=$1", module_id, bool(active))


async def set_charge_active(module_id: str, active: bool) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE spot_discharge_rules SET charge_active=$2 WHERE module_id=$1", module_id, bool(active))
