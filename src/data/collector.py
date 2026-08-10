"""
QuantB3 — Coletor de dados OHLCV via yfinance
Atualiza a tabela prices no Supabase com dados do universo IBRX.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import List, Optional

import pandas as pd
import yfinance as yf

from config.settings import (
    BENCHMARKS,
    BOVA_TICKER,
    MIN_OBS_PCT,
    YFINANCE_RETRY_ATTEMPTS,
    YFINANCE_RETRY_DELAY,
    YFINANCE_TICKER_BLACKLIST,
    YFINANCE_TIMEOUT,
    YFINANCE_INITIAL_TICKERS_PER_RUN,
)
from src.db.repositories import get_latest_price_dates, upsert_prices

logger = logging.getLogger(__name__)

# Universo IBRX (~86 tickers líquidos) + benchmarks
IBRX_TICKERS = [
    "ABEV3.SA", "ALOS3.SA", "ALPA4.SA", "AMER3.SA", "ASAI3.SA",
    "AZUL4.SA", "B3SA3.SA", "BBAS3.SA", "BBDC3.SA", "BBDC4.SA",
    "BBSE3.SA", "BEEF3.SA", "BPAC11.SA", "BRAP4.SA", "BRFS3.SA",
    "BRKM5.SA", "CASH3.SA", "CCRO3.SA", "CIEL3.SA", "CMIG4.SA",
    "COGN3.SA", "CPFE3.SA", "CPLE6.SA", "CRFB3.SA", "CSAN3.SA",
    "CSNA3.SA", "CVCB3.SA", "CYRE3.SA", "DXCO3.SA", "ECOR3.SA",
    "EGIE3.SA", "ELET3.SA", "ELET6.SA", "EMBR3.SA", "ENEV3.SA",
    "ENGI11.SA", "EQTL3.SA", "EZTC3.SA", "FLRY3.SA", "GGBR4.SA",
    "GOAU4.SA", "GOLL4.SA", "HAPV3.SA", "HYPE3.SA", "IGTI11.SA",
    "INTB3.SA", "IRBR3.SA", "ITSA4.SA", "ITUB4.SA", "JBSS3.SA",
    "JHSF3.SA", "KLBN11.SA", "LREN3.SA", "LWSA3.SA", "MGLU3.SA",
    "MRFG3.SA", "MRVE3.SA", "MULT3.SA", "NTCO3.SA", "PCAR3.SA",
    "PETR3.SA", "PETR4.SA", "PETZ3.SA", "PRIO3.SA", "QUAL3.SA",
    "RADL3.SA", "RAIL3.SA", "RAIZ4.SA", "RDOR3.SA", "RENT3.SA",
    "RRRP3.SA", "SANB11.SA", "SBSP3.SA", "SLCE3.SA", "SMTO3.SA",
    "SOMA3.SA", "SUZB3.SA", "TAEE11.SA", "TIMS3.SA", "TOTS3.SA",
    "UGPA3.SA", "USIM5.SA", "VALE3.SA", "VBBR3.SA", "VIVT3.SA",
    "WEGE3.SA", "YDUQ3.SA",
] + BENCHMARKS

# Rebaixa uma janela recente para corrigir eventuais lacunas do Yahoo Finance.
# Ela é maior que a maior janela de feature (63 pregões).
REPAIR_LOOKBACK_DAYS = 100
INITIAL_HISTORY_START = date(2022, 1, 1)


def _download_with_retry(
    ticker: str,
    start: str,
    end: str,
    attempts: int = YFINANCE_RETRY_ATTEMPTS,
    delay: int = YFINANCE_RETRY_DELAY,
) -> Optional[pd.DataFrame]:
    """Baixa um ativo por vez com timeout e retry automático."""
    for attempt in range(attempts):
        try:
            logger.info(
                "yfinance: %s, tentativa %s/%s (timeout=%ss)",
                ticker,
                attempt + 1,
                attempts,
                YFINANCE_TIMEOUT,
            )
            data = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=YFINANCE_TIMEOUT,
            )
            if data is not None and not data.empty:
                return data
            logger.warning("%s: yfinance retornou vazio", ticker)
        except Exception as e:
            logger.warning("%s: erro yfinance: %s", ticker, e)
        if attempt < attempts - 1:
            time.sleep(delay)

    return None


def _parse_yfinance_data(raw: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
    """
    Converte o DataFrame multi-level do yfinance para formato longo:
    date, ticker, o, h, l, c, v
    """
    records = []

    if isinstance(raw.columns, pd.MultiIndex):
        # Múltiplos tickers: MultiIndex (field, ticker)
        for ticker in tickers:
            try:
                sub = raw.xs(ticker, axis=1, level=1)
                sub = sub.rename(columns={
                    "Open": "o", "High": "h", "Low": "l",
                    "Close": "c", "Volume": "v"
                })
                sub = sub[["o", "h", "l", "c", "v"]].dropna(how="all")
                sub["ticker"] = ticker
                sub.index.name = "date"
                sub = sub.reset_index()
                records.append(sub)
            except KeyError:
                logger.debug(f"Ticker {ticker} não encontrado nos dados")
    else:
        # Ticker único
        ticker = tickers[0] if tickers else "UNKNOWN"
        sub = raw.rename(columns={
            "Open": "o", "High": "h", "Low": "l",
            "Close": "c", "Volume": "v"
        })
        sub = sub[["o", "h", "l", "c", "v"]].dropna(how="all")
        sub["ticker"] = ticker
        sub.index.name = "date"
        sub = sub.reset_index()
        records.append(sub)

    if not records:
        return pd.DataFrame()

    df = pd.concat(records, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def update_prices(
    tickers: Optional[List[str]] = None,
    start_date: Optional[date] = None,
    force_full: bool = False,
    max_new_tickers: Optional[int] = None,
) -> int:
    """
    Atualiza preços no banco de dados.

    Args:
        tickers: Lista de tickers (default: IBRX_TICKERS completo)
        start_date: Data inicial para todos os tickers (opcional)
        force_full: Se True, baixa desde 2022-01-01 independente do banco
        max_new_tickers: Limite de tickers sem histórico para esta execução

    Returns:
        Número de registros inseridos/atualizados
    """
    if tickers is None:
        tickers = IBRX_TICKERS

    ignored_tickers = sorted(set(tickers) & YFINANCE_TICKER_BLACKLIST)
    if ignored_tickers:
        logger.warning(
            "Ignorando %s ticker(s) na blacklist do Yahoo Finance: %s",
            len(ignored_tickers),
            ", ".join(ignored_tickers),
        )
        tickers = [ticker for ticker in tickers if ticker not in YFINANCE_TICKER_BLACKLIST]

    if not tickers:
        logger.warning("Nenhum ticker disponível para atualização após aplicar a blacklist")
        return 0

    end = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    latest_by_ticker = get_latest_price_dates(tickers)
    missing_tickers = [ticker for ticker in tickers if ticker not in latest_by_ticker]
    if max_new_tickers is None:
        max_new_tickers = YFINANCE_INITIAL_TICKERS_PER_RUN

    if force_full or start_date:
        selected_tickers = tickers
    else:
        selected_missing = set(missing_tickers[:max_new_tickers])
        selected_tickers = [
            ticker for ticker in tickers
            if ticker in latest_by_ticker or ticker in selected_missing
        ]

    logger.info(
        "Cobertura: %s ticker(s) com histórico, %s sem histórico; %s selecionados nesta execução",
        len(latest_by_ticker),
        len(missing_tickers),
        len(selected_tickers),
    )
    if len(missing_tickers) > max_new_tickers and not (force_full or start_date):
        logger.info(
            "Carga inicial progressiva: %s ticker(s) pendentes para as próximas execuções",
            len(missing_tickers) - max_new_tickers,
        )
    total_rows = 0

    for index, ticker in enumerate(selected_tickers, start=1):
        logger.info("  Ativo %s/%s: %s", index, len(selected_tickers), ticker)

        if force_full:
            ticker_start = INITIAL_HISTORY_START
        elif start_date:
            ticker_start = start_date
        else:
            last_date = latest_by_ticker.get(ticker)
            # Ticker novo: carga inicial completa. Ticker existente: rebaixa
            # os últimos 100 dias para reparar lacunas como a de 31/07/2026.
            ticker_start = (
                INITIAL_HISTORY_START
                if last_date is None
                else max(INITIAL_HISTORY_START, last_date - timedelta(days=REPAIR_LOOKBACK_DAYS))
            )

        start = ticker_start.strftime("%Y-%m-%d")

        raw = _download_with_retry(ticker, start, end)
        if raw is None or raw.empty:
            logger.warning("  %s: sem dados", ticker)
            continue

        df = _parse_yfinance_data(raw, [ticker])
        if df.empty:
            continue

        # Remove linhas com Close nulo
        df = df.dropna(subset=["c"])

        rows = upsert_prices(df)
        total_rows += rows
        logger.info("  %s: %s registros inseridos", ticker, rows)

        time.sleep(0.25)  # Rate limiting

    logger.info(f"Total: {total_rows} registros atualizados")
    return total_rows


def load_prices_from_csv(csv_path: str) -> pd.DataFrame:
    """
    Carrega preços do CSV histórico e faz upsert no banco.
    Útil para carga inicial.

    Formato CSV: Data, ticker, O, H, L, C, V
    """
    logger.info(f"Carregando CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    # Normaliza nomes de colunas
    col_map = {
        "Data": "date", "data": "date",
        "O": "o", "H": "h", "L": "l", "C": "c", "V": "v",
        "open": "o", "high": "h", "low": "l", "close": "c", "volume": "v",
    }
    df = df.rename(columns=col_map)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    required = ["date", "ticker", "o", "h", "l", "c", "v"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas faltando no CSV: {missing}")

    df = df[required].dropna(subset=["c"])

    logger.info(f"  {len(df)} registros carregados do CSV")
    rows = upsert_prices(df)
    logger.info(f"  {rows} registros inseridos no banco")
    return df
