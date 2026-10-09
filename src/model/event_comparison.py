"""Comparação temporal entre o modelo-base e o modelo com IBRX Model Watch.

O módulo não modifica parâmetros de carteira, custos, stop/take ou execução.
Ele apenas troca o conjunto de features e usa o mesmo walk-forward e o mesmo
motor de backtest para tornar a comparação auditável.
"""

from __future__ import annotations

from typing import Callable, Dict

import pandas as pd

from quantb3_model import run_backtest
from src.model.train_predict import QuantB3Model


BacktestRunner = Callable[..., dict]


def _metrics(label: str, result: dict) -> dict:
    """Seleciona métricas comparáveis do resultado do motor existente."""
    return {
        "modelo": label,
        "retorno_total": result.get("total_return"),
        "cagr": result.get("cagr"),
        "sharpe": result.get("sharpe"),
        "max_drawdown": result.get("max_dd"),
        "equity_final": result.get("final_equity"),
        "n_trades": result.get("n_trades"),
    }


def compare_base_vs_events_oos(
    *,
    prices: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    volumes: pd.DataFrame,
    benchmark: pd.Series,
    market_events: pd.DataFrame,
    oos_start: pd.Timestamp,
    seed: int = 42,
    backtest_runner: BacktestRunner = run_backtest,
) -> tuple[pd.DataFrame, Dict[str, dict]]:
    """Compara base e enriquecido em período temporal estritamente OOS.

    Cada modelo continua sendo treinado em walk-forward: para cada sinal, só
    observa linhas anteriores à data do sinal. ``oos_start`` apenas determina
    qual trecho da curva e das métricas será avaliado. Os eventos só entram no
    modelo enriquecido; o modelo-base preserva as 18 features oficiais.
    """
    oos_start = pd.Timestamp(oos_start).normalize()
    if oos_start not in prices.index:
        raise ValueError("oos_start deve ser uma data presente na série de preços")
    if market_events is None or market_events.empty:
        raise ValueError("A comparação enriquecida exige eventos históricos confirmados")
    confirmed = market_events["status"].astype(str).str.upper().eq("CONFIRMED") if "status" in market_events else pd.Series(False, index=market_events.index)
    if "confirmed" in market_events:
        confirmed &= market_events["confirmed"].fillna(False).astype(bool)
    if not confirmed.any():
        raise ValueError("A comparação enriquecida exige ao menos um evento confirmado")

    base = QuantB3Model(prices, volumes, benchmark, use_market_events=False)
    enriched = QuantB3Model(
        prices,
        volumes,
        benchmark,
        market_events=market_events,
        use_market_events=True,
    )
    base_rankings = base.generate_rankings()
    enriched_rankings = enriched.generate_rankings()

    base_result = backtest_runner(
        base_rankings, prices, highs, lows, seed=seed, start_eval=oos_start
    )
    enriched_result = backtest_runner(
        enriched_rankings, prices, highs, lows, seed=seed, start_eval=oos_start
    )
    if not base_result or not enriched_result:
        raise ValueError("Período OOS insuficiente para o motor de backtest")

    report = pd.DataFrame([
        _metrics("base_18_features", base_result),
        _metrics("enriquecido_eventos", enriched_result),
    ])
    return report, {"base": base_result, "enriquecido": enriched_result}
