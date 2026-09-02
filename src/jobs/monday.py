"""
QuantB3 — Job de Segunda-feira
Gera sinais semanais, relatório e notificações.

Executado via GitHub Actions toda segunda após o fechamento (~18:30 BRT).
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config.settings import N_POSITIONS
from src.data.collector import update_prices
from src.db.repositories import (
    finish_run,
    get_prices,
    log_notification,
    replace_weekly_plan,
    start_run,
)
from src.model.ranking import prepare_weekly_orders
from src.model.train_predict import QuantB3Model
from src.notify.email_sender import send_signal_report
from src.notify.telegram_sender import send_report
from src.reporting.signal_report import generate_signal_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")


def _brazil_today() -> date:
    """Data operacional no horário de Brasília, independente do runner UTC."""
    return datetime.now(BRAZIL_TZ).date()


def run_monday_job(signal_date: date = None, seed: int = 42) -> dict:
    """
    Executa o job completo de segunda-feira.

    Args:
        signal_date: Data do sinal (default: hoje)
        seed: Semente aleatória

    Returns:
        Dict com resultado do job
    """
    if signal_date is None:
        signal_date = _brazil_today()

    run_id = start_run("monday")
    log_lines = []

    try:
        logger.info(f"=== JOB SEGUNDA-FEIRA: {signal_date} ===")
        log_lines.append(f"Iniciando job segunda: {signal_date}")

        # 1. Atualizar preços
        logger.info("1. Atualizando preços...")
        n_rows = update_prices()
        log_lines.append(f"Preços atualizados: {n_rows} registros")

        # 2. Carregar dados do banco
        logger.info("2. Carregando dados...")
        prices_df = get_prices()

        if prices_df.empty:
            raise ValueError("Sem dados de preços no banco")

        # Pivota para formato wide
        prices = prices_df.pivot(index="date", columns="ticker", values="c")
        highs = prices_df.pivot(index="date", columns="ticker", values="h")
        lows = prices_df.pivot(index="date", columns="ticker", values="l")
        volumes = prices_df.pivot(index="date", columns="ticker", values="v")

        prices.index = pd.to_datetime(prices.index)
        highs.index = pd.to_datetime(highs.index)
        lows.index = pd.to_datetime(lows.index)
        volumes.index = pd.to_datetime(volumes.index)

        # Benchmark BOVA11
        bova_df = prices_df[prices_df["ticker"] == "BOVA11.SA"]
        if not bova_df.empty:
            bova = bova_df.set_index("date")["c"]
            bova.index = pd.to_datetime(bova.index)
        else:
            # Fallback: usa média do universo
            bova = prices.mean(axis=1)

        # Remove benchmarks das ações
        benchmarks = ["BOVA11.SA", "SMAL11.SA", "^BVSP"]
        stock_cols = [c for c in prices.columns if c not in benchmarks]
        prices = prices[stock_cols]
        highs = highs[stock_cols] if all(c in highs.columns for c in stock_cols) else highs
        lows = lows[stock_cols] if all(c in lows.columns for c in stock_cols) else lows
        volumes = volumes[stock_cols] if all(c in volumes.columns for c in stock_cols) else volumes

        logger.info(f"   {prices.shape[0]} dias × {prices.shape[1]} tickers")
        log_lines.append(f"Dados: {prices.shape[0]} dias × {prices.shape[1]} tickers")

        # 3. Treinar modelo e gerar scores
        logger.info("3. Treinando modelo LGBM...")
        signal_ts = pd.Timestamp(signal_date)

        if signal_ts not in prices.index:
            last_price_date = prices.index.max().date()
            raise ValueError(
                "Não há preços de fechamento para a data operacional "
                f"{signal_date}; último pregão disponível: {last_price_date}. "
                "Execute o job após o fechamento ou informe uma data de pregão."
            )

        model = QuantB3Model(prices, volumes, bova)

        # Carteira atual derivada do razão (não de snapshots potencialmente defasados).
        from src.db.repositories import get_orders
        from src.execution.ledger import rebuild_portfolio_from_orders
        cash, ledger_positions, _ = rebuild_portfolio_from_orders(
            get_orders(status="FILLED")
        )
        current_positions = [
            {
                "ticker": ticker,
                "qty": position["qty"],
                "avg_price": position["avg_price"],
                "stop_price": position.get("stop"),
                "take_price": position.get("take"),
            }
            for ticker, position in ledger_positions.items()
        ]
        prev_portfolio = [p["ticker"] for p in current_positions]

        # Score na data do sinal
        scores, top_tickers = model.score_on_date(signal_ts, prev_portfolio)

        if not top_tickers:
            raise ValueError(f"Sem tickers ranqueados para {signal_date}")

        logger.info(f"   Top {N_POSITIONS}: {top_tickers}")
        log_lines.append(f"Top {N_POSITIONS}: {', '.join(top_tickers)}")

        # 4. Preços de referência (fechamento da segunda)
        if signal_ts in prices.index:
            ref_prices = prices.loc[signal_ts]
        else:
            ref_prices = prices.iloc[-1]

        # 5. Equity para a alocação: caixa reconstruído + posições a mercado.
        pos_value = sum(
            position["qty"] * float(ref_prices.get(ticker, position["avg_price"]))
            for ticker, position in ledger_positions.items()
        )
        equity = cash + pos_value

        # 6. Gerar ordens e sinais
        exec_date = _next_tuesday(signal_date)
        orders, signals_list = prepare_weekly_orders(
            top_tickers=top_tickers,
            scores=scores,
            current_positions=current_positions,
            prices=ref_prices,
            equity=equity,
            signal_date=signal_date,
            exec_date=exec_date,
        )

        # 7. Persistir no banco
        logger.info("4. Persistindo sinais e ordens...")
        order_ids = replace_weekly_plan(signal_date, signals_list, orders)
        n_signals = len(signals_list)
        log_lines.append(f"Sinais: {n_signals} | Ordens: {len(order_ids)}")

        # 8. Gerar relatório
        logger.info("5. Gerando relatório...")
        report = generate_signal_report(
            signal_date=signal_date,
            top_tickers=top_tickers,
            scores=scores,
            signals=signals_list,
            orders=orders,
            current_positions=current_positions,
            equity=equity,
            cash=cash,
            pos_value=pos_value,
        )

        # 9. Enviar notificações
        logger.info("6. Enviando notificações...")
        date_str = signal_date.strftime("%d/%m/%Y")

        tg_ok = send_report(report, "signal_report", date_str)
        log_notification(
            "telegram", "signal_report", report[:500],
            "sent" if tg_ok else "failed"
        )

        email_ok = send_signal_report(report, date_str)
        log_notification(
            "email", "signal_report", report[:500],
            "sent" if email_ok else "failed"
        )

        log_lines.append(f"Telegram: {'OK' if tg_ok else 'FALHOU'}")
        log_lines.append(f"E-mail: {'OK' if email_ok else 'FALHOU'}")

        logger.info("=== JOB SEGUNDA CONCLUÍDO ===")
        finish_run(run_id, "success", "\n".join(log_lines))

        return {
            "status": "success",
            "signal_date": signal_date,
            "top_tickers": top_tickers,
            "n_orders": len(orders),
            "report": report,
        }

    except Exception as e:
        logger.error(f"Erro no job de segunda: {e}", exc_info=True)
        log_lines.append(f"ERRO: {e}")
        finish_run(run_id, "error", "\n".join(log_lines))
        raise


def _next_tuesday(d: date) -> date:
    """Retorna a próxima terça-feira a partir de d."""
    days_ahead = 1 - d.weekday()  # 1 = terça
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


if __name__ == "__main__":
    result = run_monday_job()
    print(result.get("report", "Sem relatório"))
