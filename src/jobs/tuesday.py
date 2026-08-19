"""
QuantB3 — Job de Terça-feira
Executa ordens pendentes com preço triangular simulado.
Gera notas de negociação e notifica.

Executado via GitHub Actions toda terça após o fechamento (~18:30 BRT).
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from typing import Dict
from src.data.collector import update_prices
from src.db.repositories import (
    cancel_order,
    fill_order,
    finish_run,
    get_pending_orders,
    get_prices,
    log_notification,
    start_run,
    upsert_equity,
)
from src.execution.simulator import execute_pending_orders
from src.notify.email_sender import send_trade_notes
from src.notify.telegram_sender import send_report
from src.reporting.signal_report import generate_trade_notes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def run_tuesday_job(exec_date: date = None, seed: int = 42) -> dict:
    """
    Executa o job completo de terça-feira.

    Args:
        exec_date: Data de execução (default: hoje)
        seed: Semente aleatória para preço triangular

    Returns:
        Dict com resultado do job
    """
    if exec_date is None:
        exec_date = date.today()

    run_id = start_run("tuesday")
    log_lines = []

    try:
        logger.info(f"=== JOB TERÇA-FEIRA: {exec_date} ===")
        log_lines.append(f"Iniciando job terça: {exec_date}")

        # 1. Atualizar preços do dia
        logger.info("1. Atualizando preços...")
        n_rows = update_prices()
        log_lines.append(f"Preços atualizados: {n_rows} registros")

        # 2. Carregar ordens pendentes
        logger.info("2. Carregando ordens pendentes...")
        signal_date = _prev_monday(exec_date)
        pending = get_pending_orders(signal_date)

        if not pending:
            logger.warning(f"Sem ordens pendentes para {signal_date}")
            log_lines.append("Sem ordens pendentes")
            finish_run(run_id, "success", "\n".join(log_lines))
            return {"status": "success", "n_executed": 0}

        logger.info(f"   {len(pending)} ordens pendentes")
        log_lines.append(f"Ordens pendentes: {len(pending)}")

        # 3. Carregar OHLCV do dia de execução
        logger.info("3. Carregando OHLCV do dia...")
        prices_df = get_prices(
            start_date=exec_date,
            end_date=exec_date,
        )

        if prices_df.empty:
            raise ValueError(f"Sem dados OHLCV para {exec_date}")

        # 4. Reconstruir estado a partir do razão, nunca do último snapshot.
        from src.db.repositories import get_orders
        from src.execution.ledger import rebuild_portfolio_from_orders
        cash, positions, _ = rebuild_portfolio_from_orders(get_orders(status="FILLED"))

        # 5. Executar ordens
        logger.info("4. Executando ordens...")
        new_cash, new_positions, executed, notes, cancelled = execute_pending_orders(
            pending_orders=pending,
            prices_day=prices_df,
            exec_date=exec_date,
            cash=cash,
            positions=positions,
            seed=seed,
        )

        # 6. Atualizar ordens no banco
        for order_filled in executed:
            order_id = order_filled.get("id")
            if order_id:
                fill_order(
                    order_id,
                    order_filled["price"],
                    order_filled["cost"],
                    exec_date,
                    order_filled["qty"],
                )

        for order_cancelled in cancelled:
            order_id = order_cancelled.get("id")
            if order_id:
                cancel_order(order_id, order_cancelled["reason"])

        # 7. Calcular novo valor das posições
        prices_close = prices_df.set_index("ticker")["c"]
        new_pos_value = sum(
            pos["qty"] * float(prices_close.get(ticker, pos["avg_price"]))
            for ticker, pos in new_positions.items()
        )
        new_equity = new_cash + new_pos_value

        # 8. Registrar equity provisório (será confirmado na quarta)
        upsert_equity(
            date_val=exec_date,
            equity=new_equity,
            cash=new_cash,
            pos_value=new_pos_value,
            n_positions=len(new_positions),
        )

        log_lines.append(f"Ordens executadas: {len(executed)}")
        log_lines.append(f"Ordens canceladas: {len(cancelled)}")
        log_lines.append(f"Equity após execução: R$ {new_equity:.2f}")

        # 9. Gerar notas de negociação
        logger.info("5. Gerando notas de negociação...")
        trade_notes = generate_trade_notes(
            exec_date=exec_date,
            executed_orders=executed,
            cash_after=new_cash,
            pos_value_after=new_pos_value,
        )

        # 10. Enviar notificações
        logger.info("6. Enviando notificações...")
        date_str = exec_date.strftime("%d/%m/%Y")

        tg_ok = send_report(trade_notes, "trade_notes", date_str)
        log_notification("telegram", "trade_notes", trade_notes[:500],
                         "sent" if tg_ok else "failed")

        email_ok = send_trade_notes(trade_notes, date_str)
        log_notification("email", "trade_notes", trade_notes[:500],
                         "sent" if email_ok else "failed")

        log_lines.append(f"Telegram: {'OK' if tg_ok else 'FALHOU'}")
        log_lines.append(f"E-mail: {'OK' if email_ok else 'FALHOU'}")

        logger.info("=== JOB TERÇA CONCLUÍDO ===")
        finish_run(run_id, "success", "\n".join(log_lines))

        return {
            "status": "success",
            "exec_date": exec_date,
            "n_executed": len(executed),
            "n_cancelled": len(cancelled),
            "new_equity": new_equity,
            "notes": trade_notes,
        }

    except Exception as e:
        logger.error(f"Erro no job de terça: {e}", exc_info=True)
        log_lines.append(f"ERRO: {e}")
        finish_run(run_id, "error", "\n".join(log_lines))
        raise


def _prev_monday(d: date) -> date:
    """Retorna a segunda-feira anterior a d."""
    days_back = d.weekday()  # 0=seg, 1=ter, ...
    return d - timedelta(days=days_back)


if __name__ == "__main__":
    result = run_tuesday_job()
    print(result.get("notes", "Sem notas"))
