"""Měsíční energetické bilance lokality (kWh) z výkonových vzorků.

Energie ≈ Σ (hodinový průměr výkonu × 1 h). Čistý výkon sítě = součet grid_power
přes zařízení. Konvence EMS (shodná se souhrnem dashboardu): **grid_power
+ = odběr ZE sítě (import), − = dodávka DO sítě (export)**.
"""
from __future__ import annotations

from datetime import date

from ems.api.db import get_pool

# Hodinová energie sítě (kWh) + hodinová spot cena (CZK/MWh) — cenu aplikuje Python
# přes pricing.cost.price_czk_kwh (JEDEN cenový model, shodný s plánovačem: přirážka,
# distribuce VT/NT, poplatky u nákupu; provize odečtená u prodeje).
_HOURLY_GRID_SPOT_SQL = """
WITH gh AS (
    SELECT h, sum(p) / 1000.0 AS np_kwh FROM (
        SELECT time_bucket('1 hour', time) AS h, device_id, avg(value) AS p
        FROM samples
        WHERE device_id = ANY($1::text[]) AND metric = 'grid_power'
          AND time >= $2 AND time < $3
        GROUP BY 1, device_id
    ) x GROUP BY h
), sp AS (
    SELECT time_bucket('1 hour', slot) AS h, avg(price) AS czk_mwh
    FROM spot_history WHERE slot >= $2 AND slot < $3 GROUP BY 1
)
SELECT gh.h AS h, to_char(date_trunc('month', gh.h), 'YYYY-MM') AS m,
       gh.np_kwh AS np_kwh, sp.czk_mwh AS czk_mwh
FROM gh LEFT JOIN sp ON sp.h = gh.h
ORDER BY gh.h
"""


async def hourly_grid_spot(device_ids: list[str], start: date, end: date) -> list[dict]:
    """Hodinové řádky: {h, m, np_kwh (+odběr/−dodávka), czk_mwh}."""
    if not device_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_HOURLY_GRID_SPOT_SQL, device_ids, start, end)
    return [dict(r) for r in rows]


async def monthly_cost(device_ids: list[str], tariff: dict | None,
                       start: date, end: date) -> dict[str, dict]:
    """Cena importu/exportu po měsících DLE SAZEBNÍKU lokality (ne holý spot).

    Import se počítá cenou nákupu (spot + přirážka + distribuce[VT/NT] + poplatky),
    export cenou prodeje (spot − provize) — tedy tím, co reálně platíš/dostáváš.
    """
    from ems.pricing import cost as pricing_cost

    out: dict[str, dict] = {}
    for r in await hourly_grid_spot(device_ids, start, end):
        m = r["m"]
        d = out.setdefault(m, {"import_czk": 0.0, "export_czk": 0.0})
        np_kwh = float(r["np_kwh"] or 0.0)
        price = pricing_cost.price_czk_kwh(tariff, r["h"], r["czk_mwh"])
        if np_kwh > 0:
            d["import_czk"] += np_kwh * price["import_czk"]
        else:
            d["export_czk"] += (-np_kwh) * price["export_czk"]
    return out


async def monthly_spot_cost(device_ids: list[str], start: date, end: date) -> dict[str, dict]:
    """ZASTARALÉ: holý spot bez sazebníku. Ponecháno pro srovnání/diagnostiku."""
    return await monthly_cost(device_ids, None, start, end)

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
       sum(greatest(0, -np)) / 1000.0 AS export_kwh,
       sum(greatest(0,  np)) / 1000.0 AS import_kwh
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

# Výroba z vlastního DENNÍHO počítadla měniče (energy_today): max za pražský den
# = denní výroba; součet přes měsíc. Odolné proti výpadkům kolektoru.
_PROD_TODAY_SQL = """
SELECT to_char(date_trunc('month', day), 'YYYY-MM') AS m, sum(day_kwh) AS kwh FROM (
    SELECT device_id,
           date_trunc('day', time AT TIME ZONE 'Europe/Prague') AS day,
           max(value) AS day_kwh
    FROM samples
    WHERE device_id = ANY($1::text[]) AND metric = 'energy_today'
      AND time >= $2 AND time < $3
    GROUP BY device_id, day
) t GROUP BY 1
"""


