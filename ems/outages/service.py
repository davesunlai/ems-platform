"""Výběr identifikátoru dle priority (EAN → elektroměr → adresa), stažení a notifikace.

Notifikace stojí na sloupci last_notified v DB (ne na diffu při stahování):
  - úvodní mail při zavedení odstávky (last_notified IS NULL),
  - opakované připomenutí každých EMS_OUTAGE_REMIND_DAYS dní až do odstávky.
"""
from __future__ import annotations

import logging
import os
from zoneinfo import ZoneInfo

from ems.localities import db as loc_db
from . import db as outage_db
from .provider import CezOutageProvider

logger = logging.getLogger("ems.outages")
PRAGUE = ZoneInfo("Europe/Prague")

_provider = CezOutageProvider()


def remind_days() -> int:
    try:
        return int(os.getenv("EMS_OUTAGE_REMIND_DAYS", "2") or 0)
    except ValueError:
        return 0


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
    """Stáhne a uloží odstávky lokality (bez notifikace)."""
    q = query_for_locality(loc)
    if not q:
        return 0
    outages = await _provider.fetch(q)
    return await outage_db.upsert_many(loc["id"], outages)


async def notify_locality(loc: dict) -> int:
    """Pošle úvodní mail / připomenutí na odstávky, které to dle pravidla potřebují."""
    rows = await outage_db.due_for_notification(loc["id"], remind_days())
    if not rows:
        return 0
    users = await loc_db.users_with_email_for_locality(loc["id"])
    if not users:
        return 0  # nemarkujeme – až přibude uživatel, dostane oznámení
    await _send(loc, users, rows)
    await outage_db.mark_notified([r["uid"] for r in rows])
    return len(rows)


async def _send(loc: dict, users: list[dict], rows: list[dict]) -> None:
    from ems.notify.email import send_email
    from ems.notify.templates import html_mail

    base = os.getenv("EMS_BASE_URL", "http://localhost:8080").rstrip("/")
    lines = []
    for r in sorted(rows, key=lambda x: x["start_at"]):
        s = r["start_at"].astimezone(PRAGUE).strftime("%d.%m.%Y %H:%M")
        e = r["end_at"].astimezone(PRAGUE).strftime("%H:%M")
        loc_str = (" – " + r["locations"]) if r.get("locations") else ""
        lines.append(f"{s}–{e}{loc_str}")
    paragraphs = [f"V lokalitě <strong>{loc.get('name')}</strong> je plánovaná odstávka elektřiny:"] + lines
    subject = f"TERA EMS – plánovaná odstávka: {loc.get('name')}"
    html = html_mail(
        "Plánovaná odstávka elektřiny", paragraphs, "Otevřít TERA EMS", base,
        "Tuto zprávu odeslal systém TERA EMS automaticky. Připomenutí chodí až do termínu odstávky.")
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
            sent = await notify_locality(loc)
            logger.info("Odstávky [%s]: načteno %d, oznámeno %d", loc.get("name"), n, sent)
        except Exception as exc:
            logger.warning("Odstávky [%s] selhaly: %s", loc.get("name"), exc)
