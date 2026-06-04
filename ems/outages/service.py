"""Výběr identifikátoru dle priority (EAN → elektroměr → adresa) + stažení odstávek."""
from __future__ import annotations

import logging
import os

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


async def refresh_locality(loc: dict, notify: bool = True) -> int:
    q = query_for_locality(loc)
    if not q:
        return 0
    before = await outage_db.existing_uids(loc["id"])
    outages = await _provider.fetch(q)
    n = await outage_db.upsert_many(loc["id"], outages)
    new = [o for o in outages if o.uid not in before]
    if notify and new:
        try:
            await _notify_new(loc, new)
        except Exception as exc:
            logger.warning("Notifikace odstávek [%s] selhala: %s", loc.get("name"), exc)
    return n


async def _notify_new(loc: dict, new_outages: list) -> None:
    from ems.notify.email import send_email
    from ems.notify.templates import html_mail

    users = await loc_db.users_with_email_for_locality(loc["id"])
    if not users:
        return
    base = os.getenv("EMS_BASE_URL", "http://localhost:8080").rstrip("/")
    lines = []
    for o in sorted(new_outages, key=lambda x: x.start):
        s = o.start.strftime("%d.%m.%Y %H:%M")
        e = o.end.strftime("%H:%M")
        loc_str = (" – " + "; ".join(o.locations)) if o.locations else ""
        lines.append(f"{s}–{e}{loc_str}")
    paragraphs = [f"V lokalitě <strong>{loc.get('name')}</strong> je nově plánovaná odstávka elektřiny:"] + lines
    subject = f"TERA EMS – plánovaná odstávka: {loc.get('name')}"
    html = html_mail(
        "Plánovaná odstávka elektřiny", paragraphs, "Otevřít TERA EMS", base,
        "Tuto zprávu odeslal systém TERA EMS automaticky při zjištění nové odstávky z portálu distributora.")
    body = subject + "\n\n" + "\n".join(lines) + f"\n\n{base}"
    for u in users:
        try:
            await send_email(u["email"], subject, body, html=html)
        except Exception as exc:
            logger.warning("E-mail odstávky na %s selhal: %s", u.get("email"), exc)


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
