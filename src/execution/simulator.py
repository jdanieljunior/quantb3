"""
QuantB3 — Simulador de Execução
Executa ordens com preço probabilístico triangular (Low, Close, High)
+ slippage + custos B3
"""

from __future__ import annotations

import logging
import random
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import (
    COST_PCT,
    SLIPPAGE_ENTRY,
    SLIPPAGE_STOP,
    SLIPPAGE_TAKE,
    STOP_PCT,
    TAKE_RR,
)

logger = logging.getLogger(__name__)


def triangular_price(
    low: float,
    high: float,
    close: float,
    seed: Optional[int] = None,
) -> float:
    """
    Gera preço probabilístico com distribuição triangular.
    Moda centrada no Close, limitado ao range [Low, High].

    Args:
        low: Mínima do dia
        high: Máxima do dia
        close: Fechamento do dia (moda da distribuição)
        seed: Semente aleatória (opcional)

    Returns:
        Preço simulado
    """
    if any(pd.isna(v) for v in [low, high, close]):
        return close if not pd.isna(close) else np.nan

    if high <= low:
        return float(close)

    close = float(np.clip(close, low, high))

    if seed is not None:
        np.random.seed(seed)

    return float(np.random.triangular(low, close, high))


def simulate_execution(
    order: Dict,
    ohlc_day: Dict,
    seed: Optional[int] = None,
) -> Tuple[float, float, str]:
    """
    Simula a execução de uma ordem com preço triangular + slippage + custo.

    Args:
        order: Dict com side (BUY/SELL), qty, ticker
        ohlc_day: Dict com o, h, l, c do dia de execução
        seed: Semente aleatória

    Returns:
        (exec_price, cost_value, note)
    """
    low = ohlc_day.get("l", np.nan)
    high = ohlc_day.get("h", np.nan)
    close = ohlc_day.get("c", np.nan)

    raw_price = triangular_price(low, high, close, seed)

    if pd.isna(raw_price) or raw_price <= 0:
        raw_price = close if not pd.isna(close) else 0.0

    side = order.get("side", "BUY")
    qty = order.get("qty", 0)

    # Aplica slippage (desfavorável)
    if side == "BUY":
        exec_price = raw_price * (1 + SLIPPAGE_ENTRY)
    elif side == "SELL":
        exec_price = raw_price * (1 - SLIPPAGE_ENTRY)
    elif side == "STOP":
        exec_price = raw_price * (1 - SLIPPAGE_STOP)
    elif side == "TAKE":
        exec_price = raw_price * (1 - SLIPPAGE_TAKE)
    else:
        exec_price = raw_price

    # Custo B3 (emolumentos)
    cost_value = abs(qty) * exec_price * COST_PCT

    note = (
        f"{side} {qty}x {order.get('ticker', '?')} "
        f"@ R${exec_price:.2f} (raw={raw_price:.2f}, custo=R${cost_value:.2f})"
    )

    return exec_price, cost_value, note


