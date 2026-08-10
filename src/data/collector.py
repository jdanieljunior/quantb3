"""
QuantB3 — Coletor de dados OHLCV via yfinance
Atualiza a tabela prices no Supabase com dados do universo IBRX.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

import pandas as pd
import yfinance as yf

from config.settings import (
    BENCHMARKS,
    BOVA_TICKER,
    MIN_OBS_PCT,
    YFINANCE_BATCH_SIZE,
    YFINANCE_RETRY_ATTEMPTS,
    YFINANCE_RETRY_DELAY,
    YFINANCE_TIMEOUT,
)
from src.db.repositories import get_latest_price_date, upsert_prices

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


def _download_with_retry(
    tickers: List[str],
    start: str,
    end: str,
    attempts: int = YFINANCE_RETRY_ATTEMPTS,
    delay: int = YFINANCE_RETRY_DELAY,
) -> Optional[pd.DataFrame]:
    """Baixa dados do yfinance com timeout e retry automático."""
    for attempt in range(attempts):
        try:
            logger.info(
                "yfinance: tentativa %s/%s para %s ativos (timeout=%ss)",
                attempt + 1,
                attempts,
                len(tickers),
                YFINANCE_TIMEOUT,
            )
            data = yf.download(
                tickers,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                # A execução concorrente do yfinance pode ficar bloqueada quando
                # o Yahoo responde com símbolos inválidos. Lotes menores e
                # execução serial tornam o tempo máximo previsível.
                threads=False,
                timeout=YFINANCE_TIMEOUT,
            )
            if data is not None and not data.empty:
                return data
            logger.warning(f"yfinance retornou vazio (tentativa {attempt + 1}/{attempts})")
        except Exception as e:
            logger.warning(f"Erro yfinance tentativa {attempt + 1}/{attempts}: {e}")
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
) -> int:
    """
    Atualiza preços no banco de dados.

    Args:
        tickers: Lista de tickers (default: IBRX_TICKERS completo)
        start_date: Data inicial (default: última data no banco + 1 dia)
        force_full: Se True, baixa desde 2022-01-01 independente do banco

    Returns:
        Número de registros inseridos/atualizados
    """
    if tickers is None:
        tickers = IBRX_TICKERS

    if force_full:
        start = "2022-01-01"
    elif start_date:
        start = start_date.strftime("%Y-%m-%d")
    else:
        latest = get_latest_price_date()
        if latest:
            next_day = latest + timedelta(days=1)
            start = next_day.strftime("%Y-%m-%d")
        else:
            start = "2022-01-01"

    end = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    if start >= end:
        logger.info("Preços já atualizados até hoje")
        return 0

    logger.info(f"Baixando {len(tickers)} tickers de {start} a {end}...")

    # Lotes pequenos impedem que tickers indisponíveis bloqueiem todo o universo.
    batch_size = YFINANCE_BATCH_SIZE
    total_rows = 0

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        logger.info(f"  Lote {i // batch_size + 1}: {len(batch)} tickers")

        raw = _download_with_retry(batch, start, end)
        if raw is None or raw.empty:
            logger.warning(f"  Lote {i // batch_size + 1}: sem dados")
            continue

        df = _parse_yfinance_data(raw, batch)
        if df.empty:
            continue

        # Remove linhas com Close nulo
        df = df.dropna(subset=["c"])

        rows = upsert_prices(df)
        total_rows += rows
        logger.info(f"  Lote {i // batch_size + 1}: {rows} registros inseridos")

        time.sleep(1)  # Rate limiting

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
