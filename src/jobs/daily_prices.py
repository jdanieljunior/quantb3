"""
QuantB3 — Preços e Marcação Diária a Mercado
Mantém preços, posições e patrimônio atualizados no fechamento B3.

Executado via GitHub Actions todo dia útil (~19:00 BRT).
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.data.collector import update_prices
from src.db.repositories import finish_run, get_latest_price_date, start_run
from src.jobs.daily_mark_to_market import mark_portfolio_to_market

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")


def run_daily_prices_job() -> dict:
    """Atualiza OHLCV e registra o snapshot diário pelo fechamento B3."""
    run_id = start_run("daily_prices")
    log_lines = []

    try:
        operational_date = datetime.now(BRAZIL_TZ).date()
        logger.info(f"=== PREÇOS E MARCAÇÃO DIÁRIA: {operational_date} ===")

        latest = get_latest_price_date()
        log_lines.append(f"Última data no banco: {latest}")
        logger.info(f"Última data no banco: {latest}")

        n_rows = update_prices()
        log_lines.append(f"Registros atualizados: {n_rows}")
        logger.info(f"Registros atualizados: {n_rows}")

        latest_after_update = get_latest_price_date()
        if latest_after_update != operational_date:
            message = (
                "Sem fechamento novo para marcação a mercado em "
                f"{operational_date}; último disponível: {latest_after_update}."
            )
            logger.info(message)
            log_lines.append(f"SKIPPED: {message}")
            finish_run(run_id, "skipped", "\n".join(log_lines))
            return {
                "status": "skipped",
                "reason": "no_current_close",
                "n_rows": n_rows,
                "latest_price_date": latest_after_update,
            }

        snapshot = mark_portfolio_to_market(operational_date)
        log_lines.append(
            "Snapshot: "
            f"equity=R$ {snapshot['equity']:.2f}; "
            f"caixa=R$ {snapshot['cash']:.2f}; "
            f"posições={snapshot['n_positions']}"
        )
        logger.info("Snapshot diário concluído: %s", snapshot)

        finish_run(run_id, "success", "\n".join(log_lines))
        return {"status": "success", "n_rows": n_rows, **snapshot}

    except Exception as e:
        logger.error(f"Erro no job de preços: {e}", exc_info=True)
        log_lines.append(f"ERRO: {e}")
        finish_run(run_id, "error", "\n".join(log_lines))
        raise


if __name__ == "__main__":
    result = run_daily_prices_job()
    print(f"Resultado: {result}")
