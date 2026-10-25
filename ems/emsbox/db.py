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
MAX_BATCH_ROWS = 1000          # co server ještě PŘIJME (zpětná kompatibilita starších agentů)
# v1.2.2: kolik řádků má box posílat v jedné dávce. Řádek = jeden cyklus zařízení (~60 veličin),
# 1000 řádků = 60 000 vzorků → vkládání trvalo > 25 s (timeout agenta) → box dávku opakoval donekonečna
# (incident 25. 10., buffer 959 ř. 11 h). 40 řádků ≈ 2 400 vzorků ≈ zlomek sekundy hromadným INSERTem.
BOX_BATCH_ROWS = 40


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
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS public_ip TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS private_ip TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS hostname TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS wifi_ssid TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS wifi_psk TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS pending_action TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS last_action TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS last_action_status TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS last_action_at TIMESTAMPTZ")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS last_action_detail TEXT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS last_action_username TEXT")
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS emsbox_action_log (
                 id BIGSERIAL PRIMARY KEY,
                 box_id INT NOT NULL,
                 action TEXT NOT NULL,
                 username TEXT,
                 status TEXT NOT NULL DEFAULT 'pending',
                 detail TEXT,
                 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                 updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS emsbox_action_log_box ON emsbox_action_log (box_id, id DESC)")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS disk_total_mb INT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS disk_free_mb INT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS mem_total_mb INT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS mem_used_mb INT")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emsbox_announce (
                fingerprint TEXT PRIMARY KEY,
                private_ip TEXT,
                public_ip TEXT,
                agent_version TEXT,
                hw JSONB,
                first_seen TIMESTAMPTZ DEFAULT now(),
                last_seen TIMESTAMPTZ DEFAULT now()
            )
            """)
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS uptime_s BIGINT")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS last_heartbeat_body JSONB")
        await conn.execute("ALTER TABLE emsbox ADD COLUMN IF NOT EXISTS buffer_peak_rows INT DEFAULT 0")
        # --- evidence bufferování (v0.93.0): epizody + hodinová statistika syncu ---
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS emsbox_buffer_episodes (
                 id BIGSERIAL PRIMARY KEY,
                 box_id INT NOT NULL,
                 data_from TIMESTAMPTZ NOT NULL,      -- nejstarší dohraný vzorek (≈ začátek výpadku)
                 detected_at TIMESTAMPTZ NOT NULL,    -- první dávka z bufferu dorazila (≈ obnova spojení)
                 ended_at TIMESTAMPTZ,                -- buffer dohrán (NULL = dohrává se)
                 batches INT NOT NULL DEFAULT 0,
                 rows_total INT NOT NULL DEFAULT 0,
                 rows_accepted INT NOT NULL DEFAULT 0,
                 rows_dup INT NOT NULL DEFAULT 0,
                 peak_buffer_rows INT NOT NULL DEFAULT 0)""")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS emsbox_buffer_episodes_box ON emsbox_buffer_episodes (box_id, id DESC)")
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS emsbox_sync_hourly (
                 box_id INT NOT NULL,
                 hour TIMESTAMPTZ NOT NULL,
                 batches INT NOT NULL DEFAULT 0,
                 rows_total INT NOT NULL DEFAULT 0,
                 rows_accepted INT NOT NULL DEFAULT 0,
                 rows_dup INT NOT NULL DEFAULT 0,
                 backfill_batches INT NOT NULL DEFAULT 0,
                 backfill_rows INT NOT NULL DEFAULT 0,
                 max_lag_s INT NOT NULL DEFAULT 0,
                 PRIMARY KEY (box_id, hour))""")
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
        loc_name = await conn.fetchval("SELECT name FROM localities WHERE id = $1", row["locality_id"])
        return {"box_id": box_id, "box_token": token, "box_name": row["name"],
                "locality_id": row["locality_id"], "locality_name": loc_name}


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
    """rows: (time, device_id, metric, value, unit). Dedup anti-joinem, vrací počet vložených.
    v1.2.2: JEDEN hromadný INSERT … SELECT FROM unnest() místo vkládání po jednom (60 000 příkazů
    na dávku z bufferu = timeout agenta). Duplicity uvnitř dávky odfiltruje DISTINCT ON."""
    if not rows:
        return 0
    ts = [r[0] for r in rows]
    devs = [r[1] for r in rows]
    mets = [r[2] for r in rows]
    vals = [float(r[3]) for r in rows]
    units = [r[4] or "" for r in rows]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            n = await conn.fetchval(
                """WITH src AS (
                       SELECT DISTINCT ON (t, d, m) t, d, m, v, u
                       FROM unnest($1::timestamptz[], $2::text[], $3::text[], $4::float8[], $5::text[]) AS x(t, d, m, v, u)
                       ORDER BY t, d, m
                   ), ins AS (
                       INSERT INTO samples (time, device_id, metric, value, unit)
                       SELECT t, d, m, v, u FROM src
                       WHERE NOT EXISTS (SELECT 1 FROM samples s WHERE s.time = src.t AND s.device_id = src.d AND s.metric = src.m)
                       RETURNING 1
                   ) SELECT count(*) FROM ins""",
                ts, devs, mets, vals, units)
    return int(n or 0)


async def touch_ingest(box_id: int, accepted: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE emsbox SET last_ingest = now() WHERE id = $1", box_id)
        await conn.execute(
            "UPDATE alert_events e SET detail = COALESCE(e.detail, '{}'::jsonb) || "
            "jsonb_build_object('recovered_rows', COALESCE((e.detail->>'recovered_rows')::int, 0) + $2) "
            "FROM alert_rules r WHERE e.rule_id = r.id AND e.closed_at IS NULL "
            "AND r.scope = 'emsbox' AND r.kind = 'offline' AND r.target_id = $1", box_id, accepted)


BACKFILL_LAG_S = 180        # dávka s daty staršími než 3 min = dohrávání z bufferu
SYNC_HOURLY_KEEP_DAYS = 90
EPISODES_KEEP_DAYS = 365


async def record_sync(box_id: int, rows_total: int, accepted: int, dup: int,
                      oldest_ts: datetime | None, newest_ts: datetime | None) -> None:
    """Evidence každé dávky telemetrie: hodinová statistika + detekce epizod bufferování.
    Agent posílá nejnovější napřed, takže dávka se STARÝMI daty (lag > BACKFILL_LAG_S)
    = box dohrává buffer po výpadku spojení. Epizoda se otevře první takovou dávkou
    (data_from = nejstarší vzorek, detected_at = teď) a zavře první čerstvou dávkou."""
    now = datetime.now(timezone.utc)
    lag = int((now - oldest_ts).total_seconds()) if oldest_ts else 0
    backfill = oldest_ts is not None and lag > BACKFILL_LAG_S
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO emsbox_sync_hourly (box_id, hour, batches, rows_total, rows_accepted, rows_dup,
                                               backfill_batches, backfill_rows, max_lag_s)
               VALUES ($1, date_trunc('hour', now()), 1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (box_id, hour) DO UPDATE SET
                 batches = emsbox_sync_hourly.batches + 1,
                 rows_total = emsbox_sync_hourly.rows_total + EXCLUDED.rows_total,
                 rows_accepted = emsbox_sync_hourly.rows_accepted + EXCLUDED.rows_accepted,
                 rows_dup = emsbox_sync_hourly.rows_dup + EXCLUDED.rows_dup,
                 backfill_batches = emsbox_sync_hourly.backfill_batches + EXCLUDED.backfill_batches,
                 backfill_rows = emsbox_sync_hourly.backfill_rows + EXCLUDED.backfill_rows,
                 max_lag_s = GREATEST(emsbox_sync_hourly.max_lag_s, EXCLUDED.max_lag_s)""",
            box_id, rows_total, accepted, dup, 1 if backfill else 0, accepted if backfill else 0, lag)
        open_ep = await conn.fetchrow(
            "SELECT id, data_from FROM emsbox_buffer_episodes WHERE box_id = $1 AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1", box_id)
        if backfill:
            if open_ep:
                await conn.execute(
                    "UPDATE emsbox_buffer_episodes SET batches = batches + 1, rows_total = rows_total + $2, "
                    "rows_accepted = rows_accepted + $3, rows_dup = rows_dup + $4, "
                    "data_from = LEAST(data_from, $5) WHERE id = $1",
                    open_ep["id"], rows_total, accepted, dup, oldest_ts)
            else:
                peak = await conn.fetchval("SELECT COALESCE(buffer_rows, 0) FROM emsbox WHERE id = $1", box_id) or 0
                await conn.execute(
                    "INSERT INTO emsbox_buffer_episodes (box_id, data_from, detected_at, batches, rows_total, "
                    "rows_accepted, rows_dup, peak_buffer_rows) VALUES ($1, $2, now(), 1, $3, $4, $5, $6)",
                    box_id, oldest_ts, rows_total, accepted, dup, max(peak, rows_total))
        elif open_ep:
            await conn.execute("UPDATE emsbox_buffer_episodes SET ended_at = now() WHERE id = $1", open_ep["id"])
        # úklid (levný, jednou za čas by stačilo — ale je to jeden DELETE na dávku)
        if now.minute == 0 and now.second < 5:
            await conn.execute("DELETE FROM emsbox_sync_hourly WHERE hour < now() - interval '%s days'"
                               % SYNC_HOURLY_KEEP_DAYS)
            await conn.execute("DELETE FROM emsbox_buffer_episodes WHERE detected_at < now() - interval '%s days'"
                               % EPISODES_KEEP_DAYS)


