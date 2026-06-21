"""Samokalibrace PR: porovná dnešní PŘEDPOVĚZENOU vs SKUTEČNOU výrobu za uplynulé
hodiny a jemně doladí PR všech bloků lokality (model se srovná na střechu/stínění).

MVP: ratio = skutečná / předpovězená energie dneška (uplynulé hodiny); PR se
posune zlomkem k cíli (vyhlazení), ořez 0.30–0.98. Skutečná výroba z měniče
(energy_today) — odolné proti výpadkům.
"""
from __future__ import annotations

import logging

from ems.api.db import get_pool
from . import db as fdb

logger = logging.getLogger("ems.forecast")
SMOOTH = 0.3          # váha nové korekce (vyhlazení)
PR_MIN, PR_MAX = 0.30, 0.98


async def _actual_today_kwh(device_ids: list[str]) -> float:
    """Dnešní výroba z měniče (Σ latest energy_today přes zařízení)."""
    if not device_ids:
        return 0.0
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT COALESCE(SUM(v),0) FROM ("
            "  SELECT DISTINCT ON (device_id) value AS v FROM samples"
            "  WHERE device_id = ANY($1::text[]) AND metric='energy_today'"
            "    AND time > now() - interval '20 minutes' ORDER BY device_id, time DESC) t",
            device_ids)
    return float(v or 0)


async def _predicted_today_kwh(locality_id: int) -> float:
    """Předpovězená energie dneška za uplynulé hodiny (integrál pv_forecast 'avg')."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT COALESCE(SUM(pv_w),0)/1000.0 FROM pv_forecast "
            "WHERE locality_id=$1 AND source='avg' "
            "  AND fetched_at=(SELECT max(fetched_at) FROM pv_forecast WHERE locality_id=$1 AND source='avg') "
            "  AND ts >= date_trunc('day', now() AT TIME ZONE 'Europe/Prague') AT TIME ZONE 'Europe/Prague' "
            "  AND ts <= now()", locality_id)
    return float(v or 0)


async def calibrate(locality_id: int, device_ids: list[str]) -> float | None:
    """Doladí PR bloků lokality. Vrací použitý ratio (nebo None když nelze)."""
    predicted = await _predicted_today_kwh(locality_id)
    if predicted < 1.0:                       # málo dat / brzy ráno -> nekalibruj
        return None
    actual = await _actual_today_kwh(device_ids)
    if actual <= 0:
        return None
    ratio = actual / predicted
    ratio = max(0.5, min(2.0, ratio))         # ochrana proti odlehlým hodnotám
    blocks = await fdb.list_blocks(locality_id)
    for b in blocks:
        target = b["pr"] * ratio
        new_pr = max(PR_MIN, min(PR_MAX, b["pr"] * (1 - SMOOTH) + target * SMOOTH))
        if abs(new_pr - b["pr"]) > 0.001:
            await fdb.set_block_pr(b["id"], round(new_pr, 4))
    logger.info("Kalibrace PR lokalita %s: skut=%.1f pred=%.1f ratio=%.2f", locality_id, actual, predicted, ratio)
    return ratio
