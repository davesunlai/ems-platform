"""ev_telemetry (hypertable, snapshoty 10–30 s), ev_sessions (edge detektor na car), ev_daily (CAGG z eto).
Vzor hp_telemetry / hp_runs (GOE-ADAPTER-BRIEF §2)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Prague")

from ems.api.db import get_pool

_COLS = ("car", "allowed", "amp_set", "amp_max", "amp_allowed", "phase_mode", "force", "logic_mode",
         "model_status", "error", "u_l1", "u_l2", "u_l3", "i_l1", "i_l2", "i_l3", "p_l1", "p_l2", "p_l3",
         "power_w", "energy_total_wh", "session_wh", "transaction", "phases_active", "temp_c", "uptime_ms")


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ev_telemetry (
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                module_id TEXT NOT NULL,
                car SMALLINT, allowed BOOLEAN, amp_set SMALLINT, amp_max SMALLINT, amp_allowed SMALLINT,
                phase_mode SMALLINT, force SMALLINT, logic_mode SMALLINT, model_status SMALLINT, error SMALLINT,
                u_l1 REAL, u_l2 REAL, u_l3 REAL, i_l1 REAL, i_l2 REAL, i_l3 REAL, p_l1 REAL, p_l2 REAL, p_l3 REAL,
                power_w REAL, energy_total_wh DOUBLE PRECISION, session_wh DOUBLE PRECISION,
                transaction SMALLINT, phases_active SMALLINT, temp_c REAL, uptime_ms BIGINT
            )""")
        try:
            await conn.execute("SELECT create_hypertable('ev_telemetry', 'ts', if_not_exists => TRUE)")
        except Exception:
            pass
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_tel_mod_ts ON ev_telemetry (module_id, ts DESC)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ev_sessions (
                id SERIAL PRIMARY KEY,
                module_id TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL,
                ended_at TIMESTAMPTZ,
                charging_s INTEGER NOT NULL DEFAULT 0,      -- sekundy ve stavu car=2
                wh DOUBLE PRECISION,                         -- nabito (z wh na konci / max)
                wh_max DOUBLE PRECISION NOT NULL DEFAULT 0,
                eto_start DOUBLE PRECISION,                  -- čítač celkem na začátku (kontrola)
                max_power_w REAL NOT NULL DEFAULT 0,
                phases SMALLINT,                             -- max pnp během relace
                grid_kwh DOUBLE PRECISION NOT NULL DEFAULT 0,  -- část energie ze sítě (dle bilance v čase)
                pv_kwh DOUBLE PRECISION NOT NULL DEFAULT 0,    -- část z FVE/baterie
                cost_czk DOUBLE PRECISION NOT NULL DEFAULT 0,  -- Σ grid_kwh × efektivní cena importu
                last_model_status SMALLINT,
                ended_reason TEXT                            -- unplugged | complete | error
            )""")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_sess_mod_start ON ev_sessions (module_id, started_at DESC)")
        # denní agregát z eto (monotónní čítač; reset ošetřen v dotazu daily())
        try:
            await conn.execute("""
                CREATE MATERIALIZED VIEW IF NOT EXISTS ev_daily
                WITH (timescaledb.continuous) AS
                SELECT time_bucket('1 day', ts, 'Europe/Prague') AS day, module_id,
                       min(energy_total_wh) AS eto_min, max(energy_total_wh) AS eto_max,
                       max(power_w) AS max_power_w,
                       count(*) FILTER (WHERE car = 2) AS charging_samples
                FROM ev_telemetry GROUP BY 1, 2 WITH NO DATA""")
            await conn.execute("""
                SELECT add_continuous_aggregate_policy('ev_daily', start_offset => INTERVAL '3 days',
                    end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE)""")
        except Exception:
            pass


async def insert(module_id: str, d: dict) -> None:
    pool = await get_pool()
    cols = ", ".join(_COLS)
    ph = ", ".join(f"${i + 2}" for i in range(len(_COLS)))
    vals = []
    for c in _COLS:
        v = d.get(c)
        if c in ("car", "amp_set", "amp_max", "amp_allowed", "phase_mode", "force", "logic_mode",
                 "model_status", "error", "transaction", "phases_active") and v is not None:
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = None
        vals.append(v)
    async with pool.acquire() as conn:
        await conn.execute(f"INSERT INTO ev_telemetry (module_id, {cols}) VALUES ($1, {ph})", module_id, *vals)


async def latest_for_modules(module_ids: list[str]) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ev_telemetry WHERE module_id = ANY($1::text[]) ORDER BY ts DESC LIMIT 1", module_ids)
    return dict(row) if row else None


async def sessions(module_ids: list[str], limit: int = 50, start: datetime | None = None,
                   end: datetime | None = None) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if start and end:
            rows = await conn.fetch(
                "SELECT * FROM ev_sessions WHERE module_id = ANY($1::text[]) AND started_at >= $3 AND started_at < $4 "
                "ORDER BY started_at DESC LIMIT $2", module_ids, limit, start, end)
        else:
            rows = await conn.fetch(
                "SELECT * FROM ev_sessions WHERE module_id = ANY($1::text[]) ORDER BY started_at DESC LIMIT $2",
                module_ids, limit)
    out = []
    for r in rows:
        d = dict(r)
        for k in ("started_at", "ended_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


async def daily(module_ids: list[str], start: datetime, end: datetime, live: bool = False) -> list[dict]:
    """kWh/den z delty eto (reset čítače → bere jen kladné přírůstky mezi dny).
    live=True počítá přímo z ev_telemetry (včetně dneška, bez zpoždění agregátu) — pro měsíční pohled."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if live:
            rows = await conn.fetch(
                """SELECT time_bucket('1 day', ts, 'Europe/Prague') AS day, module_id,
                          min(energy_total_wh) AS eto_min, max(energy_total_wh) AS eto_max, max(power_w) AS max_power_w,
                          count(*) FILTER (WHERE car = 2) AS charging_samples
                   FROM ev_telemetry WHERE module_id = ANY($1::text[]) AND ts >= $2 AND ts < $3
                   GROUP BY 1, 2 ORDER BY 1, 2""", module_ids, start, end)
        else:
            rows = await conn.fetch(
                """SELECT day, module_id, eto_min, eto_max, max_power_w, charging_samples
                   FROM ev_daily WHERE module_id = ANY($1::text[]) AND day >= $2 AND day < $3 ORDER BY day, module_id""",
                module_ids, start, end)
    out, prev_max = [], {}
    for r in rows:
        m = r["module_id"]
        pm = prev_max.get(m)
        base = pm if (pm is not None and r["eto_min"] is not None and r["eto_min"] >= pm) else r["eto_min"]
        kwh = max(0.0, float((r["eto_max"] or 0) - (base or 0))) / 1000.0
        prev_max[m] = r["eto_max"]
        day_local = r["day"].astimezone(_TZ).date() if r["day"].tzinfo else r["day"].date()   # bucket = pražská půlnoc (23:00 UTC!) → datum v Praze
        out.append({"day": day_local.isoformat(), "module_id": m, "kwh": round(kwh, 2),
                    "max_power_kw": round(float(r["max_power_w"] or 0) / 1000.0, 1),
                    "charging_min": None if r["charging_samples"] is None else int(r["charging_samples"]) })
    return out


