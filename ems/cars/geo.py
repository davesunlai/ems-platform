"""Místo nabíjení z OpenStreetMap: nejbližší obec (Nominatim reverse) + provozovatel nabíječky (Overpass,
amenity=charging_station do 300 m, tagy operator/brand/network). Výsledek v cache `geo_cache` podle souřadnic
zaokrouhlených na 4 desetinná místa (~10 m). Limity: Nominatim 1 dotaz/s, slušný User-Agent; max 3 nové dotazy na požadavek."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import http.client
import socket
import ssl
import urllib.parse
import urllib.request


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """HTTPS jen přes IPv4 — kontejner má IPv6 adresu bez cesty ven („Network is unreachable“, lekce 5. 11.; dřív Docker Hub)."""
    def connect(self):
        infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"{self.host}: žádná IPv4 adresa")
        sock = socket.create_connection(infos[0][4], timeout=self.timeout)
        if self._tunnel_host:
            self.sock = sock; self._tunnel()
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req)


_opener = urllib.request.build_opener(_IPv4HTTPSHandler())

from ems.api.db import get_pool

logger = logging.getLogger("ems.cars.geo")
UA = "TERA-EMS/1.0 (energy management; contact via teraems.com)"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
# overpass-api.de (i lz4.) aktivně odmítá IP franty (blocklist, lekce 5. 11.), kumi timeoutuje, osm.ch kryje jen Švýcarsko →
# zkoušet zrcadla v pořadí, první odpověď s 'elements' vyhrává; pak OpenChargeMap (klíč v app_settings.ocm_api_key nebo EMS_OCM_API_KEY)
OVERPASS_MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter"]      # osm.jp má neplatný certifikát
OCM = "https://api.openchargemap.io/v3/poi/"
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
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url: str, data: str, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, data=data.encode("utf-8"), headers={"User-Agent": UA, "Accept": "application/json",
                                                                          "Content-Type": "application/x-www-form-urlencoded"})
    with _opener.open(req, timeout=timeout) as r:
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
    q = f'[out:json][timeout:30];(node["amenity"="charging_station"](around:{RADIUS_M},{lat},{lon});way["amenity"="charging_station"](around:{RADIUS_M},{lat},{lon}););out center tags;'
    for url in OVERPASS_MIRRORS:
        try:
            res = await asyncio.to_thread(_post, url, "data=" + urllib.parse.quote(q), 40)   # běží na pozadí; Overpass běžně 10–30 s
            if not isinstance(res, dict) or "elements" not in res:
                continue
            op, name, d = operator_from_overpass(res, lat, lon)
            out.update(operator=op, station_name=name, distance_m=round(d) if d is not None else None)
            out["raw"].update(stations=len(res.get("elements") or []), radius_m=RADIUS_M, overpass=url)
            break
        except Exception as exc:
            logger.warning("overpass %s %.4f,%.4f: %s", url.split("/")[2], lat, lon, exc)
    if out["operator"] is None:
        await _ocm(lat, lon, out)
    return out


async def _ocm(lat: float, lon: float, out: dict) -> None:
    """OpenChargeMap (druhý zdroj): nejbližší POI do RADIUS_M, OperatorInfo.Title."""
    import os
    from ems.api.db import get_setting
    key = (await get_setting("ocm_api_key", None)) or os.getenv("EMS_OCM_API_KEY")
    if not key:
        out["raw"]["ocm"] = "bez klíče"
        return
    try:
        import math
        url = f"{OCM}?{urllib.parse.urlencode({'output': 'json', 'latitude': lat, 'longitude': lon, 'distance': RADIUS_M / 1000, 'distanceunit': 'km', 'maxresults': 10, 'compact': 'true', 'verbose': 'false'})}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", "X-API-Key": key})
        def _run():
            with _opener.open(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        res = await asyncio.to_thread(_run)
        best = None
        for poi in res or []:
            a = poi.get("AddressInfo") or {}
            la, lo = a.get("Latitude"), a.get("Longitude")
            if la is None or lo is None:
                continue
            d = math.hypot((la - lat) * 111320, (lo - lon) * 111320 * math.cos(math.radians(lat)))
            op = (poi.get("OperatorInfo") or {}).get("Title")
            if best is None or d < best[2]:
                best = (op, a.get("Title"), d)
        out["raw"]["ocm"] = len(res or [])
        if best and best[0]:
            out.update(operator=best[0], station_name=best[1], distance_m=round(best[2]))
            out["raw"]["source"] = "openchargemap"
    except Exception as exc:
        logger.warning("openchargemap %.4f,%.4f: %s", lat, lon, exc)
        out["raw"]["ocm"] = f"chyba: {exc}"


_bg_tasks: set = set()
_inflight: set = set()


def _schedule(keys: list[tuple[float, float]]) -> None:
    """Dohledání na pozadí (zrcadla mohou timeoutovat desítky sekund — nesmí blokovat API)."""
    todo = [k for k in keys if k not in _inflight]
    if not todo:
        return
    for k in todo:
        _inflight.add(k)

    async def run():
        try:
            await resolve_many(todo, max_new=len(todo), background=False)
        finally:
            for k in todo:
                _inflight.discard(k)
    t = asyncio.get_running_loop().create_task(run())
    _bg_tasks.add(t); t.add_done_callback(_bg_tasks.discard)


async def resolve_many(points: list[tuple[float, float]], max_new: int = 3, background: bool = True) -> dict[tuple[float, float], dict]:
    """Vrátí {(lat4, lon4): {place, operator, station_name, distance_m}} z cache; chybějící/neúplné
    s background=True naplánuje na pozadí a vrátí hned (volající dostane místo při příštím dotazu)."""
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
    missing = [k for k in keys if k not in out]
    if background:
        if missing:
            _schedule(missing[:max_new])
        # částečná data (obec bez provozovatele) vrať hned
        for r in rows:
            k = (round(float(r["lat4"]), 4), round(float(r["lon4"]), 4))
            if k in keys and k not in out:
                out[k] = {"place": r["place"], "operator": r["operator"], "station_name": r["station_name"], "distance_m": r["distance_m"], "pending": True}
        return out
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
