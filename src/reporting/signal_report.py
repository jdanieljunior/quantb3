"""
QuantB3 — Gerador de Relatório Semanal de Sinais (Segunda-feira)
Formato conforme Memorial Descritivo v2.1
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from config.settings import (
    CAPITAL,
    N_POSITIONS,
    SIMULATION_LABEL,
    STOP_PCT,
    TAKE_RR,
)


def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generate_signal_report(
    signal_date: date,
    top_tickers: List[str],
    scores: pd.Series,
    signals: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    current_positions: List[Dict[str, Any]],
    equity: float,
    cash: float,
    pos_value: float,
    perf_full: Optional[Dict] = None,
    perf_year: Optional[Dict] = None,
) -> str:
    """
    Gera o relatório semanal de sinais no formato oficial.

    Args:
        signal_date: Data do sinal (segunda-feira)
        top_tickers: Lista de tickers selecionados (Top 8)
        scores: Series com scores LGBM por ticker
        signals: Lista de sinais com ação, preço, stop, take
        orders: Lista de ordens geradas (BUY/SELL/HOLD)
        current_positions: Posições atuais antes do rebalanceamento
        equity: Valor total da carteira
        cash: Caixa disponível
        pos_value: Valor em posições
        perf_full: Métricas do período completo (opcional)
        perf_year: Métricas do último ano (opcional)

    Returns:
        Relatório formatado como string
    """
    exec_date = _next_weekday(signal_date, 1)  # terça-feira
    lines = []

    # Cabeçalho
    lines += [
        "=" * 60,
        "QUANTB3 | RELATÓRIO SEMANAL DE SINAIS",
        f"⚠️  {SIMULATION_LABEL}",
        f"Data de Geração: {signal_date.strftime('%d/%m/%Y')} (após o pregão de segunda)",
        f"Execução prevista: {exec_date.strftime('%d/%m/%Y')} (terça-feira)",
        f"Capital Total: {format_currency(equity)}",
        f"  Posições: {format_currency(pos_value)} | Caixa: {format_currency(cash)}",
        f"Estratégia: LightGBM_Fwd10_Sticky_LiqP10_Realistic (v2.1)",
        "=" * 60,
        "",
    ]

    # 1. Performance do modelo
    lines += ["1. PERFORMANCE DO MODELO (referência backtest)"]
    lines += ["-" * 40]

    if perf_full:
        lines += [
            "  Período completo (2022-01 → hoje):",
            f"    CAGR:        {perf_full.get('cagr', 0)*100:.1f}%",
            f"    Sharpe:      {perf_full.get('sharpe', 0):.2f}",
            f"    Max DD:      {perf_full.get('max_dd', 0)*100:.1f}%",
            f"    Ret. Total:  {perf_full.get('total_return', 0)*100:.1f}%",
        ]
    else:
        lines += ["  (métricas de backtest não disponíveis nesta execução)"]

    if perf_year:
        lines += [
            "",
            "  Último ano:",
            f"    Retorno:     {perf_year.get('total_return', 0)*100:.1f}%",
            f"    Sharpe:      {perf_year.get('sharpe', 0):.2f}",
            f"    Max DD:      {perf_year.get('max_dd', 0)*100:.1f}%",
        ]

    lines += [""]

    # 2. Carteira-alvo da semana
    lines += ["2. CARTEIRA-ALVO DA SEMANA (Top 8 pelo score LGBM)"]
    lines += ["-" * 40]

    target_value = equity / N_POSITIONS
    header = f"  {'Ticker':<12} {'Score':>8} {'Rank':>5} {'Preço Ref':>10} {'Qtd':>6} {'% Capital':>10}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    sig_map = {s["ticker"]: s for s in signals}

    for rank, ticker in enumerate(top_tickers, 1):
        sig = sig_map.get(ticker, {})
        score = scores.get(ticker, 0)
        ref_price = sig.get("ref_price", 0)
        target_qty = sig.get("target_qty", 0)
        pct_capital = (target_qty * ref_price / equity * 100) if equity > 0 else 0

        lines.append(
            f"  {ticker:<12} {score:>8.4f} {rank:>5} "
            f"R${ref_price:>8.2f} {target_qty:>6} {pct_capital:>9.1f}%"
        )

    lines += [""]

    # 3. Ordens recomendadas
    lines += ["3. ORDENS RECOMENDADAS PARA TERÇA-FEIRA"]
    lines += ["-" * 40]

    buys = [o for o in orders if o["side"] == "BUY"]
    sells = [o for o in orders if o["side"] == "SELL"]
    holds = [s for s in signals if s["action"] == "HOLD"]

    if buys:
        lines += ["  COMPRAR:"]
        for o in buys:
            sig = sig_map.get(o["ticker"], {})
            ref = sig.get("ref_price", 0)
            lines.append(
                f"    ▶ {o['ticker']:<10} {o['qty']:>5} ações "
                f"(ref: R${ref:.2f}, aprox. {format_currency(o['qty'] * ref)})"
            )

    if sells:
        lines += ["", "  VENDER:"]
        for o in sells:
            sig = sig_map.get(o["ticker"], {})
            ref = sig.get("ref_price", 0)
            lines.append(
                f"    ◀ {o['ticker']:<10} {o['qty']:>5} ações "
                f"(ref: R${ref:.2f})"
            )

    if holds:
        lines += ["", "  MANTER:"]
        for s in holds:
            lines.append(f"    ■ {s['ticker']:<10} {s.get('target_qty', 0):>5} ações")

    lines += [""]

    # 4. Gestão de risco por posição
    lines += ["4. GESTÃO DE RISCO POR POSIÇÃO"]
    lines += ["-" * 40]
    lines.append(
        f"  {'Ticker':<12} {'Ref':>10} {'Stop (-5%)':>12} {'Take (1:2.5)':>13} {'Risco R$':>10}"
    )
    lines.append("  " + "-" * 60)

    for ticker in top_tickers:
        sig = sig_map.get(ticker, {})
        ref = sig.get("ref_price", 0)
        stop = sig.get("stop_price", 0)
        take = sig.get("take_price", 0)
        qty = sig.get("target_qty", 0)
        risk_rs = qty * (ref - stop) if ref > 0 else 0

        lines.append(
            f"  {ticker:<12} R${ref:>8.2f} R${stop:>10.2f} R${take:>11.2f} R${risk_rs:>8.2f}"
        )

    lines += [""]

    # 5. Ações com sinal negativo
    lines += ["5. AÇÕES COM SINAL NEGATIVO / EVITAR"]
    lines += ["-" * 40]

    negative = [
        s for s in signals
        if s["action"] == "OUT" and scores.get(s["ticker"], 0) < 0
    ]

    if negative:
        neg_sorted = sorted(negative, key=lambda x: scores.get(x["ticker"], 0))
        for s in neg_sorted[:10]:
            score = scores.get(s["ticker"], 0)
            lines.append(f"  ✗ {s['ticker']:<10} score: {score:.4f}")
    else:
        lines.append("  (nenhuma ação com score negativo relevante)")

    lines += [""]

    # 6. Observações
    lines += ["6. OBSERVAÇÕES"]
    lines += ["-" * 40]
    lines += [
        f"  • Stop Loss: {abs(STOP_PCT)*100:.0f}% abaixo do preço de entrada",
        f"  • Take Profit: relação risco/retorno 1:{TAKE_RR}",
        "  • Executar as ordens na TERÇA-FEIRA via homebroker",
        "  • Preço de referência = fechamento desta segunda-feira",
        "  • Usar mercado fracionário (Clear ou Nubank)",
        f"  • {SIMULATION_LABEL}",
    ]

    lines += ["", "=" * 60]

    return "\n".join(lines)


def generate_trade_notes(
    exec_date: date,
    executed_orders: List[Dict[str, Any]],
    cash_after: float,
    pos_value_after: float,
) -> str:
    """
    Gera as notas de negociação após execução simulada (terça-feira).
    """
    lines = [
        "=" * 60,
        "QUANTB3 | NOTAS DE NEGOCIAÇÃO SIMULADAS",
        f"⚠️  {SIMULATION_LABEL}",
        f"Data de Execução: {exec_date.strftime('%d/%m/%Y')} (terça-feira)",
        "=" * 60,
        "",
    ]

    total_compras = 0.0
    total_vendas = 0.0

    lines.append(f"  {'Ticker':<12} {'Lado':>6} {'Qtd':>6} {'Preço':>10} {'Volume':>12} {'Custo':>8}")
    lines.append("  " + "-" * 60)

    for o in executed_orders:
        side = o.get("side", "?")
        ticker = o.get("ticker", "?")
        qty = o.get("qty", 0)
        price = o.get("price", 0) or 0
        cost = o.get("cost", 0) or 0
        volume = qty * price

        if side == "BUY":
            total_compras += volume
        elif side in ("SELL", "STOP", "TAKE"):
            total_vendas += volume

        lines.append(
            f"  {ticker:<12} {side:>6} {qty:>6} "
            f"R${price:>8.2f} R${volume:>10.2f} R${cost:>6.2f}"
        )

    lines += [
        "",
        f"  Total compras:  {format_currency(total_compras)}",
        f"  Total vendas:   {format_currency(total_vendas)}",
        f"  Caixa após:     {format_currency(cash_after)}",
        f"  Posições após:  {format_currency(pos_value_after)}",
        f"  Patrimônio:     {format_currency(cash_after + pos_value_after)}",
        "",
        "=" * 60,
    ]

    return "\n".join(lines)


def _next_weekday(d: date, weekday: int) -> date:
    """Retorna a próxima data com o dia da semana especificado (0=seg, 1=ter...)."""
    days_ahead = weekday - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    from datetime import timedelta
    return d + timedelta(days=days_ahead)
