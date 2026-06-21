"""Zdroje predikce počasí. Vzor: base class + provideři (jako outage provideři).

Open-Meteo: global_tilted_irradiance (rovina panelu), temperature_2m, cloud_cover.
Azimut Open-Meteo: 0 = jih, −90 = východ, +90 = západ (ověřeno v dokumentaci).
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("ems.forecast")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_SOLAR_URL = "https://api.forecast.solar/estimate"


class WeatherProvider:
    """Vrátí hodinové řady počasí pro jednu orientaci panelu (tilt/azimuth)."""
    name = "base"

    async def fetch(self, lat: float, lon: float, tilt: float, azimuth: float,
                    hours: int = 48) -> list[dict]:
        raise NotImplementedError


class OpenMeteoProvider(WeatherProvider):
    name = "open_meteo"

    async def fetch(self, lat: float, lon: float, tilt: float, azimuth: float,
                    hours: int = 48) -> list[dict]:
        import httpx
        params = {
            "latitude": round(lat, 4), "longitude": round(lon, 4),
            "hourly": "global_tilted_irradiance,shortwave_radiation,temperature_2m,cloud_cover",
            "tilt": round(tilt, 1), "azimuth": round(azimuth, 1),
            "forecast_days": 3, "timezone": "auto",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(OPEN_METEO_URL, params=params)
            r.raise_for_status()
            data = r.json()
        h = data.get("hourly") or {}
        times = h.get("time") or []
        gti = h.get("global_tilted_irradiance") or []
        ghi = h.get("shortwave_radiation") or []
        temp = h.get("temperature_2m") or []
        cloud = h.get("cloud_cover") or []
        out = []
        for i, t in enumerate(times[:hours]):
            out.append({
                "ts": _parse_ts(t, data.get("utc_offset_seconds", 0)),
                "gti": _at(gti, i), "ghi": _at(ghi, i),
                "temp_c": _at(temp, i), "cloud_pct": _at(cloud, i),
            })
        return out


class ForecastSolarProvider:
    """Přímý odhad výroby (W) z lat/lon/sklon/azimut/kWp.

    Azimut Forecast.Solar je SHODNÝ s Open-Meteo (0=jih, −90=východ, +90=západ),
    takže náš uložený azimut se předává beze změny. Free: 12 dotazů/hod/IP.
    """
    name = "forecast_solar"

    async def fetch(self, lat: float, lon: float, tilt: float, azimuth: float,
                    kwp: float) -> list[dict]:
        import httpx
        url = f"{FORECAST_SOLAR_URL}/{lat:.4f}/{lon:.4f}/{round(tilt)}/{round(azimuth)}/{kwp:.2f}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        watts = (data.get("result") or {}).get("watts") or {}
        tz = _offset_from(data)
        out = []
        for k, w in watts.items():
            try:
                dt = datetime.fromisoformat(k)
            except ValueError:
                continue
            if dt.minute != 0:          # jen celé hodiny (vynech sunrise/sunset body)
                continue
            if dt.tzinfo is None and tz is not None:
                dt = dt.replace(tzinfo=tz)
            out.append({"ts": dt, "pv_w": float(w or 0)})
        out.sort(key=lambda r: r["ts"])
        return out


def _offset_from(data: dict):
    """tzinfo z message.info.time (např. ...+02:00)."""
    from datetime import timezone
    t = ((data.get("message") or {}).get("info") or {}).get("time")
    if not t:
        return timezone.utc
    try:
        return datetime.fromisoformat(t).tzinfo or timezone.utc
    except ValueError:
        return timezone.utc


async def geocode(query: str, count: int = 5, language: str = "cs") -> list[dict]:
    """Fulltext město → kandidáti s lat/lon (Open-Meteo geocoding, zdarma bez klíče)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(GEOCODE_URL, params={
                "name": query, "count": count, "language": language, "format": "json"})
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("Geokódování '%s' selhalo: %s", query, exc)
        return []
    out = []
    for g in data.get("results") or []:
        parts = [g.get("name"), g.get("admin1"), g.get("country")]
        out.append({
            "name": g.get("name"),
            "label": ", ".join(p for p in parts if p),
            "lat": g.get("latitude"), "lon": g.get("longitude"),
            "country": g.get("country_code"),
        })
    return out


def _at(arr: list, i: int):
    return arr[i] if i < len(arr) and arr[i] is not None else None


def _parse_ts(t: str, utc_offset: int) -> datetime:
    # Open-Meteo s timezone=auto vrací lokální čas bez offsetu -> doplníme offset.
    from datetime import timezone, timedelta
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(seconds=utc_offset or 0)))
    return dt
