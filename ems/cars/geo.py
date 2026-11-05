"""Místo nabíjení z OpenStreetMap: nejbližší obec (Nominatim reverse) + provozovatel nabíječky (Overpass,
amenity=charging_station do 300 m, tagy operator/brand/network). Výsledek v cache `geo_cache` podle souřadnic
zaokrouhlených na 4 desetinná místa (~10 m). Limity: Nominatim 1 dotaz/s, slušný User-Agent; max 3 nové dotazy na požadavek."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request

from ems.api.db import get_pool

logger = logging.getLogger("ems.cars.geo")
UA = "TERA-EMS/1.0 (energy management; contact via teraems.com)"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
OVERPASS = "https://overpass-api.de/api/interpreter"
RADIUS_M = 1500      # BMW posílá polohu zaokrouhlenou (při zapojení na 2 des. místa ≈ ±0,7 km) → hledat široko, vzít nejbližší
_last_nominatim = 0.0


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS geo_cache (
                lat4 REAL NOT NULL, lon4 REAL NOT NULL,
                place TEXT, operator TEXT, station_name TEXT, distance_m REAL,
                raw JSONB, resolved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (lat4, lon4))""")


def _get(url: str, timeout: float = 6) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url: str, data: str, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, data=data.encode("utf-8"), headers={"User-Agent": UA, "Accept": "application/json",
                                                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def place_from_nominatim(res: dict) -> str | None:
    a = res.get("address") or {}
    for k in ("village", "town", "city", "municipality", "hamlet", "suburb", "county"):
        if a.get(k):
            return a[k]
    return (res.get("display_name") or "").split(",")[0] or None


def operator_from_overpass(res: dict, lat: float, lon: float) -> tuple[str | None, str | None, float | None]:
    """(operator, název stanice, vzdálenost m) nejbližší stanice."""
    import math
    best = None
    for el in res.get("elements") or []:
        t = el.get("tags") or {}
        la = el.get("lat") or (el.get("center") or {}).get("lat"); lo = el.get("lon") or (el.get("center") or {}).get("lon")
        if la is None or lo is None:
            continue
        d = math.hypot((la - lat) * 111320, (lo - lon) * 111320 * math.cos(math.radians(lat)))
        op = t.get("operator") or t.get("brand") or t.get("network") or t.get("name")
        if best is None or d < best[2]:
            best = (op, t.get("name") or t.get("brand"), d)
    return best or (None, None, None)


async def _lookup(lat: float, lon: float) -> dict:
    global _last_nominatim
    out = {"place": None, "operator": None, "station_name": None, "distance_m": None, "raw": {}}
    try:
        wait = 1.1 - (time.monotonic() - _last_nominatim)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_nominatim = time.monotonic()
        res = await asyncio.to_thread(_get, f"{NOMINATIM}?{urllib.parse.urlencode({'lat': lat, 'lon': lon, 'format': 'jsonv2', 'zoom': 14, 'accept-language': 'cs'})}")
        out["place"] = place_from_nominatim(res); out["raw"]["nominatim"] = res.get("address")
    except Exception as exc:
        logger.info("nominatim %.4f,%.4f: %s", lat, lon, exc)
    try:
        q = f'[out:json][timeout:8];(node["amenity"="charging_station"](around:{RADIUS_M},{lat},{lon});way["amenity"="charging_station"](around:{RADIUS_M},{lat},{lon}););out center tags;'
        res = await asyncio.to_thread(_post, OVERPASS, "data=" + urllib.parse.quote(q))
        op, name, d = operator_from_overpass(res, lat, lon)
        out.update(operator=op, station_name=name, distance_m=round(d) if d is not None else None)
        out["raw"]["stations"] = len(res.get("elements") or []); out["raw"]["radius_m"] = RADIUS_M
    except Exception as exc:
        logger.info("overpass %.4f,%.4f: %s", lat, lon, exc)
    return out


async def resolve_many(points: list[tuple[float, float]], max_new: int = 3) -> dict[tuple[float, float], dict]:
    """Vrátí {(lat4, lon4): {place, operator, station_name, distance_m}} — z cache, chybějící dohledá (max_new)."""
    keys = sorted({(round(float(la), 4), round(float(lo), 4)) for la, lo in points if la is not None and lo is not None})
    if not keys:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT lat4, lon4, place, operator, station_name, distance_m, resolved_at, "
            "COALESCE((raw->>'radius_m')::int, 0) AS radius_m FROM geo_cache WHERE lat4 = ANY($1::real[]) AND lon4 = ANY($2::real[])",
            [k[0] for k in keys], [k[1] for k in keys])
    out = {}
    from datetime import datetime, timezone, timedelta
    for r in rows:
        k = (round(float(r["lat4"]), 4), round(float(r["lon4"]), 4))
        if k not in keys:
            continue
        # bez provozovatele a hledáno užším poloměrem (nebo před > 1 dnem) → zkusit znovu
        stale = r["operator"] is None and (int(r["radius_m"] or 0) < RADIUS_M or r["resolved_at"] < datetime.now(timezone.utc) - timedelta(days=1))
        if not stale:
            out[k] = {"place": r["place"], "operator": r["operator"], "station_name": r["station_name"], "distance_m": r["distance_m"]}
    new = 0
    for k in keys:
        if k in out or new >= max_new:
            continue
        new += 1
        info = await _lookup(*k)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO geo_cache (lat4, lon4, place, operator, station_name, distance_m, raw) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb) "
                "ON CONFLICT (lat4, lon4) DO UPDATE SET place=EXCLUDED.place, operator=EXCLUDED.operator, station_name=EXCLUDED.station_name, "
                "distance_m=EXCLUDED.distance_m, raw=EXCLUDED.raw, resolved_at=now()",
                k[0], k[1], info["place"], info["operator"], info["station_name"], info["distance_m"], json.dumps(info["raw"], ensure_ascii=False))
        out[k] = {kk: info[kk] for kk in ("place", "operator", "station_name", "distance_m")}
    return out


def label(info: dict | None) -> str | None:
    """„Ionity · Mohelnice“ / „ČEZ · Olomouc“ / „Mohelnice“."""
    if not info:
        return None
    parts = [p for p in (info.get("operator"), info.get("place")) if p]
    return " · ".join(parts) or None