async def announce(fingerprint: str, private_ip: str | None, public_ip: str | None,
                   agent_version: str | None, hw: dict | None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO emsbox_announce (fingerprint, private_ip, public_ip, agent_version, hw) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (fingerprint) DO UPDATE SET private_ip=$2, public_ip=$3, "
            "agent_version=$4, hw=$5, last_seen=now()",
            fingerprint, private_ip, public_ip, agent_version, json.dumps(hw or {}))
        await conn.execute("DELETE FROM emsbox_announce WHERE last_seen < now() - interval '7 days'")


async def overview() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        boxes = await conn.fetch(
            "SELECT e.id, e.name, e.status, e.locality_id, l.name AS locality_name, "
            "e.last_heartbeat, e.last_ingest, e.buffer_rows, e.clock_drift_s, e.agent_version, "
            "e.public_ip, e.private_ip, e.hostname, e.wifi_ssid, e.wifi_psk, "
            "e.disk_total_mb, e.disk_free_mb, e.mem_total_mb, e.mem_used_mb, e.created_at, "
            "e.last_action, e.last_action_status, e.last_action_at, e.last_action_detail, e.last_action_username "
            "FROM emsbox e LEFT JOIN localities l ON l.id = e.locality_id "
            "WHERE e.status != 'disabled' ORDER BY e.id")
        ann = await conn.fetch(
            "SELECT fingerprint, private_ip, public_ip, agent_version, hw, first_seen, last_seen "
            "FROM emsbox_announce WHERE last_seen > now() - interval '10 minutes' ORDER BY last_seen DESC")
    def iso(d, keys):
        for k in keys:
            if d.get(k):
                d[k] = d[k].isoformat()
        return d
    unp = []
    for r in ann:
        d = iso(dict(r), ("first_seen", "last_seen"))
        if isinstance(d.get("hw"), str):
            try:
                d["hw"] = json.loads(d["hw"])
            except Exception:
                d["hw"] = {}
        unp.append(d)
    return {"boxes": [iso(dict(r), ("last_heartbeat", "last_ingest", "created_at")) for r in boxes],
            "unpaired": unp}


