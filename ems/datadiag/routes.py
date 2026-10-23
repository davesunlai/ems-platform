"""📚 Datová diagnostika portálu: velikosti DB, hypertable samples (chunky, komprese, retence),
continuous aggregate samples_15m, úlohy Timescale (poslední běh / výsledek / další start),
řádky za 24 h po metrikách, zařízení bez čerstvých dat. Admin."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from ems.api.db import get_pool
from ems.auth.deps import require_permission

logger = logging.getLogger("ems.datadiag")
router = APIRouter(prefix="/api/admin/data-diag", tags=["datadiag"])


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else (str(v) if v is not None and not isinstance(v, (int, float, str, bool)) else v)


async def _q(conn, sql, *args, one=False):
    try:
        if one:
            r = await conn.fetchrow(sql, *args)
            return {k: _iso(v) for k, v in dict(r).items()} if r else None
        return [{k: _iso(v) for k, v in dict(r).items()} for r in await conn.fetch(sql, *args)]
    except Exception as exc:
        logger.debug("datadiag %s: %s", sql[:40], exc)
        return {"error": str(exc).splitlines()[0]} if one else []


@router.get("")
async def data_diag(_: dict = Depends(require_permission("admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        sizes = await _q(conn, """
            SELECT pg_database_size('ems') AS db_bytes,
                   hypertable_size('samples') AS samples_bytes,
                   (SELECT hypertable_size(format('%I.%I', materialization_hypertable_schema, materialization_hypertable_name)::regclass)
                      FROM timescaledb_information.continuous_aggregates WHERE view_name='samples_15m') AS agg_bytes,
                   (SELECT extversion FROM pg_extension WHERE extname='timescaledb') AS timescale,
                   version() AS postgres""", one=True)
        comp = await _q(conn, """
            SELECT before_compression_total_bytes AS before_bytes, after_compression_total_bytes AS after_bytes,
                   number_compressed_chunks AS compressed_chunks, total_chunks
            FROM hypertable_compression_stats('samples')""", one=True)
        chunks = await _q(conn, """
            SELECT chunk_name, range_start, range_end, is_compressed,
                   pg_size_pretty(pg_total_relation_size(format('%I.%I', chunk_schema, chunk_name))) AS size,
                   pg_total_relation_size(format('%I.%I', chunk_schema, chunk_name)) AS bytes
            FROM timescaledb_information.chunks WHERE hypertable_name='samples' ORDER BY range_start""")
        raw_range = await _q(conn, "SELECT min(time) AS raw_from, max(time) AS raw_to FROM samples", one=True)
        agg_range = await _q(conn, "SELECT min(bucket) AS agg_from, max(bucket) AS agg_to, count(*) AS rows FROM samples_15m", one=True)
        jobs = await _q(conn, """
            SELECT j.job_id, j.proc_name, j.hypertable_name, j.schedule_interval::text AS schedule, j.config::text AS config,
                   s.last_run_started_at, s.last_run_status, s.last_run_duration::text AS last_run_duration,
                   s.next_start, s.total_runs, s.total_failures
            FROM timescaledb_information.jobs j LEFT JOIN timescaledb_information.job_stats s USING (job_id)
            WHERE j.proc_name NOT LIKE 'policy_telemetry%' ORDER BY j.job_id""")
        per_metric = await _q(conn, """
            SELECT metric, count(*) AS rows_24h, count(DISTINCT device_id) AS devices
            FROM samples WHERE time > now() - interval '24 hours' GROUP BY metric ORDER BY rows_24h DESC""")
        per_device = await _q(conn, """
            SELECT m.id AS device_id, m.name, m.adapter, m.emsbox_id, l.name AS locality,
                   (SELECT max(time) FROM samples s WHERE s.device_id = m.id) AS last_sample,
                   (SELECT count(*) FROM samples s WHERE s.device_id = m.id AND time > now() - interval '24 hours') AS rows_24h
            FROM modules m LEFT JOIN localities l ON l.id = m.locality_id ORDER BY m.id""")
        tables = await _q(conn, """
            SELECT relname AS table, pg_total_relation_size(c.oid) AS bytes, pg_size_pretty(pg_total_relation_size(c.oid)) AS size
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r','m') AND relname NOT LIKE '_hyper%'
            ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 25""")
        spot = await _q(conn, "SELECT min(slot) AS spot_from, max(slot) AS spot_to, count(*) AS slots FROM spot_history", one=True)
    rows_24h = sum(int(r.get("rows_24h") or 0) for r in per_metric) if isinstance(per_metric, list) else 0
    return {"generated_at": datetime.utcnow().isoformat() + "Z", "sizes": sizes, "compression": comp,
            "chunks": chunks, "raw_range": raw_range, "agg_range": agg_range, "jobs": jobs,
            "per_metric": per_metric, "per_device": per_device, "tables": tables, "spot": spot,
            "rows_24h": rows_24h, "est_month_bytes_raw": None}
