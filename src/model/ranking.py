"""
QuantB3 — Ranking e geração de ordens da semana
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import (
    CAPITAL,
    N_POSITIONS,
    STOP_PCT,
    TAKE_RR,
    SLIPPAGE_STOP,
    SLIPPAGE_TAKE,
)

logger = logging.getLogger(__name__)


def compute_risk_levels(
    entry_price: float,
    stop_pct: float = STOP_PCT,
    take_rr: float = TAKE_RR,
    slippage_stop: float = SLIPPAGE_STOP,
    slippage_take: float = SLIPPAGE_TAKE,
) -> Tuple[float, float]:
    """
    Calcula Stop Loss e Take Profit a partir do preço de entrada.

    Returns:
        (stop_price, take_price)
    """
    stop_price = entry_price * (1 + stop_pct) * (1 - slippage_stop)
    risk = entry_price - stop_price
    take_price = (entry_price + risk * take_rr) * (1 - slippage_take)
    return stop_price, take_price


def build_target_portfolio(
    top_tickers: List[str],
    prices: pd.Series,
    equity: float,
    n_positions: int = N_POSITIONS,
) -> Dict[str, int]:
    """
    Constrói a carteira-alvo com alocação igual.

    Args:
        top_tickers: Lista de tickers do ranking
        prices: Preços de fechamento da data do sinal
        equity: Valor total da carteira (caixa + posições)
        n_positions: Número de posições

    Returns:
        Dict ticker -> quantidade inteira
    """
    target_value = equity / n_positions
    orders = {}

    for ticker in top_tickers:
        price = prices.get(ticker, np.nan)
        if pd.isna(price) or price <= 0:
            logger.warning(f"Preço inválido para {ticker}: {price}")
            continue
        qty = int(target_value / price)
        if qty > 0:
            orders[ticker] = qty

    return orders


def diff_portfolios(
    current: Dict[str, int],
    target: Dict[str, int],
) -> Tuple[Dict[str, int], List[str], Dict[str, int]]:
    """
    Calcula a diferença entre carteira atual e carteira-alvo.

    Returns:
        (buys, sells, holds)
        buys: ticker -> quantidade a comprar (diff positivo)
        sells: lista de tickers a vender completamente
        holds: ticker -> quantidade mantida
    """
    all_tickers = set(current.keys()) | set(target.keys())
    buys: Dict[str, int] = {}
    sells: List[str] = []
    holds: Dict[str, int] = {}

    for ticker in all_tickers:
        cur_qty = current.get(ticker, 0)
        tgt_qty = target.get(ticker, 0)

        if tgt_qty == 0 and cur_qty > 0:
            sells.append(ticker)
        elif tgt_qty > 0 and cur_qty == 0:
            buys[ticker] = tgt_qty
        elif tgt_qty > 0 and cur_qty > 0:
            diff = tgt_qty - cur_qty
            if diff > 0:
                buys[ticker] = diff
                holds[ticker] = cur_qty
            elif diff < 0:
                # Redução de posição — trata como venda parcial
                sells.append(ticker)
                buys[ticker] = tgt_qty
            else:
                holds[ticker] = cur_qty

    return buys, sells, holds


def prepare_weekly_orders(
    top_tickers: List[str],
    scores: pd.Series,
    current_positions: List[Dict],
    prices: pd.Series,
    equity: float,
    signal_date: date,
    exec_date: date,
    n_positions: int = N_POSITIONS,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Prepara as ordens da semana (BUY/SELL/HOLD) para inserção no banco.

    Returns:
        (orders_list, signals_list)
    """
    # Carteira atual
    current = {p["ticker"]: p["qty"] for p in current_positions}

    # Carteira-alvo
    target = build_target_portfolio(top_tickers, prices, equity, n_positions)

    # Diff
    buys, sells, holds = diff_portfolios(current, target)

    orders = []
    signals_list = []

    # Rank dos tickers pelo score
    all_tickers_ranked = list(scores.sort_values(ascending=False).index)

    for rank, ticker in enumerate(all_tickers_ranked, 1):
        price = prices.get(ticker, np.nan)
        if pd.isna(price):
            continue

        stop_p, take_p = compute_risk_levels(price)

        # Determina ação
        if ticker in top_tickers:
            if ticker in buys:
                action = "BUY"
                qty = buys[ticker]
            elif ticker in sells:
                action = "SELL"
                qty = current.get(ticker, 0)
            else:
                action = "HOLD"
                qty = holds.get(ticker, target.get(ticker, 0))
        else:
            action = "OUT"
            qty = 0
            if ticker in sells:
                action = "SELL"
                qty = current.get(ticker, 0)

        # Sinal
        signals_list.append({
            "signal_date": signal_date,
            "ticker": ticker,
            "score": float(scores.get(ticker, 0)),
            "rank": rank,
            "action": action,
            "target_qty": target.get(ticker, 0),
            "ref_price": float(price),
            "stop_price": float(stop_p),
            "take_price": float(take_p),
        })

        # Ordem (apenas BUY e SELL)
        if action in ("BUY", "SELL") and qty > 0:
            orders.append({
                "signal_date": signal_date,
                "exec_date": exec_date,
                "ticker": ticker,
                "side": action,
                "qty": qty,
                "price": None,
                "cost": None,
                "status": "PENDING",
                "note_id": None,
            })

    # Vendas de tickers fora do top (saída total)
    for ticker in sells:
        if ticker not in top_tickers:
            price = prices.get(ticker, np.nan)
            qty = current.get(ticker, 0)
            if qty > 0 and not pd.isna(price):
                orders.append({
                    "signal_date": signal_date,
                    "exec_date": exec_date,
                    "ticker": ticker,
                    "side": "SELL",
                    "qty": qty,
                    "price": None,
                    "cost": None,
                    "status": "PENDING",
                    "note_id": None,
                })

    return orders, signals_list
