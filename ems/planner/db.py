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
    "spiral_anti_curtail": True,      # reaktivní soak: baterie plná + přetok na stropu → spirála ON
    "spiral_curtail_frac": 0.6,       # spirálu pouštět na ořez, až když by se ořezal ≥ tento podíl jejího příkonu
    "breaker_kw": 22.0,               # strop přípojky pro IMPORT (3×32 A ≈ 22 kW)
    "cycle_margin_czk_kwh": 0.5,      # práh, ať se vyplatí cyklovat baterii do sítě
    # --- 2a: ekonomika exportu + sezónní/tepelný model (SEED hodnoty, kalibrace později) ---
    "grid_export_limit_kw": 9.25,     # setpoint měniče (proti tomu plánuj export + detekuj ořez)
    "dso_export_limit_kw": 9.45,      # smluvní limit DS (jen validace: setpoint ≤ tohle)
    "export_price_floor_czk": 0.7,    # pod tuto cenu prodeje do sítě NIKDY nevybíjet
    "import_price_ceiling_czk": 1.0,  # nad tuto cenu nákupu NIKDY neplánovat odběr z gridu (baterie má prioritu)
    "reserve_margin_pct": 20.0,       # bezpečnostní marže noční rezervy (+% na predikci spotřeby noci)
    "priority_order": '["reserve","export","spiral","grid_charge"]',  # pořadí priorit (UI drag&drop)
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
            ("spiral_anti_curtail", "BOOLEAN DEFAULT TRUE"),
            ("spiral_curtail_frac", "DOUBLE PRECISION DEFAULT 0.6"),
            ("breaker_kw", "DOUBLE PRECISION DEFAULT 22"),
            ("cycle_margin_czk_kwh", "DOUBLE PRECISION DEFAULT 0.5"),
            ("grid_export_limit_kw", "DOUBLE PRECISION DEFAULT 9.25"),
            ("dso_export_limit_kw", "DOUBLE PRECISION DEFAULT 9.45"),
            ("export_price_floor_czk", "DOUBLE PRECISION DEFAULT 0.7"),
            ("import_price_ceiling_czk", "DOUBLE PRECISION DEFAULT 1.0"),
            ("reserve_margin_pct", "DOUBLE PRECISION DEFAULT 20"),
            ("priority_order", "TEXT DEFAULT '[\"reserve\",\"export\",\"spiral\",\"grid_charge\"]'"),
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
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planner_time_rules (
                id SERIAL PRIMARY KEY,
                locality_id INTEGER NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                label TEXT NOT NULL DEFAULT '',
                time_from TEXT NOT NULL,
                time_to TEXT NOT NULL,
                days TEXT NOT NULL DEFAULT '1234567',
                action TEXT NOT NULL,
                target TEXT,
                power_kw DOUBLE PRECISION NOT NULL DEFAULT 5
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pv_forecast_daily (
                locality_id INTEGER NOT NULL,
                day DATE NOT NULL,
                forecast_kwh DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (locality_id, day)
            )
            """
        )
        for col, ddl in (
            ("cond_sun", "TEXT NOT NULL DEFAULT 'any'"),
            ("cond_sun_kwh", "DOUBLE PRECISION NOT NULL DEFAULT 30"),
            ("cond_soc_op", "TEXT NOT NULL DEFAULT 'any'"),
            ("cond_soc_pct", "DOUBLE PRECISION NOT NULL DEFAULT 50"),
            ("cond_spot_op", "TEXT NOT NULL DEFAULT 'any'"),
            ("cond_spot_czk", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
            ("cond_spot_hold", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("cond_logic", "TEXT NOT NULL DEFAULT 'and'"),
            ("cond_soc_hold", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("latched_soc_window", "TEXT"),
            ("latched_window", "TEXT"),
        ):
            await conn.execute(f"ALTER TABLE planner_time_rules ADD COLUMN IF NOT EXISTS {col} {ddl}")


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


# --- ⏰ Časový plán (priorita 2 — hned pod bezpečnostní podlahou) -------------
TIME_RULE_FIELDS = ("enabled", "label", "time_from", "time_to", "days", "action", "target", "power_kw",
                    "cond_sun", "cond_sun_kwh", "cond_soc_op", "cond_soc_pct", "cond_spot_op", "cond_spot_czk", "cond_spot_hold", "cond_soc_hold", "cond_logic")
TIME_RULE_ACTIONS = ("force_charge", "force_discharge", "stop", "output_on", "output_off")


async def list_time_rules(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, latched_window, latched_soc_window, " + ", ".join(TIME_RULE_FIELDS) +
            " FROM planner_time_rules WHERE locality_id=$1 ORDER BY time_from, id", locality_id)
    return [dict(r) for r in rows]


async def create_time_rule(locality_id: int, data: dict) -> dict:
    pool = await get_pool()
    vals = [data.get(k) for k in TIME_RULE_FIELDS]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO planner_time_rules (locality_id, " + ", ".join(TIME_RULE_FIELDS) + ") "
            "VALUES ($1, " + ", ".join(f"${i+2}" for i in range(len(TIME_RULE_FIELDS))) + ") "
            "RETURNING id, " + ", ".join(TIME_RULE_FIELDS), locality_id, *vals)
    return dict(row)


async def update_time_rule(locality_id: int, rid: int, data: dict) -> dict | None:
    cur = None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, " + ", ".join(TIME_RULE_FIELDS) +
            " FROM planner_time_rules WHERE locality_id=$1 AND id=$2", locality_id, rid)
        if not row:
            return None
        cur = dict(row)
        for k in TIME_RULE_FIELDS:
            if k in data and data[k] is not None:
                cur[k] = data[k]
        await conn.execute(
            "UPDATE planner_time_rules SET " +
            ", ".join(f"{k}=${i+3}" for i, k in enumerate(TIME_RULE_FIELDS)) +
            " WHERE locality_id=$1 AND id=$2", locality_id, rid, *[cur[k] for k in TIME_RULE_FIELDS])
    return cur


async def delete_time_rule(locality_id: int, rid: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM planner_time_rules WHERE locality_id=$1 AND id=$2", locality_id, rid)
    return res.endswith("1")


def _rule_active(rule: dict, hm: str, isoday: str) -> bool:
    """Okno HH:MM–HH:MM v pražském čase; from>to = přes půlnoc. days = ISO číslice 1–7."""
    if not rule.get("enabled"):
        return False
    if isoday not in (rule.get("days") or "1234567"):
        return False
    f, t = rule.get("time_from") or "00:00", rule.get("time_to") or "00:00"
    return (f <= hm < t) if f <= t else (hm >= f or hm < t)


async def active_time_rules(locality_id: int) -> list[dict]:
    """Pravidla aktivní PRÁVĚ TEĎ (pražský čas)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/Prague"))
    hm, isoday = now.strftime("%H:%M"), str(now.isoweekday())
    return [r for r in await list_time_rules(locality_id) if _rule_active(r, hm, isoday)]


def rule_conditions_ok(rule: dict, day_pv_kwh: float | None, soc_pct: float | None,
                       spot_czk_kwh: float | None = None, spot_latched: bool = False,
                       soc_latched: bool = False) -> bool:
    """Volitelné podmínky pravidla (vyhodnocují se PRŮBĚŽNĚ během okna).
    cond_logic: 'and' (default) = všechny definované musí platit; 'or' = stačí jedna.
    Chybí-li podklad (predikce/SoC/spot), daná podmínka se bere jako NEsplněná
    (v AND blokuje celé pravidlo, v OR mohou zabrat ostatní)."""
    results = []
    cs = rule.get("cond_sun") or "any"
    if cs != "any":
        if day_pv_kwh is None:
            results.append(False)
        else:
            thr = float(rule.get("cond_sun_kwh") or 30)
            results.append(day_pv_kwh >= thr if cs == "sunny" else day_pv_kwh < thr)
    op = rule.get("cond_soc_op") or "any"
    if op != "any":
        results.append(True if soc_latched else soc_cond_ok(rule, soc_pct))
    sop = rule.get("cond_spot_op") or "any"
    if sop != "any":
        results.append(True if spot_latched else spot_cond_ok(rule, spot_czk_kwh))
    if not results:
        return True
    return any(results) if (rule.get("cond_logic") or "and") == "or" else all(results)


def soc_cond_ok(rule: dict, soc_pct: float | None) -> bool:
    """Samotná SoC podmínka (bez latch logiky)."""
    op = rule.get("cond_soc_op") or "any"
    if op == "any":
        return True
    if soc_pct is None:
        return False
    pct = float(rule.get("cond_soc_pct") or 50)
    return soc_pct >= pct if op == "ge" else soc_pct <= pct


def spot_cond_ok(rule: dict, spot_czk_kwh: float | None) -> bool:
    """Samotná spotová podmínka (bez latch logiky)."""
    sop = rule.get("cond_spot_op") or "any"
    if sop == "any":
        return True
    if spot_czk_kwh is None:
        return False
    thr = rule.get("cond_spot_czk")
    thr = 0.0 if thr is None else float(thr)
    return spot_czk_kwh >= thr if sop == "ge" else spot_czk_kwh <= thr


def rule_window_key(rule: dict, now=None) -> str:
    """Identita AKTUÁLNÍHO běhu okna: 'YYYY-MM-DD|HH:MM' (datum, kdy okno začalo;
    u oken přes půlnoc patří ranní část k včerejšímu startu)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    if now is None:
        now = datetime.now(ZoneInfo("Europe/Prague"))
    f, t = rule.get("time_from") or "00:00", rule.get("time_to") or "00:00"
    hm = now.strftime("%H:%M")
    start_day = now.date()
    if f > t and hm < t:                    # přes půlnoc, jsme v ranní části → start včera
        start_day = (now - timedelta(days=1)).date()
    return f"{start_day.isoformat()}|{f}"


async def set_rule_latch(rid: int, window_key: str, field: str = "latched_window") -> None:
    if field not in ("latched_window", "latched_soc_window"):
        raise ValueError(field)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE planner_time_rules SET {field}=$2 WHERE id=$1", rid, window_key)


# --- Denní snapshot predikce výroby (pro srovnání predikce vs. realita) ------
async def upsert_pv_forecast_day(locality_id: int, day: str, kwh: float) -> None:
    """První zápis dne vyhrává (snapshot ranní predikce celého dne)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO pv_forecast_daily (locality_id, day, forecast_kwh) VALUES ($1, $2, $3) "
            "ON CONFLICT (locality_id, day) DO NOTHING", locality_id, __import__("datetime").date.fromisoformat(day), float(kwh))


async def get_pv_forecast_days(locality_id: int, start, end) -> dict[str, float]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT day, forecast_kwh FROM pv_forecast_daily WHERE locality_id=$1 AND day >= $2 AND day < $3",
            locality_id, start, end)
    return {r["day"].isoformat(): float(r["forecast_kwh"]) for r in rows}
