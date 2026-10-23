"""Měsíční energetické bilance lokality (kWh) z výkonových vzorků.

Energie ≈ Σ (hodinový průměr výkonu × 1 h). Čistý výkon sítě = součet grid_power
přes zařízení. Konvence EMS (shodná se souhrnem dashboardu): **grid_power
+ = odběr ZE sítě (import), − = dodávka DO sítě (export)**.
"""
from __future__ import annotations

from datetime import date

from ems.api.db import get_pool

# 15minutová energie sítě (kWh) + spot cena slotu (CZK/MWh) — cenu aplikuje Python
# přes pricing.cost.price_czk_kwh (JEDEN cenový model, shodný s plánovačem: přirážka,
# distribuce VT/NT, poplatky u nákupu; provize odečtená u prodeje).
# v0.99.0: dřív hodinové koše — v rámci hodiny se odběr a dodávka vzájemně odečítaly
# (dopoledne export, pak odběr → „nic“), což podhodnocovalo obojí. 15 min = zúčtovací
# interval distributora i granularita spotu, takže se počítá přesně to, co fakturuje.
# v1.0.0: čte z continuous aggregate samples_15m (materializované 15min koše, realtime okraj),
# n = počet surových vzorků ve slotu (pokrytí; plný slot ≈ 30–90 podle periody čtení).
_Q15_GRID_SPOT_SQL = """
WITH gq AS (
    SELECT bucket AS q, sum(avg) * 0.25 / 1000.0 AS np_kwh, min(n) AS n
    FROM samples_15m
    WHERE device_id = ANY($1::text[]) AND metric = 'grid_power'
      AND bucket >= $2 AND bucket < $3
    GROUP BY bucket
), sp AS (
    SELECT time_bucket('15 minutes', slot) AS q, avg(price) AS czk_mwh
    FROM spot_history WHERE slot >= $2 AND slot < $3 GROUP BY 1
)
SELECT gq.q AS h, to_char(date_trunc('month', gq.q), 'YYYY-MM') AS m,
       gq.np_kwh AS np_kwh, sp.czk_mwh AS czk_mwh, gq.n AS n
FROM gq LEFT JOIN sp ON sp.q = gq.q
ORDER BY gq.q
"""


async def hourly_grid_spot(device_ids: list[str], start: date, end: date) -> list[dict]:
    """15min řádky (název zachován kvůli volajícím): {h = začátek slotu, m, np_kwh (+odběr/−dodávka), czk_mwh}."""
    if not device_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_Q15_GRID_SPOT_SQL, device_ids, start, end)
    return [dict(r) for r in rows]


def cost_bucket() -> dict:
    """Prázdný akumulátor nákladů (měsíc/den): kWh, Kč dle sazebníku, Kč jen za holý spot."""
    return {"import_kwh": 0.0, "export_kwh": 0.0, "import_czk": 0.0, "export_czk": 0.0,
            "import_spot_czk": 0.0, "export_spot_czk": 0.0, "slots_no_spot": 0}


def accumulate(d: dict, np_kwh: float, price: dict, czk_mwh) -> None:
    """Přičte jeden 15min slot: kWh, Kč dle sazebníku (price) a Kč za holý spot."""
    spot_kwh = (float(czk_mwh) / 1000.0) if czk_mwh is not None else None
    if czk_mwh is None and np_kwh:
        d["slots_no_spot"] += 1
    if np_kwh > 0:
        d["import_kwh"] += np_kwh
        d["import_czk"] += np_kwh * price["import_czk"]
        if spot_kwh is not None:
            d["import_spot_czk"] += np_kwh * spot_kwh
    elif np_kwh < 0:
        d["export_kwh"] += -np_kwh
        d["export_czk"] += (-np_kwh) * price["export_czk"]
        if spot_kwh is not None:
            d["export_spot_czk"] += (-np_kwh) * spot_kwh