async def _finish_action(conn, box_id: int, ok: bool, detail: str) -> None:
    st = "done" if ok else "failed"
    await conn.execute(
        "UPDATE emsbox SET last_action_status = $2, last_action_at = now(), last_action_detail = $3 "
        "WHERE id = $1", box_id, st, detail)
    await conn.execute(
        """UPDATE emsbox_action_log SET status = $2, detail = $3, updated_at = now()
           WHERE id = (SELECT id FROM emsbox_action_log
                       WHERE box_id = $1 AND status IN ('pending','delivered') ORDER BY id DESC LIMIT 1)""",
        box_id, st, detail)


async def finish_console(box_id: int, connected: bool, dur_s: int) -> None:
    """Uzavře stavový řádek servisní konzole (jinak by visel na 'provádí se…')."""
    st = "done" if connected else "failed"
    detail = (f"konzole ukončena ({dur_s} s)" if connected else "box se nepřipojil")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE emsbox SET last_action_status = $2, last_action_at = now(), last_action_detail = $3 "
            "WHERE id = $1 AND last_action LIKE 'open_console%'", box_id, st, detail)
        await conn.execute(
            """UPDATE emsbox_action_log SET status = $2, detail = $3, updated_at = now()
               WHERE id = (SELECT id FROM emsbox_action_log
                           WHERE box_id = $1 AND action LIKE 'open_console%'
                             AND status IN ('pending','delivered') ORDER BY id DESC LIMIT 1)""",
            box_id, st, detail)


