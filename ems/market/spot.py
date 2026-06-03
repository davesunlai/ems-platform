"""Zdroj spotových cen (ČR / trh OTE).

Default provider: spotovaelektrina.cz (aktuální cena v Kč/MWh, zdarma).
Pro testování lze cenu nastavit ručně (manual override) přes API/DB.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ems.market")

ACTUAL_PRICE_URL = "https://spotovaelektrina.cz/api/v1/price/get-actual-price-czk"


async def fetch_current_price_czk() -> float | None:
    """Vrátí aktuální spotovou cenu v Kč/MWh, nebo None při chybě."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(ACTUAL_PRICE_URL)
            r.raise_for_status()
            txt = r.text.strip()
            try:
                return float(txt)
            except ValueError:
                data = r.json()
                if isinstance(data, (int, float)):
                    return float(data)
                if isinstance(data, dict):
                    for k in ("price", "priceCZK", "value", "data"):
                        if k in data and isinstance(data[k], (int, float)):
                            return float(data[k])
        return None
    except Exception as exc:
        logger.warning("Načtení spotové ceny selhalo: %s", exc)
        return None
