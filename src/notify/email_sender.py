"""
QuantB3 — Notificações por E-mail
Suporte a Brevo (SendinBlue) e Resend (ambos com free tier)
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from config.settings import (
    EMAIL_API_KEY,
    EMAIL_FROM,
    EMAIL_PROVIDER,
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
    """
    Envia e-mail via Brevo ou Resend.

    Args:
        subject: Assunto do e-mail
        body_text: Corpo em texto puro
        body_html: Corpo em HTML (opcional)
        to_email: Destinatário (default: EMAIL_TO)

    Returns:
        True se enviado com sucesso
    """
    if not EMAIL_API_KEY:
        logger.warning("E-mail não configurado (EMAIL_API_KEY ausente)")
        return False

    if to_email:
        recipients = [to_email]
    else:
        recipients = [row["email"] for row in get_email_recipients(active_only=True)]
        if not recipients and EMAIL_TO:
            recipients = [EMAIL_TO]

    if not recipients:
        logger.warning("E-mail não configurado (EMAIL_TO ausente)")
        return False

    provider = EMAIL_PROVIDER.lower()

    if provider not in {"brevo", "resend"}:
        logger.error(f"Provedor de e-mail desconhecido: {provider}")
        return False

    results = []
    for recipient in recipients:
        if provider == "brevo":
            results.append(_send_brevo(subject, body_text, body_html, recipient))
        else:
            results.append(_send_resend(subject, body_text, body_html, recipient))
    return all(results)


def _send_brevo(
    subject: str,
    body_text: str,
    body_html: Optional[str],
    recipient: str,
) -> bool:
    """Envia via Brevo (SendinBlue) API v3."""
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": EMAIL_API_KEY,
        "content-type": "application/json",
    }

    html = body_html or f"<pre style='font-family:monospace'>{body_text}</pre>"

    payload = {
        "sender": {"name": "QuantB3", "email": EMAIL_FROM},
        "to": [{"email": recipient}],
        "subject": subject,
        "htmlContent": html,
        "textContent": body_text,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.ok:
            logger.info(f"E-mail enviado via Brevo: {subject}")
            return True
        else:
            logger.error(f"Brevo erro {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Brevo exceção: {e}")
        return False


def _send_resend(
    subject: str,
    body_text: str,
    body_html: Optional[str],
    recipient: str,
) -> bool:
    """Envia via Resend API."""
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {EMAIL_API_KEY}",
        "Content-Type": "application/json",
    }

    html = body_html or f"<pre style='font-family:monospace'>{body_text}</pre>"

    payload = {
        "from": f"QuantB3 <{EMAIL_FROM}>",
        "to": [recipient],
        "subject": subject,
        "html": html,
        "text": body_text,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.ok:
            logger.info(f"E-mail enviado via Resend: {subject}")
            return True
        else:
            logger.error(f"Resend erro {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Resend exceção: {e}")
        return False


def send_signal_report(report_text: str, signal_date: str) -> bool:
    """Envia relatório de sinais por e-mail."""
    subject = f"[QuantB3] Sinais {signal_date}"
    return send_email(subject, report_text)


def send_trade_notes(notes_text: str, exec_date: str) -> bool:
    """Envia notas de negociação por e-mail."""
    subject = f"[QuantB3] Notas de Negociação {exec_date}"
    return send_email(subject, notes_text)


def send_reconcile_summary(summary: str, reconcile_date: str) -> bool:
    """Envia resumo de reconciliação por e-mail."""
    subject = f"[QuantB3] Reconciliação {reconcile_date}"
    return send_email(subject, summary)