def execute_pending_orders(
    pending_orders: List[Dict],
    prices_day: pd.DataFrame,
    exec_date: date,
    cash: float,
    positions: Dict[str, Dict],
    seed: Optional[int] = None,
) -> Tuple[float, Dict[str, Dict], List[Dict], List[str]]:
    """
    Executa todas as ordens pendentes para um dia.

    Args:
        pending_orders: Lista de ordens PENDING
        prices_day: DataFrame com OHLCV do dia (index=ticker)
        exec_date: Data de execução
        cash: Caixa disponível
        positions: Dict ticker -> {qty, avg_price, stop, take}
        seed: Semente aleatória

    Returns:
        (novo_cash, novas_posicoes, ordens_executadas, notas_negociacao)
    """
    executed = []
    notes = []
    rng = np.random.default_rng(seed)

    # Primeiro processa vendas (libera caixa)
    sells = [o for o in pending_orders if o["side"] == "SELL"]
    buys = [o for o in pending_orders if o["side"] == "BUY"]

    for order in sells:
        ticker = order["ticker"]
        qty = order["qty"]

        if ticker not in positions:
            logger.warning(f"Tentativa de vender {ticker} sem posição")
            continue

        row = prices_day[prices_day["ticker"] == ticker]
        if row.empty:
            logger.warning(f"Sem dados OHLCV para {ticker} em {exec_date}")
            continue

        ohlc = row.iloc[0].to_dict()
        local_seed = int(rng.integers(0, 999999))
        exec_price, cost_val, note = simulate_execution(order, ohlc, local_seed)

        proceeds = qty * exec_price - cost_val
        cash += proceeds

        order_filled = {**order, "price": exec_price, "cost": cost_val,
                        "status": "FILLED", "exec_date": exec_date}
        executed.append(order_filled)
        notes.append(note)

        # Remove posição
        if positions[ticker]["qty"] <= qty:
            del positions[ticker]
        else:
            positions[ticker]["qty"] -= qty

        logger.info(f"VENDA: {note}")

    # Depois processa compras
    for order in buys:
        ticker = order["ticker"]
        qty = order["qty"]

        row = prices_day[prices_day["ticker"] == ticker]
        if row.empty:
            logger.warning(f"Sem dados OHLCV para {ticker} em {exec_date}")
            continue

        ohlc = row.iloc[0].to_dict()
        local_seed = int(rng.integers(0, 999999))
        exec_price, cost_val, note = simulate_execution(order, ohlc, local_seed)

        total_cost = qty * exec_price + cost_val
        if total_cost > cash:
            # Ajusta quantidade para o caixa disponível
            qty = int((cash * 0.99) / (exec_price * (1 + COST_PCT)))
            if qty <= 0:
                logger.warning(f"Caixa insuficiente para {ticker}")
                continue
            total_cost = qty * exec_price + cost_val
            order = {**order, "qty": qty}
            exec_price, cost_val, note = simulate_execution(order, ohlc, local_seed)
            total_cost = qty * exec_price + cost_val

        cash -= total_cost

        # Calcula stop e take
        stop_p = exec_price * (1 + STOP_PCT) * (1 - SLIPPAGE_STOP)
        risk = exec_price - stop_p
        take_p = (exec_price + risk * TAKE_RR) * (1 - SLIPPAGE_TAKE)

        # Atualiza posição (preço médio ponderado)
        if ticker in positions:
            old = positions[ticker]
            total_qty = old["qty"] + qty
            avg_price = (old["qty"] * old["avg_price"] + qty * exec_price) / total_qty
            positions[ticker] = {
                "qty": total_qty,
                "avg_price": avg_price,
                "stop": stop_p,
                "take": take_p,
            }
        else:
            positions[ticker] = {
                "qty": qty,
                "avg_price": exec_price,
                "stop": stop_p,
                "take": take_p,
            }

        order_filled = {**order, "price": exec_price, "cost": cost_val,
                        "status": "FILLED", "exec_date": exec_date}
        executed.append(order_filled)
        notes.append(note)

        logger.info(f"COMPRA: {note}")

    return cash, positions, executed, notes


def check_stops_takes(
    positions: Dict[str, Dict],
    prices_day: pd.DataFrame,
    date_val: date,
    cash: float,
) -> Tuple[float, Dict[str, Dict], List[Dict]]:
    """
    Verifica stops e takes no High/Low do dia.

    Args:
        positions: Posições atuais
        prices_day: OHLCV do dia
        date_val: Data de verificação
        cash: Caixa atual

    Returns:
        (novo_cash, posicoes_atualizadas, ordens_stop_take)
    """
    triggered = []
    to_close = []

    for ticker, pos in positions.items():
        row = prices_day[prices_day["ticker"] == ticker]
        if row.empty:
            continue

        day_low = row.iloc[0].get("l", np.nan)
        day_high = row.iloc[0].get("h", np.nan)

        if pd.isna(day_low) or pd.isna(day_high):
            continue

        if pos.get("stop") and day_low <= pos["stop"]:
            # Stop Loss ativado
            proceeds = pos["qty"] * pos["stop"] * (1 - COST_PCT)
            cash += proceeds
            triggered.append({
                "signal_date": None,
                "exec_date": date_val,
                "ticker": ticker,
                "side": "STOP",
                "qty": pos["qty"],
                "price": pos["stop"],
                "cost": pos["qty"] * pos["stop"] * COST_PCT,
                "status": "FILLED",
                "note_id": None,
            })
            to_close.append(ticker)
            logger.info(f"STOP: {ticker} @ R${pos['stop']:.2f}")

        elif pos.get("take") and day_high >= pos["take"]:
            # Take Profit ativado
            proceeds = pos["qty"] * pos["take"] * (1 - COST_PCT)
            cash += proceeds
            triggered.append({
                "signal_date": None,
                "exec_date": date_val,
                "ticker": ticker,
                "side": "TAKE",
                "qty": pos["qty"],
                "price": pos["take"],
                "cost": pos["qty"] * pos["take"] * COST_PCT,
                "status": "FILLED",
                "note_id": None,
            })
            to_close.append(ticker)
            logger.info(f"TAKE: {ticker} @ R${pos['take']:.2f}")

    for ticker in to_close:
        del positions[ticker]

    return cash, positions, triggered
