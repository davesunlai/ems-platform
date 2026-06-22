"""Odesílání e-mailů přes SMTP (Forpsi).

Konfigurace přes proměnné prostředí:
  EMS_SMTP_HOST=smtp.forpsi.com
  EMS_SMTP_PORT=465
  EMS_SMTP_SECURITY=ssl        # ssl (465) | starttls (587)
  EMS_SMTP_USER=ai@teraems.com
  EMS_SMTP_PASSWORD=...        # heslo schránky (v .env, ne v gitu)
  EMS_SMTP_FROM=ai@teraems.com
  EMS_SMTP_FROM_NAME=TERA EMS   # zobrazované jméno odesílatele (volitelné)
"""
from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger("ems.notify")


def smtp_configured() -> bool:
    return bool(os.getenv("EMS_SMTP_USER") and os.getenv("EMS_SMTP_PASSWORD"))


async def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    import aiosmtplib

    host = os.getenv("EMS_SMTP_HOST", "smtp.forpsi.com")
    port = int(os.getenv("EMS_SMTP_PORT", "465"))
    security = os.getenv("EMS_SMTP_SECURITY", "").lower()
    # když není režim explicitně nastaven, odvoď ho z portu
    if security not in ("ssl", "starttls"):
        security = "ssl" if port == 465 else "starttls"
    user = os.getenv("EMS_SMTP_USER")
    password = os.getenv("EMS_SMTP_PASSWORD")
    sender = os.getenv("EMS_SMTP_FROM", user or "noreply@localhost")
    from_name = os.getenv("EMS_SMTP_FROM_NAME", "TERA EMS").strip()
    timeout = float(os.getenv("EMS_SMTP_TIMEOUT", "25"))

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, sender)) if from_name else sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    async def _send(p: int, sec: str) -> None:
        # KLÍČOVÉ: u implicitního TLS (465) MUSÍ být start_tls=False, jinak
        # aiosmtplib zkusí STARTTLS přes už šifrované spojení -> "Connection lost".
        kwargs = {"hostname": host, "port": p, "username": user, "password": password,
                  "timeout": timeout}
        if sec == "ssl":
            kwargs["use_tls"] = True
            kwargs["start_tls"] = False
        else:
            kwargs["use_tls"] = False
            kwargs["start_tls"] = True
        await aiosmtplib.send(msg, **kwargs)

    try:
        await _send(port, security)
    except Exception as exc:
        # fallback na druhý obvyklý režim (465/ssl <-> 587/starttls)
        alt_port, alt_sec = (587, "starttls") if security == "ssl" else (465, "ssl")
        logger.warning("SMTP %s:%s (%s) selhalo (%s) -> zkouším %s:%s (%s)",
                       host, port, security, exc, host, alt_port, alt_sec)
        await _send(alt_port, alt_sec)
    logger.info("E-mail odeslán na %s (%s)", to, subject)
