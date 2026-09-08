"""Marcação diária a mercado da carteira simulada.

O razão de ordens ``FILLED`` é a fonte de verdade. Este módulo apenas cria
snapshots diários de posições e patrimônio com o fechamento disponível.
"""

from __future__ import annotations

from datetime import date
from typing import Dict

from src.db.repositories import (
    get_orders,
    get_prices,
    replace_positions_snapshot,
    upsert_equity,
)
from src.execution.ledger import rebuild_portfolio_from_orders


def mark_portfolio_to_market(snapshot_date: date) -> Dict[str, float | int | date]:
    """Persiste a fotografia da carteira no fechamento de ``snapshot_date``.

    Uma posição sem fechamento no dia interrompe a atualização: gravar um
    patrimônio com preço defasado esconderia uma falha na coleta de dados.
    """
    cash, positions, _ = rebuild_portfolio_from_orders(
        get_orders(end_date=snapshot_date, status="FILLED")
    )

    tickers = sorted(positions)
    if tickers:
        prices_df = get_prices(
            tickers=tickers,
            start_date=snapshot_date,
            end_date=snapshot_date,
        )
        closes = prices_df.set_index("ticker")["c"].to_dict() if not prices_df.empty else {}
        missing = [ticker for ticker in tickers if ticker not in closes]
        if missing:
            raise ValueError(
                "Sem fechamento para posição(ões) em "
                f"{snapshot_date}: {', '.join(missing)}"
            )
    else:
        closes = {}

    positions_list = [
        {
            "ticker": ticker,
            "qty": position["qty"],
            "avg_price": position["avg_price"],
            "stop_price": position.get("stop"),
            "take_price": position.get("take"),
        }
        for ticker, position in positions.items()
    ]
    pos_value = sum(
        float(position["qty"]) * float(closes[ticker])
        for ticker, position in positions.items()
    )
    equity = float(cash) + pos_value

    replace_positions_snapshot(positions_list, snapshot_date)
    upsert_equity(
        date_val=snapshot_date,
        equity=equity,
        cash=float(cash),
        pos_value=pos_value,
        n_positions=len(positions),
    )

    return {
        "snapshot_date": snapshot_date,
        "cash": float(cash),
        "pos_value": pos_value,
        "equity": equity,
        "n_positions": len(positions),
    }
