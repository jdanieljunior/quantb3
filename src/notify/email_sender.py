"""Notificacoes por e-mail via Brevo, Resend ou SMTP."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

import requests

from config.settings import (
    EMAIL_API_KEY,
    EMAIL_FROM,
    EMAIL_PROVIDER,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PASSWORD,
    EMAIL_SMTP_PORT,
    EMAIL_TO,
)
from src.db.repositories import get_email_recipients

logger = logging.getLogger(__name__)


def send_email(
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
    to_email: Optional[str] = None,
) -> bool:
    """Envia e-mail aos destinatarios ativos configurados no dashboard."""
    if to_email:
        recipients = [to_email]
    else:
        recipients = [row["email"] for row in get_email_recipients(active_only=True)]
        if not recipients and EMAIL_TO:
            recipients = [EMAIL_TO]

    if not recipients:
        logger.warning("No email recipients are configured")
        return False

    provider = EMAIL_PROVIDER.lower()
    if provider not in {"brevo", "resend", "smtp"}:
        logger.error("Unknown email provider: %s", provider)
        return False
    if provider in {"brevo", "resend"} and not EMAIL_API_KEY:
        logger.warning("Email provider API key is missing")
        return False
    if provider == "smtp" and not EMAIL_SMTP_PASSWORD:
        logger.warning("SMTP password is missing")
        return False
    if not EMAIL_FROM:
        logger.warning("Sender email is missing")
        return False

    results = []
    for recipient in recipients:
        if provider == "brevo":
            results.append(_send_brevo(subject, body_text, body_html, recipient))
        elif provider == "resend":
            results.append(_send_resend(subject, body_text, body_html, recipient))
        else:
            results.append(_send_smtp(subject, body_text, body_html, recipient))
    return all(results)


def _send_brevo(subject: str, body_text: str, body_html: Optional[str], recipient: str) -> bool:
    """Envia via Brevo API v3."""
    payload = {
        "sender": {"name": "QuantB3", "email": EMAIL_FROM},
        "to": [{"email": recipient}],
        "subject": subject,
        "htmlContent": body_html or f"<pre style='font-family:monospace'>{body_text}</pre>",
        "textContent": body_text,
    }
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers={"accept": "application/json", "api-key": EMAIL_API_KEY, "content-type": "application/json"},
            timeout=30,
        )
        if response.ok:
            logger.info("Email sent via Brevo: %s", subject)
            return True
        logger.error("Brevo error %s: %s", response.status_code, response.text[:200])
    except Exception as error:
        logger.error("Brevo exception: %s", error)
    return False


def _send_resend(subject: str, body_text: str, body_html: Optional[str], recipient: str) -> bool:
    """Envia via Resend API."""
    payload = {
        "from": f"QuantB3 <{EMAIL_FROM}>",
        "to": [recipient],
        "subject": subject,
        "html": body_html or f"<pre style='font-family:monospace'>{body_text}</pre>",
        "text": body_text,
    }
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={"Authorization": f"Bearer {EMAIL_API_KEY}", "Content-Type": "application/json"},
            timeout=30,
        )
        if response.ok:
            logger.info("Email sent via Resend: %s", subject)
            return True
        logger.error("Resend error %s: %s", response.status_code, response.text[:200])
    except Exception as error:
        logger.error("Resend exception: %s", error)
    return False


def _send_smtp(subject: str, body_text: str, body_html: Optional[str], recipient: str) -> bool:
    """Envia via SMTP autenticado, incluindo Yahoo com senha de aplicativo."""
    message = EmailMessage()
    message["From"] = f"QuantB3 <{EMAIL_FROM}>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body_text)
    if body_html:
        message.add_alternative(body_html, subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, context=context, timeout=30) as server:
            server.login(EMAIL_FROM, EMAIL_SMTP_PASSWORD)
            server.send_message(message)
        logger.info("Email sent via SMTP: %s", subject)
        return True
    except Exception as error:
        logger.error("SMTP exception: %s", error)
        return False


def send_signal_report(report_text: str, signal_date: str) -> bool:
    return send_email(f"[QuantB3] Sinais {signal_date}", report_text)


def send_trade_notes(notes_text: str, exec_date: str) -> bool:
    return send_email(f"[QuantB3] Notas de Negociação {exec_date}", notes_text)


def send_reconcile_summary(summary: str, reconcile_date: str) -> bool:
    return send_email(f"[QuantB3] Reconciliação {reconcile_date}", summary)
