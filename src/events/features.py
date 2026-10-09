"""Transforma eventos confirmados em features estritamente point-in-time."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable

import pandas as pd


EVENT_FEATURE_NAMES = [
    "evt_corporate_5d",
    "evt_ibrx_composition_5d",
    "evt_b3_regulatory_10d",
    "regime_high_volatility",
    "regime_risk_off",
]

_POINT_WINDOWS = {
    "CORPORATE_ACTION": ("evt_corporate_5d", 5),
    "IBRX_COMPOSITION": ("evt_ibrx_composition_5d", 5),
    "B3_REGULATORY": ("evt_b3_regulatory_10d", 10),
}
_REGIME_FEATURES = {
    "HIGH_VOLATILITY_REGIME": "regime_high_volatility",
    "RISK_OFF_REGIME": "regime_risk_off",
}


def _event_date(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    return timestamp.normalize()


def _event_applies_to_ticker(event_ticker: object, ticker: str) -> bool:
    """Eventos sem ticker são de mercado; os demais são específicos do ativo."""
    if event_ticker is None or pd.isna(event_ticker):
        return True
    value = str(event_ticker).strip().upper()
    return value in {"", "ALL", "MARKET", ticker.upper()}


def build_market_event_features(
    index: pd.Index,
    tickers: Iterable[str],
    events: pd.DataFrame | None,
) -> dict[str, pd.DataFrame]:
    """Retorna flags de eventos disponíveis em cada data de sinal.

    Somente eventos ``CONFIRMED`` cujo ``published_at`` já ocorreu são usados.
    Logo, uma revisão posterior, uma data efetiva futura ou a confirmação após
    o fato jamais retroalimenta features de datas passadas.
    """
    dates = pd.DatetimeIndex(pd.to_datetime(index)).normalize()
    ticker_list = list(tickers)
    result = {
        name: pd.DataFrame(0.0, index=dates, columns=ticker_list)
        for name in EVENT_FEATURE_NAMES
    }
    if events is None or events.empty:
        return result

    required = {"event_type", "published_at", "status"}
    if not required.issubset(events.columns):
        raise ValueError(
            "Eventos exigem as colunas event_type, published_at e status"
        )

    for _, event in events.iterrows():
        if str(event.get("status", "")).upper() != "CONFIRMED":
            continue
        # A base de produção possui a dupla confirmação status + booleano.
        # Manter a compatibilidade com DataFrames históricos sem esta coluna
        # permite testar candidatos, sem relaxar a regra quando ela existe.
        if "confirmed" in events.columns:
            confirmed = event.get("confirmed")
            if pd.isna(confirmed) or not bool(confirmed):
                continue
        published_at = _event_date(event.get("published_at"))
        if published_at is None:
            continue
        event_type = str(event.get("event_type", "")).upper()
        event_class = str(event.get("event_class", "POINT")).upper()
        # Nas tabelas atuais, ``available_from`` é obrigatório para eventos
        # promovidos: é a data causal, e não uma suposição a partir do alerta.
        if "available_from" in events.columns:
            available_from = _event_date(event.get("available_from"))
            if available_from is None:
                continue
        else:  # Compatibilidade apenas com fixtures/legado sem a coluna.
            available_from = published_at
        feature_from = _event_date(event.get("feature_from"))
        if feature_from is None:
            feature_from = available_from
        # Disponibilidade informacional nunca pode anteceder a divulgação.
        active_from = max(published_at, available_from, feature_from)
        feature_to = _event_date(event.get("feature_to"))
        valid_to = _event_date(event.get("valid_to"))

        if event_class == "REGIME" and event_type in _REGIME_FEATURES:
            feature_name = _REGIME_FEATURES[event_type]
            if "feature_to" in events.columns and feature_to is None:
                # Regime sem término causal não é promovível; evita duração
                # infinita escondida em uma célula vazia.
                continue
            active_to = feature_to if feature_to is not None else (valid_to if valid_to is not None else dates.max())
        elif event_type in _POINT_WINDOWS:
            feature_name, window_days = _POINT_WINDOWS[event_type]
            active_to = active_from + timedelta(days=window_days)
            if feature_to is not None:
                active_to = min(active_to, feature_to)
            elif valid_to is not None:
                active_to = min(active_to, valid_to)
        else:
            continue

        mask = (dates >= active_from) & (dates <= active_to)
        if not mask.any():
            continue
        for ticker in ticker_list:
            if _event_applies_to_ticker(event.get("ticker"), ticker):
                result[feature_name].loc[mask, ticker] = 1.0

    return result
