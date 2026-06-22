"""Denní kurz EUR→CZK z ČNB (textový kurzovní lístek, ~1× za pracovní den)."""
from __future__ import annotations

import logging
from datetime import date

from . import db as pdb

logger = logging.getLogger("ems.pricing")
CNB_URL = "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"


def parse_eur_czk(text: str) -> float | None:
    """Z kurzovního lístku ČNB vytáhne EUR (řádek 'země|měna|množství|kód|kurz')."""
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) >= 5 and parts[3].strip() == "EUR":
            try:
                amount = float(parts[2].strip().replace(",", "."))
                rate = float(parts[4].strip().replace(",", "."))
                return rate / amount if amount else rate
            except ValueError:
                return None
    return None


async def fetch_cnb_eur_czk() -> float | None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(CNB_URL)
            r.raise_for_status()
            return parse_eur_czk(r.text)
    except Exception as exc:
        logger.warning("ČNB kurz fetch selhal: %s", exc)
        return None


async def update_daily() -> float | None:
    """Stáhne dnešní kurz, jen pokud ještě není v cache."""
    latest = await pdb.latest_fx()
    if latest and latest["day"] >= date.today():
        return latest["eur_czk"]
    rate = await fetch_cnb_eur_czk()
    if rate:
        await pdb.save_fx(date.today(), rate)
        logger.info("ČNB kurz EUR/CZK = %.3f", rate)
    return rate
