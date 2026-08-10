"""
QuantB3 — Job Diário de Atualização de Preços
Mantém o banco atualizado e evita pausa do Supabase.

Executado via GitHub Actions todo dia útil (~19:00 BRT).
"""

from __future__ import annotations

import logging
import sys
from datetime import date

from src.data.collector import update_prices
from src.db.repositories import finish_run, get_latest_price_date, start_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def run_daily_prices_job() -> dict:
    """Atualiza preços OHLCV no banco de dados."""
    run_id = start_run("daily_prices")
    log_lines = []

    try:
        logger.info(f"=== JOB PREÇOS DIÁRIOS: {date.today()} ===")

        latest = get_latest_price_date()
        log_lines.append(f"Última data no banco: {latest}")
        logger.info(f"Última data no banco: {latest}")

        n_rows = update_prices()
        log_lines.append(f"Registros atualizados: {n_rows}")
        logger.info(f"Registros atualizados: {n_rows}")

        finish_run(run_id, "success", "\n".join(log_lines))
        return {"status": "success", "n_rows": n_rows}

    except Exception as e:
        logger.error(f"Erro no job de preços: {e}", exc_info=True)
        log_lines.append(f"ERRO: {e}")
        finish_run(run_id, "error", "\n".join(log_lines))
        raise


if __name__ == "__main__":
    result = run_daily_prices_job()
    print(f"Resultado: {result}")
