"""Tabulky: car_accounts (BMW účet + tokeny), car_vehicles (VIN → lokalita/wallbox), car_state (poslední
hodnoty všech deskriptorů per VIN), car_history (hypertable: ts, vin, key, value_num/value_txt).
Mapování deskriptorů na role (soc, range, …) je konfigurovatelné (car_key_map) — katalog TDC se liší
podle modelu, takže se mapuje až podle toho, co auto reálně posílá."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ems.api.db import get_pool

# výchozí mapování rolí → deskriptor (podle integrací komunity; ověří se živě proti tomu, co auto posílá)
DEFAULT_KEY_MAP = {
    "soc": "vehicle.drivetrain.batteryManagement.header",
    "capacity_kwh": "vehicle.drivetrain.batteryManagement.maxEnergy",
    "charging_status": "vehicle.drivetrain.electricEngine.charging.status",
    "charging_power_kw": "vehicle.powertrain.electric.battery.charging.power",
    "plugged": "vehicle.drivetrain.electricEngine.charging.plugConnected",
    "target_soc": "vehicle.drivetrain.electricEngine.charging.targetSoc",
    "range_km": "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange",
    "odometer_km": "vehicle.vehicle.travelledDistance",
    "lat": "vehicle.cabin.infotainment.navigation.currentLocation.latitude",
    "lon": "vehicle.cabin.infotainment.navigation.currentLocation.longitude",
}
ROLES = list(DEFAULT_KEY_MAP)


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS car_accounts (
                id SERIAL PRIMARY KEY,
                locality_id INTEGER,
                client_id TEXT NOT NULL,
                gcid TEXT,
                access_token TEXT, refresh_token TEXT, id_token TEXT,
                access_expires_at TIMESTAMPTZ, refresh_expires_at TIMESTAMPTZ,
                device_code TEXT, user_code TEXT, verification_uri TEXT, code_verifier TEXT,
                device_expires_at TIMESTAMPTZ, poll_interval_s INTEGER,
                status TEXT NOT NULL DEFAULT 'new',      -- new | pending | connected | expired | error
                last_error TEXT,
                stream_status TEXT, stream_since TIMESTAMPTZ, stream_msgs BIGINT NOT NULL DEFAULT 0,
                rest_calls_today INTEGER NOT NULL DEFAULT 0, rest_day DATE,
                container_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS car_vehicles (
                vin TEXT PRIMARY KEY,
                account_id INTEGER REFERENCES car_accounts(id) ON DELETE CASCADE,
                locality_id INTEGER,
                name TEXT, model TEXT, brand TEXT,
                wallbox_module_id TEXT,
                capacity_kwh DOUBLE PRECISION,
                key_map JSONB,
                basic JSONB,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS car_state (
                vin TEXT NOT NULL, key TEXT NOT NULL,
                value_num DOUBLE PRECISION, value_txt TEXT, unit TEXT,
                ts TIMESTAMPTZ NOT NULL, source TEXT,
                PRIMARY KEY (vin, key)
            )""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS car_history (
                ts TIMESTAMPTZ NOT NULL, vin TEXT NOT NULL, key TEXT NOT NULL,
                value_num DOUBLE PRECISION, value_txt TEXT
            )""")
        try:
            await conn.execute("SELECT create_hypertable('car_history', 'ts', if_not_exists => TRUE)")
        except Exception:
            pass
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_car_hist ON car_history (vin, key, ts DESC)")


# --- účty ---------------------------------------------------------------------
async def list_accounts() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM car_accounts ORDER BY id")
    return [dict(r) for r in rows]