async def status_timeline(module_id: str, hours: int = 24) -> list[dict]:
    """Změny modelStatus / car / force v čase (jen hrany) — diagnostika „proč (ne)nabíjí"."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """WITH t AS (
                 SELECT ts, car, model_status, force, phase_mode, amp_set, amp_allowed, power_w, error,
                        lag(car) OVER w AS pcar, lag(model_status) OVER w AS pms, lag(force) OVER w AS pfrc,
                        lag(phase_mode) OVER w AS ppsm, lag(amp_set) OVER w AS pamp, lag(error) OVER w AS perr
                 FROM ev_telemetry WHERE module_id=$1 AND ts > now() - make_interval(hours => $2)
                 WINDOW w AS (ORDER BY ts))
               SELECT ts, car, model_status, force, phase_mode, amp_set, amp_allowed, power_w, error
               FROM t WHERE pcar IS NULL OR car IS DISTINCT FROM pcar OR model_status IS DISTINCT FROM pms
                  OR force IS DISTINCT FROM pfrc OR phase_mode IS DISTINCT FROM ppsm OR amp_set IS DISTINCT FROM pamp
                  OR error IS DISTINCT FROM perr
               ORDER BY ts DESC LIMIT 200""", module_id, hours)
    return [{**dict(r), "ts": r["ts"].isoformat()} for r in rows]


async def series(module_ids: list[str], hours: int = 24) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT time_bucket('1 minute', ts) AS t, avg(power_w) AS power_w, max(car) AS car,
                      max(amp_set) AS amp_set, max(amp_allowed) AS amp_allowed, max(phases_active) AS pnp
               FROM ev_telemetry WHERE module_id = ANY($1::text[]) AND ts > now() - make_interval(hours => $2)
               GROUP BY 1 ORDER BY 1""", module_ids, hours)
    return [{"ts": r["t"].isoformat(), "power_w": r["power_w"], "car": r["car"], "amp_set": r["amp_set"],
             "amp_allowed": r["amp_allowed"], "pnp": r["pnp"]} for r in rows]
