"""
QuantB3 — Notificações via Telegram Bot API
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_LENGTH = 4096


def send_message(
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    disable_notification: bool = False,
) -> bool:
    """
    Envia mensagem de texto via Telegram.
    Divide automaticamente se > 4096 caracteres.

    Returns:
        True se enviado com sucesso
    """
    token = TELEGRAM_BOT_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID

    if not token or not cid:
        logger.warning("Telegram não configurado (TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausente)")
        return False

    url = TELEGRAM_API.format(token=token, method="sendMessage")

    # Divide mensagens longas
    chunks = _split_message(text, MAX_MESSAGE_LENGTH)
    success = True

    for chunk in chunks:
        payload = {
            "chat_id": cid,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if not resp.ok:
                logger.error(f"Telegram erro {resp.status_code}: {resp.text[:200]}")
                success = False
        except Exception as e:
            logger.error(f"Telegram exceção: {e}")
            success = False

    return success


def send_document(
    text: str,
    filename: str,
    caption: str = "",
    chat_id: Optional[str] = None,
) -> bool:
    """
    Envia texto como arquivo .txt via Telegram.
    Útil para relatórios longos.
    """
    token = TELEGRAM_BOT_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID

    if not token or not cid:
        logger.warning("Telegram não configurado")
        return False

    url = TELEGRAM_API.format(token=token, method="sendDocument")

    try:
        files = {"document": (filename, text.encode("utf-8"), "text/plain")}
        data = {"chat_id": cid, "caption": caption[:1024]}
        resp = requests.post(url, data=data, files=files, timeout=60)
        if resp.ok:
            return True
        else:
            logger.error(f"Telegram documento erro {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Telegram documento exceção: {e}")
        return False


def send_report(
    report_text: str,
    kind: str,
    signal_date: str,
) -> bool:
    """
    Envia relatório completo — como mensagem se curto, como arquivo se longo.

    Args:
        report_text: Conteúdo do relatório
        kind: 'signal_report' ou 'trade_notes'
        signal_date: Data no formato DD/MM/AAAA
    """
    if kind == "signal_report":
        caption = f"📊 QuantB3 | Sinais {signal_date}"
        filename = f"quantb3_sinais_{signal_date.replace('/', '')}.txt"
    else:
        caption = f"📋 QuantB3 | Notas de Negociação {signal_date}"
        filename = f"quantb3_notas_{signal_date.replace('/', '')}.txt"

    if len(report_text) <= MAX_MESSAGE_LENGTH:
        # Envia como mensagem com formatação monospace
        return send_message(f"<pre>{report_text}</pre>")
    else:
        # Envia como arquivo
        return send_document(report_text, filename, caption)


def _split_message(text: str, max_len: int) -> list[str]:
    """Divide texto em chunks de no máximo max_len caracteres."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Tenta quebrar em linha
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks
