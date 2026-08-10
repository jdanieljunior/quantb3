"""
QuantB3 — Engenharia de Features
18 features oficiais do modelo LightGBM v2.1
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from config.settings import FEATURE_NAMES


def build_features(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    benchmark: pd.Series,
) -> Dict[str, pd.DataFrame]:
    """
    Constrói as 18 features oficiais do modelo.

    Args:
        prices: DataFrame de fechamentos (index=Data, columns=tickers)
        volumes: DataFrame de volumes (index=Data, columns=tickers)
        benchmark: Series de fechamentos do BOVA11 (index=Data)

    Returns:
        Dict com nome da feature -> DataFrame (mesmo shape que prices)
    """
    rets = prices.pct_change()
    feat: Dict[str, pd.DataFrame] = {}

    # --- Momentum ---
    for w in [5, 10, 21, 42, 63]:
        feat[f"mom_{w}"] = prices.pct_change(w)
    feat["mom_accel"] = feat["mom_10"] - feat["mom_21"]

    # --- Volatilidade ---
    for w in [10, 21]:
        feat[f"vol_{w}"] = rets.rolling(w).std()
    feat["mom_vol_adj"] = feat["mom_10"] / feat["vol_21"].replace(0, np.nan)

    # --- Volume ---
    vol_ma21 = volumes.rolling(21).mean()
    feat["vol_rel"] = volumes / vol_ma21.replace(0, np.nan)
    feat["vol_trend"] = vol_ma21 / volumes.rolling(63).mean().replace(0, np.nan)

    # --- Preço relativo (canal 63d) ---
    roll_max = prices.rolling(63).max()
    roll_min = prices.rolling(63).min()
    feat["dist_high_63"] = prices / roll_max - 1
    feat["dist_low_63"] = prices / roll_min - 1
    feat["price_pos_63"] = (prices - roll_min) / (roll_max - roll_min).replace(0, np.nan)

    # --- Excesso vs mercado ---
    for w in [10, 21]:
        feat[f"excesso_{w}"] = feat[f"mom_{w}"].sub(benchmark.pct_change(w), axis=0)

    # --- Técnicos ---
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    feat["rsi_14"] = 100 - (100 / (1 + rs))
    feat["rev_5"] = -feat["mom_5"]

    return feat


def build_panel(
    features: Dict[str, pd.DataFrame],
    fwd_ret: pd.DataFrame,
    vol_ma21: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Empilha features + target em formato longo (Data, ticker, features..., fwd_10).

    Args:
        features: Dict de features
        fwd_ret: DataFrame de retornos forward
        vol_ma21: Volume médio 21d (para filtro de liquidez)

    Returns:
        DataFrame no formato longo
    """
    panels = []
    for name, df in features.items():
        s = df.stack()
        s.name = name
        panels.append(s)

    panel = pd.concat(panels, axis=1)
    panel["fwd_10"] = fwd_ret.stack()
    if vol_ma21 is not None:
        panel["vol_ma21"] = vol_ma21.stack()

    subset = FEATURE_NAMES + ["fwd_10"]
    panel = panel.dropna(subset=subset, how="any").reset_index()

    cols = ["Data", "ticker"] + FEATURE_NAMES + ["fwd_10"]
    if vol_ma21 is not None:
        cols.append("vol_ma21")

    panel.columns = cols
    return panel.sort_values(["Data", "ticker"]).reset_index(drop=True)


def get_latest_features(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    benchmark: pd.Series,
    signal_date: pd.Timestamp,
    vol_threshold: Optional[float] = None,
) -> pd.DataFrame:
    """
    Calcula as features para uma data específica (uso em produção).

    Args:
        prices: DataFrame de fechamentos
        volumes: DataFrame de volumes
        benchmark: Series BOVA11
        signal_date: Data do sinal
        vol_threshold: Limiar de liquidez (P10 do volume médio 21d).
            Quando ``None``, retorna todos os tickers com features válidas.

    Returns:
        DataFrame com features para o dia, filtrado por liquidez
    """
    features = build_features(prices, volumes, benchmark)
    vol_ma21 = volumes.rolling(21).mean()

    # Pega apenas a data do sinal
    row_data = {}
    for name, df in features.items():
        if signal_date in df.index:
            row_data[name] = df.loc[signal_date]

    if not row_data:
        return pd.DataFrame()

    feat_df = pd.DataFrame(row_data)
    feat_df.index.name = "ticker"
    feat_df = feat_df.reset_index()

    # Adiciona volume médio para filtro de liquidez
    if signal_date in vol_ma21.index:
        vol_series = vol_ma21.loc[signal_date]
        vol_series.name = "vol_ma21"
        feat_df = feat_df.merge(
            vol_series.reset_index().rename(columns={"index": "ticker"}),
            on="ticker",
            how="left"
        )
        # Aplica filtro de liquidez apenas quando solicitado. O fallback sem
        # filtro permite gerar um ranking mesmo em um dia de baixa cobertura.
        if vol_threshold is not None:
            feat_df = feat_df[feat_df["vol_ma21"] >= vol_threshold]

    # Remove linhas com features faltando
    feat_df = feat_df.dropna(subset=FEATURE_NAMES)

    return feat_df
