"""Měsíční energetické bilance lokality (kWh) z výkonových vzorků.

Energie ≈ Σ (hodinový průměr výkonu × 1 h). Přetoky/odběr z čisté výkonu sítě
(součet grid_power přes zařízení): znaménko: kladný grid_power = dodávka do sítě (export), záporný = odběr (import).
"""
from __future__ import annotations

from datetime import date

from ems.api.db import get_pool

_GRID_SQL = """
WITH hourly AS (
    SELECT time_bucket('1 hour', time) AS h, device_id, avg(value) AS p
    FROM samples
    WHERE device_id = ANY($1::text[]) AND metric = 'grid_power'
      AND time >= $2 AND time < $3
    GROUP BY h, device_id
), net AS (
    SELECT h, sum(p) AS np FROM hourly GROUP BY h
)
SELECT to_char(date_trunc('month', h), 'YYYY-MM') AS m,
       sum(greatest(0,  np)) / 1000.0 AS export_kwh,
       sum(greatest(0, -np)) / 1000.0 AS import_kwh
FROM net GROUP BY 1
"""

_METRIC_SQL = """
WITH hourly AS (
    SELECT h, sum(dev) AS p FROM (
        SELECT time_bucket('1 hour', time) AS h, device_id, avg(value) AS dev
        FROM samples
        WHERE device_id = ANY($1::text[]) AND metric = $4
          AND time >= $2 AND time < $3
        GROUP BY h, device_id
    ) x GROUP BY h
)
SELECT to_char(date_trunc('month', h), 'YYYY-MM') AS m, sum(p) / 1000.0 AS kwh
FROM hourly GROUP BY 1
"""


async def monthly_energy(device_ids: list[str], start: date, end: date) -> list[dict]:
    if not device_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        grid = await conn.fetch(_GRID_SQL, device_ids, start, end)
        pv = await conn.fetch(_METRIC_SQL, device_ids, start, end, "pv_power")
        load = await conn.fetch(_METRIC_SQL, device_ids, start, end, "load_power")

    months: dict[str, dict] = {}
    for r in grid:
        months.setdefault(r["m"], {}).update(
            export_kwh=float(r["export_kwh"] or 0), import_kwh=float(r["import_kwh"] or 0))
    for r in pv:
        months.setdefault(r["m"], {})["prod_kwh"] = float(r["kwh"] or 0)
    for r in load:
        months.setdefault(r["m"], {})["cons_kwh"] = float(r["kwh"] or 0)

    out = []
    for m in sorted(months):
        d = months[m]
        out.append({"month": m,
                    "prod_kwh": round(d.get("prod_kwh", 0.0), 1),
                    "cons_kwh": round(d.get("cons_kwh", 0.0), 1),
                    "export_kwh": round(d.get("export_kwh", 0.0), 1),
                    "import_kwh": round(d.get("import_kwh", 0.0), 1)})
    return out


async def period_export_kwh(device_ids: list[str], start: date, end: date) -> float:
    """Jen přetoky (export) za období — pro kontrolu limitu."""
    rows = await monthly_energy(device_ids, start, end)
    return round(sum(r["export_kwh"] for r in rows), 1)
