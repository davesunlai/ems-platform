"""Konfigurace plánovače (per lokalita) + uložený plán (dispatch_schedule)."""
from __future__ import annotations

from datetime import datetime

from ems.api.db import get_pool

CONFIG_DEFAULTS = {
    "enabled": False,                 # řídí (zapisuje do měniče)? default NE
    "allow_grid_discharge": False,    # smí vybíjet do sítě? (43136 neověřen) default NE
    "capacity_kwh": 52.8,             # Solis 2× 26.4
    "soc_min_pct": 15.0,
    "outage_reserve_pct": 10.0,       # rezerva navíc pro výpadek
    "max_charge_kw": 10.0,
    "max_discharge_kw": 10.0,
    "horizon_h": 36,
    # --- Smart Control: odložitelný výstup (spirála / bazén / cokoliv přes eWeLink či relé) ---
    "spiral_output_id": None,         # který switch_output planner řídí (NULL = žádný)
    "spiral_target_kwh": 0.0,         # cíl kWh/den (0 = neplánuj odložitelný výstup)
    "spiral_deadline_h": 7,           # hotovo do (pražská hodina, typicky ráno)
    "spiral_power_kw": 6.0,           # příkon spotřebiče
    "spiral_tmax_metric": "tank_s_bot",  # čidlo stropu (slave dolní I5)
    "spiral_tmax_c": 65.0,            # T_max – nad tím STOP spirály (seed)
    "spiral_kwh_per_deg": 2.33,       # tepelná kapacita nádrží (kWh/°C, seed)
    "spiral_min_on_min": 30,          # min. doba běhu (anti-short-cycle, ochrana relé)
    "spiral_min_off_min": 15,         # min. doba klidu
    "breaker_kw": 22.0,               # strop přípojky pro IMPORT (3×32 A ≈ 22 kW)
    "cycle_margin_czk_kwh": 0.5,      # práh, ať se vyplatí cyklovat baterii do sítě
    # --- 2a: ekonomika exportu + sezónní/tepelný model (SEED hodnoty, kalibrace později) ---
    "grid_export_limit_kw": 9.25,     # setpoint měniče (proti tomu plánuj export + detekuj ořez)
    "dso_export_limit_kw": 9.45,      # smluvní limit DS (jen validace: setpoint ≤ tohle)
    "export_price_floor_czk": 0.7,    # pod tuto cenu prodeje do sítě NIKDY nevybíjet
    "hodnota_tepla_leto": 2.0,        # Kč/kWh – alternativa získat teplo jinak (léto)
    "season_mode": "auto",            # auto | summer | winter
    "prah_zima": 15.0,                # 7denní průměr výroby FVE (kWh/den) < práh → WINTER
    "prah_leto": 35.0,                # > práh → SUMMER (prah_leto>prah_zima = hystereze)
    "tc_prikon_kw": 3.5,              # el. příkon TČ pro vytápění (seed)
    "tc_tuv_kwh_den": 4.0,            # TUV (teplá voda) – celoroční denní energie TČ (seed)
    "tc_cop_a": 2.75, "tc_cop_b": 0.11, "tc_cop_min": 1.8, "tc_cop_max": 4.0,
}
_CFG_KEYS = list(CONFIG_DEFAULTS.keys())


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planner_config (
                locality_id        INTEGER PRIMARY KEY,
                enabled            BOOLEAN NOT NULL DEFAULT FALSE,
                allow_grid_discharge BOOLEAN NOT NULL DEFAULT FALSE,
                capacity_kwh       DOUBLE PRECISION DEFAULT 52.8,
                soc_min_pct        DOUBLE PRECISION DEFAULT 15,
                outage_reserve_pct DOUBLE PRECISION DEFAULT 10,
                max_charge_kw      DOUBLE PRECISION DEFAULT 10,
                max_discharge_kw   DOUBLE PRECISION DEFAULT 10,
                horizon_h          INTEGER DEFAULT 36,
                updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch_schedule (
                locality_id  INTEGER NOT NULL,
                ts           TIMESTAMPTZ NOT NULL,
                action       TEXT NOT NULL,
                battery_kw   DOUBLE PRECISION,
                soc_pct      DOUBLE PRECISION,
                import_kwh   DOUBLE PRECISION,
                export_kwh   DOUBLE PRECISION,
                price_import DOUBLE PRECISION,
                price_export DOUBLE PRECISION,
                reason       TEXT,
                fetched_at   TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (locality_id, ts)
            )
            """
        )
        for col, ddl in (
            ("spiral_output_id", "INTEGER"),
            ("spiral_target_kwh", "DOUBLE PRECISION DEFAULT 0"),
            ("spiral_deadline_h", "INTEGER DEFAULT 7"),
            ("spiral_power_kw", "DOUBLE PRECISION DEFAULT 6"),
            ("spiral_tmax_metric", "TEXT DEFAULT 'tank_s_bot'"),
            ("spiral_tmax_c", "DOUBLE PRECISION DEFAULT 65"),
            ("spiral_kwh_per_deg", "DOUBLE PRECISION DEFAULT 2.33"),
            ("spiral_min_on_min", "INTEGER DEFAULT 30"),
            ("spiral_min_off_min", "INTEGER DEFAULT 15"),
            ("breaker_kw", "DOUBLE PRECISION DEFAULT 22"),
            ("cycle_margin_czk_kwh", "DOUBLE PRECISION DEFAULT 0.5"),
            ("grid_export_limit_kw", "DOUBLE PRECISION DEFAULT 9.25"),
            ("dso_export_limit_kw", "DOUBLE PRECISION DEFAULT 9.45"),
            ("export_price_floor_czk", "DOUBLE PRECISION DEFAULT 0.7"),
            ("hodnota_tepla_leto", "DOUBLE PRECISION DEFAULT 2.0"),
            ("season_mode", "TEXT DEFAULT 'auto'"),
            ("prah_zima", "DOUBLE PRECISION DEFAULT 15"),
            ("prah_leto", "DOUBLE PRECISION DEFAULT 35"),
            ("tc_prikon_kw", "DOUBLE PRECISION DEFAULT 3.5"),
            ("tc_tuv_kwh_den", "DOUBLE PRECISION DEFAULT 4.0"),
            ("tc_cop_a", "DOUBLE PRECISION DEFAULT 2.75"),
            ("tc_cop_b", "DOUBLE PRECISION DEFAULT 0.11"),
            ("tc_cop_min", "DOUBLE PRECISION DEFAULT 1.8"),
            ("tc_cop_max", "DOUBLE PRECISION DEFAULT 4.0"),
        ):
            await conn.execute(f"ALTER TABLE planner_config ADD COLUMN IF NOT EXISTS {col} {ddl}")
        await conn.execute("ALTER TABLE dispatch_schedule ADD COLUMN IF NOT EXISTS deferrable_on BOOLEAN DEFAULT FALSE")


async def get_config(locality_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM planner_config WHERE locality_id=$1", locality_id)
    cfg = dict(CONFIG_DEFAULTS)
    cfg["locality_id"] = locality_id
    if row:
        for k in _CFG_KEYS:
            cfg[k] = row[k]
    return cfg


async def all_enabled() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT locality_id FROM planner_config WHERE enabled=TRUE")
    return [r["locality_id"] for r in rows]


async def upsert_config(locality_id: int, patch: dict) -> dict:
    cur = await get_config(locality_id)
    cur.update({k: patch[k] for k in _CFG_KEYS if k in patch and patch[k] is not None})
    cols = ", ".join(["locality_id", *_CFG_KEYS])
    ph = ", ".join(f"${i}" for i in range(1, len(_CFG_KEYS) + 2))
    sets = ", ".join(f"{k}=EXCLUDED.{k}" for k in _CFG_KEYS)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO planner_config ({cols}) VALUES ({ph}) "
            f"ON CONFLICT (locality_id) DO UPDATE SET {sets}, updated_at=now()",
            locality_id, *[cur[k] for k in _CFG_KEYS])
    return await get_config(locality_id)


async def write_schedule(locality_id: int, rows: list[dict], fetched_at: datetime) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM dispatch_schedule WHERE locality_id=$1", locality_id)
            if rows:
                await conn.executemany(
                    "INSERT INTO dispatch_schedule (locality_id, ts, action, battery_kw, soc_pct, "
                    "import_kwh, export_kwh, price_import, price_export, reason, deferrable_on, fetched_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
                    [(locality_id, r["ts"], r["action"], r["battery_kw"], r["soc_pct"],
                      r["import_kwh"], r["export_kwh"], r["price_import"], r["price_export"],
                      r["reason"], bool(r.get("deferrable_on", False)), fetched_at) for r in rows])


async def latest_schedule(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ts, action, battery_kw, soc_pct, import_kwh, export_kwh, "
            "price_import, price_export, reason, deferrable_on FROM dispatch_schedule "
            "WHERE locality_id=$1 ORDER BY ts", locality_id)
    return [{**dict(r), "ts": r["ts"].isoformat()} for r in rows]


async def current_action(locality_id: int) -> dict | None:
    """Řádek plánu pro aktuální hodinu (pro výkon povelu kolektorem)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ts, action, battery_kw, soc_pct, reason, deferrable_on FROM dispatch_schedule "
            "WHERE locality_id=$1 AND ts <= now() ORDER BY ts DESC LIMIT 1", locality_id)
    return dict(row) if row else None


async def all_configs() -> list[dict]:
    """Konfigurace všech lokalit, co mají řádek (pro winddown vypnutých)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM planner_config")
    out = []
    for row in rows:
        cfg = dict(CONFIG_DEFAULTS)
        cfg["locality_id"] = row["locality_id"]
        for k in _CFG_KEYS:
            cfg[k] = row[k]
        out.append(cfg)
    return out


async def claimed_output_ids() -> set[int]:
    """ID switch_outputs, které vlastní ZAPNUTÝ planner (vyřadit z reaktivního evaluate_outputs)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT spiral_output_id FROM planner_config WHERE enabled=TRUE AND spiral_output_id IS NOT NULL")
    return {r["spiral_output_id"] for r in rows}