async def monthly_energy(device_ids: list[str], start: date, end: date) -> list[dict]:
    if not device_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        grid = await conn.fetch(_GRID_SQL, device_ids, start, end)
        pv = await conn.fetch(_METRIC_SQL, device_ids, start, end, "pv_power")
        prod_cnt = await conn.fetch(_PROD_TODAY_SQL, device_ids, start, end)
        load = await conn.fetch(_METRIC_SQL, device_ids, start, end, "load_power")
        bat = await conn.fetch(_METRIC_SQL, device_ids, start, end, "battery_power")

    months: dict[str, dict] = {}
    for r in grid:
        months.setdefault(r["m"], {}).update(
            export_kwh=float(r["export_kwh"] or 0), import_kwh=float(r["import_kwh"] or 0))
    for r in pv:
        months.setdefault(r["m"], {})["pv_int_kwh"] = float(r["kwh"] or 0)
    for r in prod_cnt:
        months.setdefault(r["m"], {})["prod_cnt_kwh"] = float(r["kwh"] or 0)
    for r in load:
        months.setdefault(r["m"], {})["load_kwh"] = float(r["kwh"] or 0)
    for r in bat:
        months.setdefault(r["m"], {})["bat_net_kwh"] = float(r["kwh"] or 0)

    out = []
    for m in sorted(months):
        d = months[m]
        # Výroba: přednost vlastní počítadlo měniče (energy_today), jinak integrace pv_power.
        prod = d.get("prod_cnt_kwh", 0.0) or d.get("pv_int_kwh", 0.0)
        imp = d.get("import_kwh", 0.0)
        exp = d.get("export_kwh", 0.0)
        # Spotřeba: přímé load_power (goodwe), jinak bilance FVE+import−export−Δbaterie.
        load_kwh = d.get("load_kwh", 0.0)
        cons = load_kwh if load_kwh > 0 else max(0.0, prod + imp - exp - d.get("bat_net_kwh", 0.0))
        out.append({"month": m,
                    "prod_kwh": round(prod, 1),
                    "cons_kwh": round(cons, 1),
                    "export_kwh": round(exp, 1),
                    "import_kwh": round(imp, 1)})
    return out


async def period_export_kwh(device_ids: list[str], start: date, end: date) -> float:
    """Jen přetoky (export) za období — pro kontrolu limitu."""
    rows = await monthly_energy(device_ids, start, end)
    return round(sum(r["export_kwh"] for r in rows), 1)


async def spot_cost_total(device_ids: list[str], start: date, end: date,
                          tariff: dict | None = None) -> dict:
    """Cena importu/exportu za celé období dle sazebníku (součet měsíců) — pro souhrn."""
    m = await monthly_cost(device_ids, tariff, start, end)
    return {"import_czk": round(sum(v["import_czk"] for v in m.values()), 2),
            "export_czk": round(sum(v["export_czk"] for v in m.values()), 2)}


_TODAY_GRID_SPOT_SQL = """
WITH gh AS (
    SELECT h, sum(p) / 1000.0 AS np_kwh FROM (
        SELECT time_bucket('1 hour', time) AS h, device_id, avg(value) AS p
        FROM samples
        WHERE device_id = ANY($1::text[]) AND metric = 'grid_power'
          AND time >= date_trunc('day', now() AT TIME ZONE 'Europe/Prague') AT TIME ZONE 'Europe/Prague'
        GROUP BY 1, device_id
    ) x GROUP BY h
), sp AS (
    SELECT time_bucket('1 hour', slot) AS h, avg(price) AS czk_mwh
    FROM spot_history
    WHERE slot >= date_trunc('day', now() AT TIME ZONE 'Europe/Prague') AT TIME ZONE 'Europe/Prague'
    GROUP BY 1
)
SELECT gh.h AS h, gh.np_kwh AS np_kwh, sp.czk_mwh AS czk_mwh
FROM gh LEFT JOIN sp ON sp.h = gh.h
"""


async def today_spot_cost(device_ids: list[str], tariff: dict | None = None) -> dict:
    """Dnešní cena import/export přes PRAŽSKÝ den dle sazebníku (shodně s kWh v souhrnu)."""
    if not device_ids:
        return {"import_czk": 0.0, "export_czk": 0.0}
    from ems.pricing import cost as pricing_cost

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_TODAY_GRID_SPOT_SQL, device_ids)
    imp = exp = 0.0
    for r in rows:
        np_kwh = float(r["np_kwh"] or 0.0)
        price = pricing_cost.price_czk_kwh(tariff, r["h"], r["czk_mwh"])
        if np_kwh > 0:
            imp += np_kwh * price["import_czk"]
        else:
            exp += (-np_kwh) * price["export_czk"]
    return {"import_czk": round(imp, 2), "export_czk": round(exp, 2)}
