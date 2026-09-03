"""EMSBOX — edge gateway: schéma a dotazy (brief docs/EMSBOX-BRIEF.md §6).

Pozn. k dedupu telemetrie: tabulka samples nemá unique constraint a přidávat ho
na živou hypertable je riskantní (existující duplicity by migraci shodily).
Ingest proto dedupuje anti-joinem (NOT EXISTS) — batch-level idempotenci navíc
zajišťuje ingest_batches (TTL 7 dní). Continuous aggregates v systému NEJSOU
(agregace se počítají on-the-fly), takže zpětné dohrání měsíce dat je bezpečné.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone

from ems.api.db import get_pool

BATCH_TTL_DAYS = 7
MAX_BATCH_ROWS = 1000


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emsbox (
                id SERIAL PRIMARY KEY,
                locality_id INT NOT NULL REFERENCES localities(id),
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                hw_info JSONB,
                created_at TIMESTAMPTZ DEFAULT now(),
                last_heartbeat TIMESTAMPTZ,
                last_ingest TIMESTAMPTZ,
                buffer_rows INT,
                buffer_oldest_ts TIMESTAMPTZ,
                clock_drift_s REAL,
                heartbeat_devices JSONB,
                agent_version TEXT,
                status TEXT DEFAULT 'pairing'
            )
            """)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emsbox_pairing_codes (
                code TEXT PRIMARY KEY,
                locality_id INT NOT NULL,
                name TEXT NOT NULL DEFAULT 'EMSBOX',
                expires_at TIMESTAMPTZ NOT NULL,
                used BOOLEAN DEFAULT FALSE
            )
            """)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_batches (
                batch_id UUID PRIMARY KEY,
                box_id INT NOT NULL,
                received_at TIMESTAMPTZ DEFAULT now()
            )
            """)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_rules (
                id SERIAL PRIMARY KEY,
                locality_id INT NOT NULL,
                scope TEXT NOT NULL,
                target_id INT,
                kind TEXT NOT NULL,
                threshold_min INT DEFAULT 15,
                channel TEXT DEFAULT 'email',
                recipients TEXT[],
                enabled BOOLEAN DEFAULT TRUE,
                last_mail_at TIMESTAMPTZ
            )
            """)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_events (
                id SERIAL PRIMARY KEY,
                rule_id INT NOT NULL,
                opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                closed_at TIMESTAMPTZ,
                detail JSONB
            )
            """)
        await conn.execute("ALTER TABLE modules ADD COLUMN IF NOT EXISTS emsbox_id INT REFERENCES emsbox(id)")
        await conn.execute("ALTER TABLE modules ADD COLUMN IF NOT EXISTS transport_params JSONB")


# --- párování ---------------------------------------------------------------
async def create_pairing_code(locality_id: int, name: str) -> dict:
    code = secrets.token_hex(4).upper()          # 8 znaků
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO emsbox_pairing_codes (code, locality_id, name, expires_at) "
            "VALUES ($1, $2, $3, now() + interval '1 hour')", code, locality_id, name)
    return {"code": code, "expires_in_min": 60}


