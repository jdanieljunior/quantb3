"""Importa CSV do IBRX Model Watch para a área de auditoria do Supabase."""

from __future__ import annotations

import argparse

from src.db.repositories import upsert_market_event_staging
from src.events.staging import read_watch_staging


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", help="CSV UTF-8 com BOM do IBRX Model Watch")
    args = parser.parse_args()
    records = read_watch_staging(args.csv_path)
    count = upsert_market_event_staging(records)
    print(f"{count} eventos importados para market_event_staging; nenhum foi promovido.")


if __name__ == "__main__":
    main()