async def get_account(aid: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM car_accounts WHERE id=$1", aid)
    return dict(r) if r else None


async def create_account(locality_id: int | None, client_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO car_accounts (locality_id, client_id) VALUES ($1, $2) RETURNING *", locality_id, client_id.strip())
    return dict(r)


async def update_account(aid: int, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        vals.append(v); cols.append(f"{k}=${len(vals)}")
    vals.append(aid)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE car_accounts SET {', '.join(cols)}, updated_at=now() WHERE id=${len(vals)}", *vals)


async def delete_account(aid: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM car_accounts WHERE id=$1", aid)


async def rest_budget_hit(aid: int, limit: int = 45) -> bool:
    """Denní rozpočet REST (BMW: 50/den, reset o půlnoci UTC) — držíme rezervu."""
    pool = await get_pool()
    today = datetime.now(timezone.utc).date()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT rest_calls_today, rest_day FROM car_accounts WHERE id=$1", aid)
        if not r:
            return True
        n = r["rest_calls_today"] if r["rest_day"] == today else 0
        if n >= limit:
            return True
        await conn.execute("UPDATE car_accounts SET rest_calls_today=$2, rest_day=$3 WHERE id=$1", aid, n + 1, today)
    return False


# --- vozidla --------------------------------------------------------------------
async def upsert_vehicle(vin: str, account_id: int, **fields) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO car_vehicles (vin, account_id, locality_id) VALUES ($1, $2, (SELECT locality_id FROM car_accounts WHERE id=$2)) "
            "ON CONFLICT (vin) DO NOTHING", vin, account_id)
        for k, v in fields.items():
            if k in ("basic", "key_map"):
                v = json.dumps(v)
                await conn.execute(f"UPDATE car_vehicles SET {k}=$2::jsonb WHERE vin=$1", vin, v)
            else:
                await conn.execute(f"UPDATE car_vehicles SET {k}=$2 WHERE vin=$1", vin, v)


async def list_vehicles(locality_id: int | None = None) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if locality_id is None:
            rows = await conn.fetch("SELECT * FROM car_vehicles ORDER BY vin")
        else:
            rows = await conn.fetch("SELECT * FROM car_vehicles WHERE locality_id=$1 ORDER BY vin", locality_id)
    out = []
    for r in rows:
        d = dict(r)
        for k in ("basic", "key_map"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    d[k] = None
        out.append(d)
    return out


async def update_vehicle(vin: str, patch: dict) -> None:
    allowed = {"name", "locality_id", "wallbox_module_id", "capacity_kwh", "key_map", "enabled"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        for k, v in patch.items():
            if k not in allowed:
                continue
            if k == "key_map":
                await conn.execute("UPDATE car_vehicles SET key_map=$2::jsonb WHERE vin=$1", vin, json.dumps(v))
            else:
                await conn.execute(f"UPDATE car_vehicles SET {k}=$2 WHERE vin=$1", vin, v)


# --- stav / historie -------------------------------------------------------------
def _split(value):
    if isinstance(value, bool):
        return (1.0 if value else 0.0), str(value).lower()
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, str):
        try:
            return float(value), value
        except ValueError:
            return None, value
    if value is None:
        return None, None
    return None, json.dumps(value)[:500]


async def write_values(vin: str, items: dict, source: str, default_ts: datetime | None = None) -> int:
    """items: {key: {"value":…, "timestamp":…, "unit":…}} nebo {key: value}. Upsert car_state + append historie."""
    pool = await get_pool()
    n = 0
    async with pool.acquire() as conn:
        for key, v in items.items():
            unit, ts = None, default_ts or datetime.now(timezone.utc)
            if isinstance(v, dict) and "value" in v:
                unit = v.get("unit")
                tsr = v.get("timestamp")
                if tsr:
                    try:
                        ts = datetime.fromisoformat(str(tsr).replace("Z", "+00:00"))
                    except ValueError:
                        pass
                v = v.get("value")
            num, txt = _split(v)
            await conn.execute(
                "INSERT INTO car_state (vin, key, value_num, value_txt, unit, ts, source) VALUES ($1,$2,$3,$4,$5,$6,$7) "
                "ON CONFLICT (vin, key) DO UPDATE SET value_num=EXCLUDED.value_num, value_txt=EXCLUDED.value_txt, "
                "unit=EXCLUDED.unit, ts=EXCLUDED.ts, source=EXCLUDED.source",
                vin, key, num, txt, unit, ts, source)
            await conn.execute("INSERT INTO car_history (ts, vin, key, value_num, value_txt) VALUES ($1,$2,$3,$4,$5)",
                               ts, vin, key, num, txt)
            n += 1
    return n


async def state(vin: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value_num, value_txt, unit, ts, source FROM car_state WHERE vin=$1 ORDER BY key", vin)
    return {r["key"]: {"value": r["value_num"] if r["value_num"] is not None else r["value_txt"],
                       "unit": r["unit"], "ts": r["ts"].isoformat(), "source": r["source"]} for r in rows}


async def history(vin: str, key: str, hours: int = 48) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ts, value_num, value_txt FROM car_history WHERE vin=$1 AND key=$2 AND ts > now() - make_interval(hours => $3) ORDER BY ts",
            vin, key, hours)
    return [{"ts": r["ts"].isoformat(), "value": r["value_num"] if r["value_num"] is not None else r["value_txt"]} for r in rows]