async def action_log(box_id: int, limit: int = 30) -> list[dict]:
    """📜 Historie servisních akcí boxu (kdo, co, kdy, výsledek)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, action, username, status, detail, created_at, updated_at "
            "FROM emsbox_action_log WHERE box_id = $1 ORDER BY id DESC LIMIT $2", box_id, limit)
    out = []
    for r in rows:
        d = dict(r)
        for k in ("created_at", "updated_at"):
            d[k] = d[k].isoformat() if d[k] else None
        out.append(d)
    return out


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
            "private_ip = COALESCE($7, private_ip), public_ip = COALESCE($8, public_ip), "
            "hostname = COALESCE($9, hostname), wifi_ssid = $10, wifi_psk = $11, "
            "disk_total_mb = COALESCE($12, disk_total_mb), disk_free_mb = COALESCE($13, disk_free_mb), "
            "mem_total_mb = COALESCE($14, mem_total_mb), mem_used_mb = COALESCE($15, mem_used_mb), "
            "uptime_s = COALESCE($16, uptime_s), last_heartbeat_body = $17, "
            "buffer_peak_rows = GREATEST(COALESCE(buffer_peak_rows, 0), COALESCE($2, 0)), "
            "status = CASE WHEN status = 'offline' THEN 'online' ELSE status END WHERE id = $1",
            box_id, body.get("buffer_rows"),
            datetime.fromisoformat(body["buffer_oldest_ts"].replace("Z", "+00:00")) if body.get("buffer_oldest_ts") else None,
            drift, json.dumps(body.get("devices") or []), body.get("agent_version"),
            body.get("private_ip"), body.get("_public_ip"),
            body.get("hostname"), body.get("wifi_ssid"), body.get("wifi_psk"),
            body.get("disk_total_mb"), body.get("disk_free_mb"),
            body.get("mem_total_mb"), body.get("mem_used_mb"),
            body.get("uptime_s"),
            json.dumps({k: v for k, v in body.items() if k not in ("action_result", "wifi_psk")}, default=str))
        if (body.get("buffer_rows") or 0) > 0:      # vrchol bufferu do otevřené epizody
            await conn.execute(
                "UPDATE emsbox_buffer_episodes SET peak_buffer_rows = GREATEST(peak_buffer_rows, $2) "
                "WHERE box_id = $1 AND ended_at IS NULL", box_id, int(body["buffer_rows"]))
        # --- životní cyklus servisních akcí ---
        ar = body.get("action_result")
        if isinstance(ar, dict) and ar.get("action"):
            await _finish_action(conn, box_id, bool(ar.get("ok")), str(ar.get("detail") or ar["action"]))
        else:
            row = await conn.fetchrow(
                "SELECT last_action, last_action_status, last_action_detail FROM emsbox WHERE id = $1", box_id)
            if (row and row["last_action"] == "update_agent" and row["last_action_status"] == "delivered"
                    and body.get("agent_version") and body["agent_version"] != row["last_action_detail"]):
                await _finish_action(conn, box_id, True,
                                     f"verze {row['last_action_detail'] or '?'} → {body['agent_version']}")


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


async def box_detail(box_id: int, include_actions: bool) -> dict | None:
    """🔎 Vše, co o boxu víme: identita, HW, poslední heartbeat, moduly, epizody bufferování,
    statistika syncu (24 h / 7 d / 30 d), alertové události, servisní akce (admin)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        box = await conn.fetchrow(
            "SELECT e.*, l.name AS locality_name FROM emsbox e LEFT JOIN localities l ON l.id = e.locality_id "
            "WHERE e.id = $1", box_id)
        if not box:
            return None
        mods = await conn.fetch(
            "SELECT id, name, adapter, device_type, transport_params FROM modules WHERE emsbox_id = $1 ORDER BY id",
            box_id)
        eps = await conn.fetch(
            "SELECT id, data_from, detected_at, ended_at, batches, rows_total, rows_accepted, rows_dup, "
            "peak_buffer_rows FROM emsbox_buffer_episodes WHERE box_id = $1 ORDER BY id DESC LIMIT 100", box_id)
        stats = {}
        for key, days in (("24h", 1), ("7d", 7), ("30d", 30), ("90d", 90)):
            r = await conn.fetchrow(
                "SELECT COALESCE(SUM(batches),0) AS batches, COALESCE(SUM(rows_total),0) AS rows_total, "
                "COALESCE(SUM(rows_accepted),0) AS rows_accepted, COALESCE(SUM(rows_dup),0) AS rows_dup, "
                "COALESCE(SUM(backfill_batches),0) AS backfill_batches, COALESCE(SUM(backfill_rows),0) AS backfill_rows, "
                "COALESCE(MAX(max_lag_s),0) AS max_lag_s, COUNT(*) AS hours "
                "FROM emsbox_sync_hourly WHERE box_id = $1 AND hour >= now() - interval '%s days'" % days, box_id)
            stats[key] = dict(r)
        hourly = await conn.fetch(
            "SELECT hour, batches, rows_total, rows_accepted, backfill_rows, max_lag_s FROM emsbox_sync_hourly "
            "WHERE box_id = $1 AND hour >= now() - interval '7 days' ORDER BY hour", box_id)
        ep_sum = await conn.fetchrow(
            "SELECT COUNT(*) AS n, COALESCE(SUM(rows_accepted),0) AS rows_accepted, "
            "COALESCE(SUM(EXTRACT(EPOCH FROM (detected_at - data_from))),0) AS offline_s, "
            "MIN(detected_at) AS since FROM emsbox_buffer_episodes WHERE box_id = $1", box_id)
        alerts = await conn.fetch(
            "SELECT ev.id, r.kind, ev.opened_at, ev.closed_at, ev.detail FROM alert_events ev "
            "JOIN alert_rules r ON r.id = ev.rule_id WHERE r.scope = 'emsbox' AND r.target_id = $1 "
            "ORDER BY ev.id DESC LIMIT 30", box_id)
        first_sync = await conn.fetchval(
            "SELECT MIN(hour) FROM emsbox_sync_hourly WHERE box_id = $1", box_id)

    def iso(v):
        return v.isoformat() if isinstance(v, datetime) else v

    def jl(v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    b = {k: iso(v) for k, v in dict(box).items() if k != "token_hash"}
    for k in ("hw_info", "heartbeat_devices", "last_heartbeat_body"):
        b[k] = jl(b.get(k))
    out = {
        "box": b,
        "modules": [{**dict(m), "transport_params": jl(m["transport_params"])} for m in mods],
        "episodes": [{k: iso(v) for k, v in dict(e).items()} for e in eps],
        "episodes_summary": {k: iso(v) for k, v in dict(ep_sum).items()},
        "sync_stats": stats,
        "sync_hourly": [{k: iso(v) for k, v in dict(h).items()} for h in hourly],
        "sync_since": iso(first_sync),
        "alerts": [{**{k: iso(v) for k, v in dict(a).items()}, "detail": jl(a["detail"])} for a in alerts],
        "actions": await action_log(box_id, 50) if include_actions else None,
    }
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


async def set_pending_action(box_id: int, action: str | None, username: str | None = None) -> bool:
    """Servisní akce pro box (vyzvedne si ji heartbeatem). None = zrušit.
    Zakládá i stavový řádek životního cyklu: pending → delivered → done/failed.
    U update_agent se do detail uloží AKTUÁLNÍ verze (pro pozdější porovnání)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if action is None:
            r = await conn.execute("UPDATE emsbox SET pending_action = NULL WHERE id = $1", box_id)
            return r.endswith("1")
        detail = None
        if action == "update_agent":
            detail = await conn.fetchval("SELECT agent_version FROM emsbox WHERE id = $1", box_id)
        r = await conn.execute(
            "UPDATE emsbox SET pending_action = $2, last_action = $2, last_action_status = 'pending', "
            "last_action_at = now(), last_action_detail = $3, last_action_username = $4 "
            "WHERE id = $1", box_id, action, detail, username)
        if r.endswith("1"):
            await conn.execute(
                "INSERT INTO emsbox_action_log (box_id, action, username, status, detail) "
                "VALUES ($1, $2, $3, 'pending', $4)", box_id, action, username, detail)
            return True
        return False


async def pop_pending_action(box_id: int) -> str | None:
    """Atomicky vrátí a smaže čekající akci (doručení právě jednou) — čitelná transakce."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            val = await conn.fetchval(
                "SELECT pending_action FROM emsbox WHERE id = $1 FOR UPDATE", box_id)
            if val:
                await conn.execute(
                    "UPDATE emsbox SET pending_action = NULL, last_action_status = 'delivered', "
                    "last_action_at = now() WHERE id = $1", box_id)
                await conn.execute(
                    """UPDATE emsbox_action_log SET status = 'delivered', updated_at = now()
                       WHERE id = (SELECT id FROM emsbox_action_log
                                   WHERE box_id = $1 AND status = 'pending' ORDER BY id DESC LIMIT 1)""",
                    box_id)
    return val
