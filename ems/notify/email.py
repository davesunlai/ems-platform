"""Odesílání e-mailů přes SMTP (Forpsi).

Konfigurace přes proměnné prostředí:
  EMS_SMTP_HOST=smtp.forpsi.com
  EMS_SMTP_PORT=465
  EMS_SMTP_SECURITY=ssl        # ssl (465) | starttls (587)
  EMS_SMTP_USER=ai@teraems.com
  EMS_SMTP_PASSWORD=...        # heslo schránky (v .env, ne v gitu)
  EMS_SMTP_FROM=ai@teraems.com
"""
from __future__ import annotations

import logging
import os
from email.message import EmailMessage

logger = logging.getLogger("ems.notify")


def smtp_configured() -> bool:
    return bool(os.getenv("EMS_SMTP_USER") and os.getenv("EMS_SMTP_PASSWORD"))


async def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    import aiosmtplib

    host = os.getenv("EMS_SMTP_HOST", "smtp.forpsi.com")
    port = int(os.getenv("EMS_SMTP_PORT", "465"))
    security = os.getenv("EMS_SMTP_SECURITY", "ssl").lower()
    user = os.getenv("EMS_SMTP_USER")
    password = os.getenv("EMS_SMTP_PASSWORD")
    sender = os.getenv("EMS_SMTP_FROM", user or "noreply@localhost")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    kwargs = {"hostname": host, "port": port, "username": user, "password": password}
    if security == "ssl":
        kwargs["use_tls"] = True
    else:
        kwargs["start_tls"] = True

    await aiosmtplib.send(msg, **kwargs)
    logger.info("E-mail odeslán na %s (%s)", to, subject)
