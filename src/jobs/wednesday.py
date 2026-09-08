"""
QuantB3 — Reconciliação de Carteira
Reconcilia a carteira no pregão B3 seguinte à negociação de ordens.
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from typing import Dict, List

from config.settings import SIMULATION_LABEL
from src.db.repositories import (
    finish_run,
    get_orders,
    get_prices,
    log_notification,
    start_run,
    upsert_equity,
    replace_positions_snapshot,
)
from src.notify.email_sender import send_reconcile_summary
from src.notify.telegram_sender import send_message
from src.jobs.trading_calendar import is_b3_trading_day, previous_b3_trading_day

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def run_wednesday_job(
    reconcile_date: date | None = None,
    strict_date: bool = False,
) -> dict:
    """
    Reconcilia somente as negociações do pregão B3 imediatamente anterior.

    Args:
        reconcile_date: Data operacional (default: hoje)
        strict_date: Rejeita uma data sem pregão, para execuções manuais.

    Returns:
        Dict com resultado do job
    """
    if reconcile_date is None:
        reconcile_date = date.today()

    run_id = start_run("portfolio_reconciliation")
    log_lines = []

    try:
        logger.info(f"=== RECONCILIAÇÃO DE CARTEIRA: {reconcile_date} ===")
        log_lines.append(f"Data operacional: {reconcile_date}")

        if not is_b3_trading_day(reconcile_date):
            message = f"{reconcile_date} não é pregão B3; não há reconciliação a executar."
            logger.info(message)
            log_lines.append(f"SKIPPED: {message}")
            if strict_date:
                raise ValueError(message)
            finish_run(run_id, "skipped", "\n".join(log_lines))
            return {"status": "skipped", "reason": "market_closed", "reconcile_date": reconcile_date}

        # 1. Carregar somente as ordens negociadas no pregão anterior.
        exec_date = previous_b3_trading_day(reconcile_date)
        logger.info(f"1. Carregando ordens executadas em {exec_date}...")

        filled_orders = get_orders(
            start_date=exec_date,
            end_date=exec_date,
            status="FILLED",
        )

        if not filled_orders:
            message = f"Sem ordens FILLED para {exec_date}; nenhuma reconciliação é necessária."
            logger.info(message)
            log_lines.append(f"SKIPPED: {message}")
            finish_run(run_id, "skipped", "\n".join(log_lines))
            return {"status": "skipped", "reason": "no_filled_dependency", "n_positions": 0}

        logger.info(f"   {len(filled_orders)} ordens FILLED")
        log_lines.append(f"Ordens FILLED: {len(filled_orders)}")

        # 2. Reconstruir posições a partir das ordens
        logger.info("2. Reconstruindo posições...")
        cash, positions, _ = _rebuild_portfolio_from_ledger()

        # 3. Carregar preços atuais para valorização
        logger.info("3. Carregando preços para valorização...")
        prices_df = get_prices(
            start_date=reconcile_date,
            end_date=reconcile_date,
        )

        if prices_df.empty:
            # Usa preços do dia anterior
            prices_df = get_prices(
                start_date=exec_date,
                end_date=exec_date,
            )

        prices_close = {}
        if not prices_df.empty:
            prices_close = prices_df.set_index("ticker")["c"].to_dict()

        # 4. Calcular equity usando o caixa reconstruído do razão
        pos_value = sum(
            pos["qty"] * float(prices_close.get(ticker, pos["avg_price"]))
            for ticker, pos in positions.items()
        )
        equity = cash + pos_value

        # 5. Persistir posições
        logger.info("4. Persistindo posições...")
        positions_list = [
            {
                "ticker": ticker,
                "qty": pos["qty"],
                "avg_price": pos["avg_price"],
                "stop_price": pos.get("stop"),
                "take_price": pos.get("take"),
            }
            for ticker, pos in positions.items()
            if pos["qty"] > 0
        ]

        n_pos = replace_positions_snapshot(positions_list, reconcile_date)
        log_lines.append(f"Posições persistidas: {n_pos}")

        # 6. Atualizar equity oficial
        upsert_equity(
            date_val=reconcile_date,
            equity=equity,
            cash=cash,
            pos_value=pos_value,
            n_positions=len(positions),
        )
        log_lines.append(f"Equity: R$ {equity:.2f}")

        # 7. Gerar resumo de reconciliação
        summary = _generate_reconcile_summary(
            reconcile_date=reconcile_date,
            positions=positions,
            prices_close=prices_close,
            equity=equity,
            cash=cash,
            pos_value=pos_value,
            n_filled=len(filled_orders),
        )

        # 8. Notificar
        logger.info("5. Enviando notificações...")
        date_str = reconcile_date.strftime("%d/%m/%Y")

        tg_ok = send_message(f"<pre>{summary}</pre>")
        log_notification("telegram", "reconcile", summary[:500],
                         "sent" if tg_ok else "failed")

        email_ok = send_reconcile_summary(summary, date_str)
        log_notification("email", "reconcile", summary[:500],
                         "sent" if email_ok else "failed")

        log_lines.append(f"Telegram: {'OK' if tg_ok else 'FALHOU'}")
        log_lines.append(f"E-mail: {'OK' if email_ok else 'FALHOU'}")

        logger.info("=== RECONCILIAÇÃO DE CARTEIRA CONCLUÍDA ===")
        finish_run(run_id, "success", "\n".join(log_lines))

        return {
            "status": "success",
            "reconcile_date": reconcile_date,
            "n_positions": len(positions),
            "equity": equity,
            "summary": summary,
        }

    except Exception as e:
        logger.error(f"Erro na reconciliação de carteira: {e}", exc_info=True)
        log_lines.append(f"ERRO: {e}")
        finish_run(run_id, "error", "\n".join(log_lines))
        raise


def _rebuild_positions_from_orders(
    filled_orders: List[Dict],
) -> Dict[str, Dict]:
    """
    Reconstrói posições a partir do histórico de ordens FILLED.
    Considera todas as ordens desde o início da simulação.
    """
    from src.execution.ledger import rebuild_portfolio_from_orders
    _, positions, _ = rebuild_portfolio_from_orders(filled_orders)
    return positions


def _rebuild_portfolio_from_ledger() -> tuple[float, Dict[str, Dict], List[str]]:
    """Retorna o estado oficial, derivado de todo o histórico FILLED."""
    from src.db.repositories import get_orders as _get_all_orders
    from src.execution.ledger import rebuild_portfolio_from_orders
    return rebuild_portfolio_from_orders(_get_all_orders(status="FILLED"))


def _generate_reconcile_summary(
    reconcile_date: date,
    positions: Dict[str, Dict],
    prices_close: Dict[str, float],
    equity: float,
    cash: float,
    pos_value: float,
    n_filled: int,
) -> str:
    """Gera resumo de reconciliação."""
    lines = [
        "=" * 50,
        "QUANTB3 | RECONCILIAÇÃO DE CARTEIRA",
        f"⚠️  {SIMULATION_LABEL}",
        f"Data: {reconcile_date.strftime('%d/%m/%Y')}",
        "=" * 50,
        "",
        f"Ordens executadas na terça: {n_filled}",
        f"Posições ativas: {len(positions)}",
        "",
        f"{'Ticker':<12} {'Qtd':>6} {'P.Médio':>10} {'P.Atual':>10} {'P&L':>10} {'P&L%':>7}",
        "-" * 55,
    ]

    total_pl = 0.0
    for ticker, pos in sorted(positions.items()):
        qty = pos["qty"]
        avg = pos["avg_price"]
        current = prices_close.get(ticker, avg)
        pl = qty * (current - avg)
        pl_pct = (current / avg - 1) * 100 if avg > 0 else 0
        total_pl += pl

        lines.append(
            f"{ticker:<12} {qty:>6} R${avg:>8.2f} R${current:>8.2f} "
            f"R${pl:>8.2f} {pl_pct:>6.1f}%"
        )

    lines += [
        "-" * 55,
        f"{'TOTAL P&L:':<30} R${total_pl:>8.2f}",
        "",
        f"Caixa:     R$ {cash:,.2f}",
        f"Posições:  R$ {pos_value:,.2f}",
        f"Patrimônio: R$ {equity:,.2f}",
        "",
        "=" * 50,
    ]

    return "\n".join(lines)
if __name__ == "__main__":
    result = run_wednesday_job()
    print(result.get("summary", "Sem resumo"))
