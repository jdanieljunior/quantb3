"""Worker isolado para baixar um lote do Yahoo Finance."""

from __future__ import annotations

import sys
from pathlib import Path

import yfinance as yf

from config.settings import YFINANCE_TIMEOUT


def main() -> None:
    result_path = Path(sys.argv[1])
    start = sys.argv[2]
    end = sys.argv[3]
    tickers = sys.argv[4:]

    data = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=False,
        timeout=YFINANCE_TIMEOUT,
    )
    data.to_pickle(result_path)


if __name__ == "__main__":
    main()
