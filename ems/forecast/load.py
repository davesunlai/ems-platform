"""Predikce zátěže domu (load_forecast).

MVP: medián hodinové zátěže podle hodina-v-týdnu (ISO dow 1–7 × hodina 0–23)
z historie. Solis nedává load_power, proto zátěž počítáme z BILANCE:
    load_w = pv_power + grid_power − battery_power
(grid_power = +odběr/−dodávka; battery_power = +nabíjení/−vybíjení).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ems.api.db import get_pool

logger = logging.getLogger("ems.forecast")

_PROFILE_SQL = """
WITH per AS (
    SELECT time_bucket('1 hour', time) AS h, device_id,
           COALESCE(avg(value) FILTER (WHERE metric='pv_power'), 0)     AS pv,
           COALESCE(avg(value) FILTER (WHERE metric='grid_power'), 0)   AS g,
           COALESCE(avg(value) FILTER (WHERE metric='battery_power'), 0) AS b
    FROM samples
    WHERE device_id = ANY($1::text[])
      AND metric IN ('pv_power','grid_power','battery_power')
      AND time > now() - ($2 || ' days')::interval
    GROUP BY h, device_id
), loadh AS (
    SELECT h, GREATEST(0, sum(pv + g - b)) AS load_w FROM per GROUP BY h
)
SELECT extract(isodow from (h AT TIME ZONE 'Europe/Prague'))::int AS dow,
       extract(hour   from (h AT TIME ZONE 'Europe/Prague'))::int AS hh,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY load_w) AS med
FROM loadh GROUP BY dow, hh
"""


async def build_profile(device_ids: list[str], days: int = 42) -> dict:
    """{(isodow, hour) -> medián load_w} z posledních `days` dní."""
    if not device_ids:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_PROFILE_SQL, device_ids, str(days))
    return {(r["dow"], r["hh"]): float(r["med"] or 0) for r in rows}


def project_profile(profile: dict, grid_ts: list[datetime]) -> list[dict]:
    """Promítne profil na časové body předpovědi (stejný grid jako pv_forecast)."""
    if not profile:
        return []
    import zoneinfo
    try:
        tz = zoneinfo.ZoneInfo("Europe/Prague")
    except Exception:
        tz = timezone.utc
    vals = list(profile.values())
    overall = sorted(vals)[len(vals) // 2] if vals else 0.0   # medián jako fallback
    out = []
    for ts in grid_ts:
        loc = ts.astimezone(tz)
        key = (loc.isoweekday(), loc.hour)
        out.append({"ts": ts, "load_w": profile.get(key, overall)})
    return out
