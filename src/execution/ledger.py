"""Razão determinístico da carteira simulada.

O estado oficial (caixa e posições) é sempre derivado das ordens ``FILLED``.
Snapshots de equity são somente uma visão do razão; nunca sua fonte.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, List, Tuple

from config.settings import CAPITAL, SLIPPAGE_STOP, SLIPPAGE_TAKE, STOP_PCT, TAKE_RR


def rebuild_portfolio_from_orders(
    orders: Iterable[Dict], capital: float = CAPITAL
) -> Tuple[float, Dict[str, Dict], List[str]]:
    """Reconstrói caixa e posições exclusivamente a partir de ordens executadas.

    Uma inconsistência no livro (preço inválido, venda maior que a posição ou
    caixa negativo) interrompe a reconciliação. Escrever um snapshot incorreto
    é pior que manter o snapshot anterior para investigação.
    """
    cash = float(capital)
    positions: Dict[str, Dict] = {}
    warnings: List[str] = []

    filled = [o for o in orders if o.get("status") == "FILLED"]

    # O simulador executa vendas antes de compras para liberar caixa no mesmo
    # pregão. A reconstrução do razão deve obedecer à mesma regra; ordenar
    # apenas por ``id`` poderia debitar uma compra antes do crédito de uma
    # venda planejada para a mesma data.
    side_priority = {"SELL": 0, "STOP": 0, "TAKE": 0, "BUY": 1}
    filled.sort(
        key=lambda o: (
            o.get("exec_date") or date.min,
            side_priority.get(str(o.get("side") or "").upper(), 2),
            o.get("id") or 0,
        )
    )

    for order in filled:
        ticker = str(order.get("ticker") or "").strip()
        side = str(order.get("side") or "").upper()
        qty = int(order.get("qty") or 0)
        price = float(order.get("price") or 0)
        cost = float(order.get("cost") or 0)

        if not ticker or qty <= 0 or price <= 0 or cost < 0:
            raise ValueError(f"Ordem FILLED inválida no razão: id={order.get('id')}")

        if side == "BUY":
            debit = qty * price + cost
            if debit > cash + 1e-6:
                raise ValueError(
                    f"Caixa negativo ao processar ordem id={order.get('id')} ({ticker})"
                )
            cash -= debit
            previous = positions.get(ticker)
            if previous:
                total_qty = previous["qty"] + qty
                avg_price = (
                    previous["qty"] * previous["avg_price"] + qty * price
                ) / total_qty
            else:
                total_qty, avg_price = qty, price

            stop = price * (1 + STOP_PCT) * (1 - SLIPPAGE_STOP)
            risk = price - stop
            take = (price + risk * TAKE_RR) * (1 - SLIPPAGE_TAKE)
            positions[ticker] = {
                "qty": total_qty,
                "avg_price": avg_price,
                "stop": stop,
                "take": take,
            }
        elif side in {"SELL", "STOP", "TAKE"}:
            previous = positions.get(ticker)
            if previous is None or qty > previous["qty"]:
                raise ValueError(
                    f"Venda sem posição suficiente no razão: id={order.get('id')} ({ticker})"
                )
            cash += qty * price - cost
            remaining = previous["qty"] - qty
            if remaining:
                positions[ticker] = {**previous, "qty": remaining}
            else:
                del positions[ticker]
        else:
            raise ValueError(f"Lado de ordem inválido no razão: id={order.get('id')}")

    return cash, positions, warnings
