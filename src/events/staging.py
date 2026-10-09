"""Leitura fechada da base bruta do IBRX Model Watch."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {
    "event_id", "event_type", "ticker", "alert_date",
    "official_disclosure_date", "effective_from", "effective_to",
    "validation_status", "oos_enabled", "confirmed", "official_source_url",
    "secondary_source_url", "source_message_id", "event_stage",
    "validated_as_of", "notes",
}


def _bool(value: str, field: str, event_id: str) -> bool:
    normalized = (value or "").strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{event_id}: {field} deve ser true ou false")
    return normalized == "true"


def _parse_rows(reader: csv.DictReader) -> list[dict[str, Any]]:
    """Valida linhas brutas sem inferir datas, booleanos ou vigência."""
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise ValueError(f"CSV sem colunas obrigatórias: {', '.join(sorted(missing))}")

    records = []
    seen: set[str] = set()
    for row in reader:
        event_id = (row.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("CSV contém event_id vazio")
        if event_id in seen:
            raise ValueError(f"CSV contém event_id duplicado: {event_id}")
        seen.add(event_id)
        if not (row.get("event_type") or "").strip():
            raise ValueError(f"{event_id}: event_type é obrigatório")

        normalized = {key: (value.strip() if value else None) for key, value in row.items()}
        normalized["event_id"] = event_id
        normalized["oos_enabled"] = _bool(row.get("oos_enabled", ""), "oos_enabled", event_id)
        normalized["confirmed"] = _bool(row.get("confirmed", ""), "confirmed", event_id)
        records.append(normalized)
    return records


def read_watch_staging(path: str | Path) -> list[dict[str, Any]]:
    """Lê CSV UTF-8-BOM sem inferir datas, booleanos ou vigência.

    O resultado é adequado apenas à tabela de auditoria. A promoção para
    ``market_events`` acontece em fluxo separado, após validação documental.
    """
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        return _parse_rows(csv.DictReader(file))


def read_watch_staging_bytes(content: bytes) -> list[dict[str, Any]]:
    """Variante para upload do dashboard, com a mesma validação fechada."""
    return _parse_rows(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
