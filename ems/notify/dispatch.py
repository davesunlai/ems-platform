"""Server-side rozesílání notifikací o nových výstrahách opt-in uživatelům.

Kanály:
- e-mail (SMTP) — řeší se tady,
- prohlížeč — řeší klient (polluje /api/alerts a zobrazí Notification, když je appka otevřená).

Dedup přes notification_log, takže každá výstraha jde mailem jen jednou.
"""
from __future__ import annotations

import logging

from ems.auth import db as auth_db
from ems.localities import db as loc_db
from ems.alerts import service as alerts
from . import email as mailer

logger = logging.getLogger("ems.notify")


async def notify_new_alerts() -> None:
    if not mailer.smtp_configured():
        return
    try:
        locs = await loc_db.list_all()
    except Exception as exc:
        logger.debug("notify: list_all: %s", exc)
        return
    for loc in locs:
        try:
            recips = await loc_db.notify_users_for_locality(loc["id"])
            if not recips:
                continue
            al = await alerts.collect_for_locality(loc)
            for a in al:
                for u in recips:
                    if not (u.get("notify_email") and u.get("email")):
                        continue
                    if await auth_db.notification_already_sent(u["id"], a["id"], "email"):
                        continue
                    subject = f"TERA EMS · {a.get('title', 'Upozornění')}"
                    body = (f"{a.get('title', '')}\n"
                            f"Lokalita: {loc.get('name', '')}\n"
                            f"{a.get('detail', '')}\n\n"
                            f"(Notifikace TERA EMS — nastavení kanálů najdeš v aplikaci.)")
                    try:
                        await mailer.send_email(u["email"], subject, body)
                        await auth_db.notification_mark_sent(u["id"], a["id"], "email")
                        logger.info("Notifikace mailem -> %s (%s)", u["email"], a["id"])
                    except Exception as exc:
                        logger.warning("notify mail %s: %s", u.get("email"), exc)
        except Exception as exc:
            logger.debug("notify lokalita %s: %s", loc.get("id"), exc)
