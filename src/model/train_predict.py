"""
QuantB3 — Treinamento e Predição do Modelo LightGBM
Walk-forward: treina com dados anteriores à data do sinal.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError as e:
    raise ImportError("Instale lightgbm: pip install lightgbm") from e

from config.settings import (
    FEATURE_NAMES,
    FORWARD_DAYS,
    LGBM_PARAMS,
    LIQ_PERCENTILE,
    STICKY_BUFFER,
    TRAIN_MIN_DAYS,
    N_POSITIONS,
)
from src.features.engineering import build_features, build_panel

logger = logging.getLogger(__name__)


class QuantB3Model:
    """
    Modelo oficial QuantB3 v2.1:
    - LightGBM regressor (target = retorno forward 10d)
    - Filtro de liquidez (volume médio 21d >= P10)
    - Sticky turnover (mantém nomes no top N+4)
    """

    def __init__(
        self,
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
        benchmark: pd.Series,
        n_positions: int = N_POSITIONS,
        liq_percentile: float = LIQ_PERCENTILE,
        sticky_buffer: int = STICKY_BUFFER,
        train_min_days: int = TRAIN_MIN_DAYS,
        lgbm_params: Optional[dict] = None,
    ):
        self.prices = prices
        self.volumes = volumes
        self.benchmark = benchmark.reindex(prices.index).ffill()
        self.n_positions = n_positions
        self.liq_percentile = liq_percentile
        self.sticky_buffer = sticky_buffer
        self.train_min_days = train_min_days
        self.lgbm_params = lgbm_params or LGBM_PARAMS.copy()

        self.features = build_features(prices, volumes, self.benchmark)
        self.vol_ma21 = volumes.rolling(21).mean()
        self.fwd_10 = prices.pct_change(FORWARD_DAYS).shift(-FORWARD_DAYS)
        self.panel = build_panel(self.features, self.fwd_10, self.vol_ma21)
        self.vol_threshold = float(
            self.panel["vol_ma21"].quantile(self.liq_percentile)
        )

    def _train_lgbm(self, X: np.ndarray, y: np.ndarray) -> lgb.LGBMRegressor:
        """Treina o modelo LightGBM."""
        model = lgb.LGBMRegressor(**self.lgbm_params)
        model.fit(X, y)
        return model

    def generate_rankings(
        self,
        only_mondays: bool = True,
    ) -> Dict[pd.Timestamp, List[str]]:
        """
        Walk-forward: a cada segunda (ou cada data), treina com dados anteriores,
        aplica filtro de liquidez e sticky turnover.

        Returns:
            Dict data -> lista de tickers (top N)
        """
        all_dates = sorted(self.panel["Data"].unique())
        if only_mondays:
            signal_dates = [
                d for d in all_dates
                if pd.Timestamp(d).weekday() == 0
                and (d - all_dates[0]).days >= self.train_min_days
            ]
        else:
            signal_dates = [
                d for d in all_dates
                if (d - all_dates[0]).days >= self.train_min_days
            ]

        score_history: Dict[pd.Timestamp, pd.Series] = {}

        for i, mon in enumerate(signal_dates):
            train = self.panel[self.panel["Data"] < mon]
            test = self.panel[self.panel["Data"] == mon]

            if len(train) < 1000 or len(test) < self.n_positions:
                continue

            # Filtro de liquidez
            test_liq = test[test["vol_ma21"] >= self.vol_threshold]
            if len(test_liq) < self.n_positions:
                test_liq = test

            try:
                model = self._train_lgbm(
                    train[FEATURE_NAMES].values,
                    train["fwd_10"].values,
                )
                scores = model.predict(test_liq[FEATURE_NAMES].values)
                score_history[mon] = pd.Series(
                    scores, index=test_liq["ticker"].values
                )
                if (i + 1) % 10 == 0:
                    logger.info(f"  Ranking {i + 1}/{len(signal_dates)}: {pd.Timestamp(mon).date()}")
            except Exception as e:
                logger.warning(f"Erro no ranking {mon}: {e}")
                continue

        return self._apply_sticky(score_history)

    def _apply_sticky(
        self,
        score_history: Dict[pd.Timestamp, pd.Series],
    ) -> Dict[pd.Timestamp, List[str]]:
        """Sticky turnover: mantém tickers que ainda estão no top (N + buffer)."""
        rankings: Dict[pd.Timestamp, List[str]] = {}
        prev: List[str] = []

        for mon in sorted(score_history.keys()):
            scores = score_history[mon].sort_values(ascending=False)
            top_raw = list(scores.head(self.n_positions).index)

            if not prev:
                rankings[mon] = top_raw
                prev = top_raw
                continue

            buffer = list(scores.head(self.n_positions + self.sticky_buffer).index)
            new_port = [t for t in prev if t in buffer]
            for t in top_raw:
                if t not in new_port and len(new_port) < self.n_positions:
                    new_port.append(t)
            # Completa se ainda faltar
            for t in top_raw:
                if len(new_port) >= self.n_positions:
                    break
                if t not in new_port:
                    new_port.append(t)

            rankings[mon] = new_port[: self.n_positions]
            prev = rankings[mon]

        return rankings

    def score_on_date(
        self,
        date: pd.Timestamp,
        prev_portfolio: Optional[List[str]] = None,
    ) -> Tuple[pd.Series, List[str]]:
        """
        Score LGBM para uma data específica + sticky aplicado.

        Args:
            date: Data do sinal (segunda-feira)
            prev_portfolio: Carteira anterior (para sticky)

        Returns:
            (scores_series, top_tickers_com_sticky)
        """
        train = self.panel[self.panel["Data"] < date]
        test = self.panel[self.panel["Data"] == date]

        if len(train) < 1000 or len(test) == 0:
            return pd.Series(dtype=float), []

        test_liq = test[test["vol_ma21"] >= self.vol_threshold]
        if len(test_liq) < self.n_positions:
            test_liq = test

        model = self._train_lgbm(
            train[FEATURE_NAMES].values,
            train["fwd_10"].values,
        )
        scores = model.predict(test_liq[FEATURE_NAMES].values)
        score_series = pd.Series(
            scores, index=test_liq["ticker"].values
        ).sort_values(ascending=False)

        # Aplica sticky
        if prev_portfolio:
            buffer = list(score_series.head(self.n_positions + self.sticky_buffer).index)
            new_port = [t for t in prev_portfolio if t in buffer]
            top_raw = list(score_series.head(self.n_positions).index)
            for t in top_raw:
                if t not in new_port and len(new_port) < self.n_positions:
                    new_port.append(t)
            for t in top_raw:
                if len(new_port) >= self.n_positions:
                    break
                if t not in new_port:
                    new_port.append(t)
            top_tickers = new_port[: self.n_positions]
        else:
            top_tickers = list(score_series.head(self.n_positions).index)

        return score_series, top_tickers