def unit_prices(d: dict) -> dict:
    """Jednotkové ceny JEN z reálně odebraných / dodaných kWh (vážený průměr):
    unit_import_czk = Kč dle sazebníku / kWh, unit_import_spot = holý spot / kWh, totéž export."""
    ik, ek = d.get("import_kwh", 0.0), d.get("export_kwh", 0.0)
    return {
        "unit_import_czk": round(d["import_czk"] / ik, 3) if ik > 0.01 else None,
        "unit_import_spot": round(d["import_spot_czk"] / ik, 3) if ik > 0.01 else None,
        "unit_export_czk": round(d["export_czk"] / ek, 3) if ek > 0.01 else None,
        "unit_export_spot": round(d["export_spot_czk"] / ek, 3) if ek > 0.01 else None,
    }


async def monthly_cost(device_ids: list[str], tariff: dict | None,
                       start: date, end: date) -> dict[str, dict]:
    """Cena importu/exportu po měsících DLE SAZEBNÍKU lokality (+ holý spot pro srovnání),
    z 15min slotů. Import = spot + přirážka + distribuce[VT/NT] + poplatky; export = spot − provize."""
    from ems.pricing import cost as pricing_cost

    out: dict[str, dict] = {}
    for r in await hourly_grid_spot(device_ids, start, end):
        d = out.setdefault(r["m"], cost_bucket())
        price = pricing_cost.price_czk_kwh(tariff, r["h"], r["czk_mwh"])
        accumulate(d, float(r["np_kwh"] or 0.0), price, r["czk_mwh"])
    return out


async def monthly_spot_cost(device_ids: list[str], start: date, end: date) -> dict[str, dict]:
    """ZASTARALÉ: holý spot bez sazebníku. Ponecháno pro srovnání/diagnostiku."""
    return await monthly_cost(device_ids, None, start, end)

_GRID_SQL = """
WITH net AS (
    SELECT bucket AS h, sum(avg) AS np FROM samples_15m
    WHERE device_id = ANY($1::text[]) AND metric = 'grid_power'
      AND bucket >= $2 AND bucket < $3
    GROUP BY bucket
)
SELECT to_char(date_trunc('month', h), 'YYYY-MM') AS m,
       sum(greatest(0, -np)) * 0.25 / 1000.0 AS export_kwh,
       sum(greatest(0,  np)) * 0.25 / 1000.0 AS import_kwh
FROM net GROUP BY 1
"""

_METRIC_SQL = """
WITH q AS (
    SELECT bucket AS h, sum(avg) AS p FROM samples_15m
    WHERE device_id = ANY($1::text[]) AND metric = $4
      AND bucket >= $2 AND bucket < $3
    GROUP BY bucket
)
SELECT to_char(date_trunc('month', h), 'YYYY-MM') AS m, sum(p) * 0.25 / 1000.0 AS kwh
FROM q GROUP BY 1
"""

# Výroba z vlastního DENNÍHO počítadla měniče (energy_today): max za pražský den
# = denní výroba; součet přes měsíc. Odolné proti výpadkům kolektoru.
_PROD_TODAY_SQL = """
SELECT to_char(date_trunc('month', day), 'YYYY-MM') AS m, sum(day_kwh) AS kwh FROM (
    SELECT device_id,
           date_trunc('day', bucket AT TIME ZONE 'Europe/Prague') AS day,
           max(max) AS day_kwh
    FROM samples_15m
    WHERE device_id = ANY($1::text[]) AND metric = 'energy_today'
      AND bucket >= $2 AND bucket < $3
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


_HOURLY_METRIC_SQL = """
SELECT bucket AS h, sum(avg) * 0.25 / 1000.0 AS kwh FROM samples_15m
WHERE device_id = ANY($1::text[]) AND metric = $4
  AND bucket >= $2 AND bucket < $3
GROUP BY bucket ORDER BY bucket
"""


async def hourly_metric_kwh(device_ids: list[str], metric: str, start: date, end: date) -> list[dict]:
    """Hodinová energie dané metriky (kWh) — pro denní rozpad (dny seskupí volající)."""
    if not device_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_HOURLY_METRIC_SQL, device_ids, start, end, metric)
    return [dict(r) for r in rows]


async def hourly_pv(device_ids: list[str], start: date, end: date) -> list[dict]:
    return await hourly_metric_kwh(device_ids, "pv_power", start, end)
