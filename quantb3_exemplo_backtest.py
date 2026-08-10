"""
QUANTB3 — Exemplo de backtest completo
======================================
Uso:
    python quantb3_exemplo_backtest.py [caminho_csv]

Se não passar caminho, tenta:
    cotacoes_ibrx_ohlcv_completo.csv
"""

import sys
from pathlib import Path

from quantb3_model import (
    QuantB3Model,
    run_backtest,
    load_ohlcv_csv,
    CAPITAL,
)


def main():
    candidates = []
    if len(sys.argv) > 1:
        candidates.append(sys.argv[1])
    candidates += [
        "cotacoes_ibrx_ohlcv_completo.csv",
        "artifacts/cotacoes_ibrx_ohlcv_completo.csv",
        "/home/workdir/artifacts/cotacoes_ibrx_ohlcv_completo.csv",
    ]

    csv_path = None
    for p in candidates:
        if Path(p).exists():
            csv_path = p
            break

    if csv_path is None:
        print("CSV não encontrado. Passe o caminho:")
        print("  python quantb3_exemplo_backtest.py /caminho/cotacoes_ibrx_ohlcv_completo.csv")
        sys.exit(1)

    print(f"Dados: {csv_path}")
    prices, highs, lows, volumes, bova = load_ohlcv_csv(csv_path)
    print(f"  {prices.shape[0]} pregões × {prices.shape[1]} tickers")
    print(f"  Período: {prices.index.min().date()} → {prices.index.max().date()}")

    print("\n[1] Modelo LightGBM + sticky + liquidez P10...")
    model = QuantB3Model(prices, volumes, bova)
    rankings = model.generate_rankings(only_mondays=True)
    print(f"  Rankings gerados: {len(rankings)}")

    print("\n[2] Backtest realista (1 seed)...")
    res = run_backtest(rankings, prices, highs, lows, seed=42)

    print("\n" + "=" * 50)
    print("RESULTADO — LightGBM_Fwd10_Sticky_LiqP10")
    print("=" * 50)
    print(f"  Capital inicial: R$ {CAPITAL:,.2f}")
    print(f"  CAGR:            {res['cagr']*100:7.2f}%")
    print(f"  Sharpe:          {res['sharpe']:7.2f}")
    print(f"  Max Drawdown:    {res['max_dd']*100:7.1f}%")
    print(f"  Retorno total:   {res['total_return']*100:7.1f}%")
    print(f"  Capital final:   R$ {res['final_equity']:,.0f}")
    print(f"  Nº trades:       {res['n_trades']}")

    # Último ano
    start_year = prices.index.max() - pd.DateOffset(years=1)
    res_y = run_backtest(
        rankings, prices, highs, lows, seed=42, start_eval=start_year
    )
    if res_y:
        print("\n--- Último ano ---")
        print(f"  Retorno:         {res_y['total_return']*100:7.1f}%")
        print(f"  Sharpe:          {res_y['sharpe']:7.2f}")
        print(f"  Max Drawdown:    {res_y['max_dd']*100:7.1f}%")
        print(f"  Capital final*:  R$ {res_y['final_equity']:,.0f}")
        print("  *escalado para R$ 2.000 no início do período")

    # Salva equity
    out = Path("equity_curve_backtest.csv")
    res["equity"].to_csv(out, header=["Equity"])
    print(f"\nEquity curve salva em: {out.resolve()}")


if __name__ == "__main__":
    import pandas as pd  # noqa: F401 — usado no last-year offset
    main()