async def pair(code: str, hw_info: dict | None) -> dict | None:
    """Spotřebuje platný kód → založí box, vrátí {box_id, box_token} (token jen teď!)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE emsbox_pairing_codes SET used = TRUE "
            "WHERE code = $1 AND NOT used AND expires_at > now() "
            "RETURNING locality_id, name", code.strip().upper())
        if not row:
            return None
        secret_part = secrets.token_urlsafe(32)
        box_id = await conn.fetchval(
            "INSERT INTO emsbox (locality_id, name, token_hash, hw_info, status) "
            "VALUES ($1, $2, '', $3, 'online') RETURNING id",
            row["locality_id"], row["name"], json.dumps(hw_info or {}))
        token = f"ebx{box_id}.{secret_part}"
        await conn.execute("UPDATE emsbox SET token_hash = $2 WHERE id = $1", box_id, _hash(token))
        return {"box_id": box_id, "box_token": token, "locality_id": row["locality_id"]}


async def verify_token(token: str) -> dict | None:
    """Token formát 'ebx<id>.<secret>' → box dict, jinak None."""
    if not token.startswith("ebx") or "." not in token:
        return None
    try:
        box_id = int(token[3:].split(".", 1)[0])
    except ValueError:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM emsbox WHERE id = $1 AND status != 'disabled'", box_id)
    if not row or row["token_hash"] != _hash(token):
        return None
    return dict(row)


# --- ingest -----------------------------------------------------------------
async def batch_already_seen(batch_id: str, box_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        ins = await conn.fetchrow(
            "INSERT INTO ingest_batches (batch_id, box_id) VALUES ($1, $2) "
            "ON CONFLICT (batch_id) DO NOTHING RETURNING batch_id", batch_id, box_id)
        await conn.execute("DELETE FROM ingest_batches WHERE received_at < now() - interval '%s days'"
                           % BATCH_TTL_DAYS)
    return ins is None


async def modules_for_box(box_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, adapter, params, transport_params, device_type "
            "FROM modules WHERE emsbox_id = $1", box_id)
    out = []
    for r in rows:
        d = dict(r)
        for k in ("params", "transport_params"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    d[k] = {}
        out.append(d)
    return out


async def insert_rows(rows: list[tuple]) -> int:
    """rows: (time, device_id, metric, value, unit). Dedup anti-joinem, vrací počet vložených."""
    if not rows:
        return 0
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for t, dev, metric, val, unit in rows:
                r = await conn.fetchval(
                    "INSERT INTO samples (time, device_id, metric, value, unit) "
                    "SELECT $1, $2, $3, $4, $5 WHERE NOT EXISTS ("
                    "  SELECT 1 FROM samples s WHERE s.time = $1 AND s.device_id = $2 AND s.metric = $3"
                    ") RETURNING 1", t, dev, metric, float(val), unit)
                if r:
                    inserted += 1
    return inserted


async def touch_ingest(box_id: int, accepted: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE emsbox SET last_ingest = now() WHERE id = $1", box_id)
        await conn.execute(
            "UPDATE alert_events e SET detail = COALESCE(e.detail, '{}'::jsonb) || "
            "jsonb_build_object('recovered_rows', COALESCE((e.detail->>'recovered_rows')::int, 0) + $2) "
            "FROM alert_rules r WHERE e.rule_id = r.id AND e.closed_at IS NULL "
            "AND r.scope = 'emsbox' AND r.kind = 'offline' AND r.target_id = $1", box_id, accepted)


async def heartbeat(box_id: int, body: dict) -> None:
    drift = None
    bt = body.get("box_time")
    if bt:
        try:
            drift = (datetime.now(timezone.utc) - datetime.fromisoformat(bt.replace("Z", "+00:00"))).total_seconds()
        except Exception:
            drift = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE emsbox SET last_heartbeat = now(), buffer_rows = $2, buffer_oldest_ts = $3, "
            "clock_drift_s = $4, heartbeat_devices = $5, agent_version = $6, "
            "status = CASE WHEN status = 'offline' THEN 'online' ELSE status END WHERE id = $1",
            box_id, body.get("buffer_rows"),
            datetime.fromisoformat(body["buffer_oldest_ts"].replace("Z", "+00:00")) if body.get("buffer_oldest_ts") else None,
            drift, json.dumps(body.get("devices") or []), body.get("agent_version"))


# --- boxy / alerty (uživatelské) -------------------------------------------
async def list_boxes(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, status, created_at, last_heartbeat, last_ingest, buffer_rows, "
            "buffer_oldest_ts, clock_drift_s, agent_version, heartbeat_devices "
            "FROM emsbox WHERE locality_id = $1 AND status != 'disabled' ORDER BY id", locality_id)
    out = []
    for r in rows:
        d = dict(r)
        for k in ("created_at", "last_heartbeat", "last_ingest", "buffer_oldest_ts"):
            if d.get(k):
                d[k] = d[k].isoformat()
        if isinstance(d.get("heartbeat_devices"), str):
            try:
                d["heartbeat_devices"] = json.loads(d["heartbeat_devices"])
            except Exception:
                d["heartbeat_devices"] = []
        out.append(d)
    return out


async def disable_box(box_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE emsbox SET status = 'disabled' WHERE id = $1", box_id)
        await conn.execute("UPDATE modules SET emsbox_id = NULL WHERE emsbox_id = $1", box_id)


ALERT_FIELDS = ("scope", "target_id", "kind", "threshold_min", "channel", "recipients", "enabled")


async def alert_rules(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, " + ", ".join(ALERT_FIELDS) + ", last_mail_at "
            "FROM alert_rules WHERE locality_id = $1 ORDER BY id", locality_id)
    out = []
    for r in rows:
        d = dict(r)
        if d.get("last_mail_at"):
            d["last_mail_at"] = d["last_mail_at"].isoformat()
        out.append(d)
    return out


async def alert_rule_create(locality_id: int, d: dict) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO alert_rules (locality_id, scope, target_id, kind, threshold_min, channel, recipients, enabled) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
            locality_id, d["scope"], d.get("target_id"), d["kind"], d.get("threshold_min", 15),
            d.get("channel", "email"), d.get("recipients"), d.get("enabled", True))


async def alert_rule_update(rule_id: int, d: dict) -> None:
    sets, vals = [], []
    for k in ALERT_FIELDS:
        if k in d:
            vals.append(d[k])
            sets.append(f"{k} = ${len(vals)}")
    if not sets:
        return
    vals.append(rule_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE alert_rules SET {', '.join(sets)} WHERE id = ${len(vals)}", *vals)


async def alert_rule_delete(rule_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM alert_rules WHERE id = $1", rule_id)
        await conn.execute("DELETE FROM alert_events WHERE rule_id = $1", rule_id)


async def locality_recipient_emails(locality_id: int) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT u.email FROM users u JOIN user_localities ul ON ul.user_id = u.id "
            "WHERE ul.locality_id = $1 AND u.email IS NOT NULL AND u.email != '' AND u.active", locality_id)
    return [r["email"] for r in rows]
