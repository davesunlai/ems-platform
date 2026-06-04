"""Výběr identifikátoru dle priority (EAN → elektroměr → adresa) + stažení odstávek."""
from __future__ import annotations

import logging

from ems.localities import db as loc_db
from . import db as outage_db
from .provider import CezOutageProvider

logger = logging.getLogger("ems.outages")

_provider = CezOutageProvider()


def query_for_locality(loc: dict) -> dict | None:
    """Vrátí payload pro ČEZ podle první vyplněné možnosti, jinak None."""
    ean = (loc.get("cez_ean") or "").strip()
    if ean:
        return {"eans": [ean]}
    meter = (loc.get("cez_meter") or "").strip()
    if meter:
        return {"meterNumbers": [meter]}
    psc = (loc.get("addr_zip") or "").strip()
    mesto = (loc.get("addr_city") or "").strip()
    ulice = (loc.get("addr_street") or "").strip()
    if psc and mesto:
        q = {"psc": psc, "mesto": mesto}
        if ulice:
            q["ulice"] = ulice
        return q
    return None


def query_kind(loc: dict) -> str | None:
    q = query_for_locality(loc)
    if not q:
        return None
    if "eans" in q:
        return "EAN"
    if "meterNumbers" in q:
        return "číslo elektroměru"
    return "adresa"


async def refresh_locality(loc: dict) -> int:
    q = query_for_locality(loc)
    if not q:
        return 0
    outages = await _provider.fetch(q)
    return await outage_db.upsert_many(loc["id"], outages)


async def refresh_all() -> None:
    await outage_db.prune_old()
    locs = await loc_db.list_all()
    for loc in locs:
        if query_for_locality(loc) is None:
            continue
        try:
            n = await refresh_locality(loc)
            logger.info("Odstávky [%s]: načteno %d", loc.get("name"), n)
        except Exception as exc:
            logger.warning("Odstávky [%s] selhaly: %s", loc.get("name"), exc)
