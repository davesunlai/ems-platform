"""Zdroj spotových cen (ČR / trh OTE).

Default provider: spotovaelektrina.cz (aktuální cena v Kč/MWh, zdarma).
Pro testování lze cenu nastavit ručně (manual override) přes API/DB.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ems.market")

ACTUAL_PRICE_URL = "https://spotovaelektrina.cz/api/v1/price/get-actual-price-czk"
DAY_PRICES_URL = "https://spotovaelektrina.cz/api/v1/price/get-prices-json"


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


async def fetch_day_prices() -> dict | None:
    """Vrátí hodinovou křivku cen pro dnešek a zítřek (Kč/MWh), nebo None.

    Zítřek bývá publikovaný cca po 14:00; do té doby může být prázdný.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(DAY_PRICES_URL)
            r.raise_for_status()
            data = r.json()

        def conv(arr):
            out = []
            for it in arr or []:
                if not isinstance(it, dict):
                    continue
                hr = it.get("hour", it.get("hourIndex"))
                pr = it.get("priceCZK", it.get("price"))
                if hr is not None and pr is not None:
                    try:
                        out.append({"hour": int(hr), "price": float(pr)})
                    except (TypeError, ValueError):
                        pass
            return sorted(out, key=lambda x: x["hour"])

        today = conv(data.get("hoursToday") or data.get("today"))
        tomorrow = conv(data.get("hoursTomorrow") or data.get("tomorrow"))
        if not today and not tomorrow:
            return None
        return {"today": today, "tomorrow": tomorrow}
    except Exception as exc:
        logger.warning("Načtení denní křivky selhalo: %s", exc)
        return None
