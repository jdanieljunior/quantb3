"""
QuantB3 — Job de Quarta-feira
Reconcilia carteira, atualiza posições e equity oficial.

Executado via GitHub Actions toda quarta (~12:00 BRT).
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from typing import Dict, List

import pandas as pd

from config.settings import CAPITAL, SIMULATION_LABEL
from src.db.repositories import (
    finish_run,
    get_equity_curve,
    get_orders,
    get_prices,
    log_notification,
    start_run,
    upsert_equity,
    upsert_positions,
)
from src.notify.email_sender import send_reconcile_summary
from src.notify.telegram_sender import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def run_wednesday_job(reconcile_date: date = None) -> dict:
    """
    Executa o job completo de quarta-feira.

    Args:
        reconcile_date: Data de reconciliação (default: hoje)

    Returns:
        Dict com resultado do job
    """
    if reconcile_date is None:
        reconcile_date = date.today()

    run_id = start_run("wednesday")
    log_lines = []

    try:
        logger.info(f"=== JOB QUARTA-FEIRA: {reconcile_date} ===")
        log_lines.append(f"Iniciando job quarta: {reconcile_date}")

        # 1. Carregar ordens FILLED da terça
        exec_date = _prev_tuesday(reconcile_date)
        logger.info(f"1. Carregando ordens executadas em {exec_date}...")

        filled_orders = get_orders(
            start_date=exec_date,
            end_date=exec_date,
            status="FILLED",
        )

        if not filled_orders:
            logger.warning(f"Sem ordens FILLED para {exec_date}")
            log_lines.append("Sem ordens executadas para reconciliar")

        logger.info(f"   {len(filled_orders)} ordens FILLED")
        log_lines.append(f"Ordens FILLED: {len(filled_orders)}")

        # 2. Reconstruir posições a partir das ordens
        logger.info("2. Reconstruindo posições...")
        positions = _rebuild_positions_from_orders(filled_orders)

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

        # 4. Calcular equity
        equity_df = get_equity_curve()
        if not equity_df.empty:
            cash = float(equity_df.iloc[-1]["cash"])
        else:
            cash = CAPITAL

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

        n_pos = upsert_positions(positions_list, reconcile_date)
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

        logger.info("=== JOB QUARTA CONCLUÍDO ===")
        finish_run(run_id, "success", "\n".join(log_lines))

        return {
            "status": "success",
            "reconcile_date": reconcile_date,
            "n_positions": len(positions),
            "equity": equity,
            "summary": summary,
        }

    except Exception as e:
        logger.error(f"Erro no job de quarta: {e}", exc_info=True)
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
    from src.db.repositories import get_orders as _get_all_orders
    all_orders = _get_all_orders(status="FILLED")

    positions: Dict[str, Dict] = {}

    # Ordena por data de execução
    all_orders_sorted = sorted(all_orders, key=lambda x: (x.get("exec_date") or date.min, x.get("id") or 0))

    for order in all_orders_sorted:
        ticker = order["ticker"]
        side = order["side"]
        qty = order["qty"]
        price = order.get("price") or 0

        if side == "BUY":
            if ticker in positions:
                old = positions[ticker]
                total_qty = old["qty"] + qty
                avg_price = (old["qty"] * old["avg_price"] + qty * price) / total_qty if total_qty > 0 else price
                positions[ticker] = {**old, "qty": total_qty, "avg_price": avg_price}
            else:
                from config.settings import STOP_PCT, TAKE_RR, SLIPPAGE_STOP, SLIPPAGE_TAKE
                stop_p = price * (1 + STOP_PCT) * (1 - SLIPPAGE_STOP)
                risk = price - stop_p
                take_p = (price + risk * TAKE_RR) * (1 - SLIPPAGE_TAKE)
                positions[ticker] = {
                    "qty": qty,
                    "avg_price": price,
                    "stop": stop_p,
                    "take": take_p,
                }
        elif side in ("SELL", "STOP", "TAKE"):
            if ticker in positions:
                new_qty = positions[ticker]["qty"] - qty
                if new_qty <= 0:
                    del positions[ticker]
                else:
                    positions[ticker]["qty"] = new_qty

    return positions


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


def _prev_tuesday(d: date) -> date:
    """Retorna a terça-feira anterior a d."""
    days_back = (d.weekday() - 1) % 7
    return d - timedelta(days=days_back)


if __name__ == "__main__":
    result = run_wednesday_job()
    print(result.get("summary", "Sem resumo"))
