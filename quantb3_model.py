"""
QUANTB3 — Modelo Oficial + Backtest Realista
=============================================
Modelo: LightGBM_Fwd10_Sticky_LiqP10_Realistic (v2.1)
Referência: QUANTB3_Memorial_LightGBM_Final.md

Uso básico:
    from quantb3_model import QuantB3Model, run_backtest

    model = QuantB3Model(prices, highs, lows, volumes, bova)
    rankings = model.generate_rankings()          # dict[date -> list[ticker]]
    result = run_backtest(rankings, prices, highs, lows)

Requisitos:
    pip install pandas numpy lightgbm scikit-learn
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

try:
    import lightgbm as lgb
except ImportError as e:
    raise ImportError("Instale lightgbm: pip install lightgbm") from e


# =============================================================================
# PARÂMETROS OFICIAIS (Memorial v2.1)
# =============================================================================

CAPITAL = 2000.0
N_POSITIONS = 8
FORWARD_DAYS = 10
TRAIN_MIN_DAYS = 378
LIQ_PERCENTILE = 0.10
STICKY_BUFFER = 4

STOP_PCT = -0.05
TAKE_RR = 2.5

SLIPPAGE_ENTRY = 0.0005
SLIPPAGE_STOP = 0.0010
SLIPPAGE_TAKE = 0.0005
COST_PCT = 0.0003

LGBM_PARAMS = dict(
    n_estimators=150,
    max_depth=3,
    learning_rate=0.03,
    subsample=0.7,
    colsample_bytree=0.7,
    reg_alpha=0.5,
    reg_lambda=2.0,
    min_child_samples=50,
    random_state=42,
    verbosity=-1,
)

FEATURE_NAMES = [
    "mom_5", "mom_10", "mom_21", "mom_42", "mom_63", "mom_accel",
    "vol_10", "vol_21", "mom_vol_adj",
    "vol_rel", "vol_trend",
    "dist_high_63", "dist_low_63", "price_pos_63",
    "excesso_10", "excesso_21",
    "rsi_14", "rev_5",
]


# =============================================================================
# FEATURES
# =============================================================================

def build_features(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    benchmark: pd.Series,
) -> Dict[str, pd.DataFrame]:
    """Constrói as 18 features oficiais do modelo."""
    rets = prices.pct_change()
    feat: Dict[str, pd.DataFrame] = {}

    for w in [5, 10, 21, 42, 63]:
        feat[f"mom_{w}"] = prices.pct_change(w)
    feat["mom_accel"] = feat["mom_10"] - feat["mom_21"]

    for w in [10, 21]:
        feat[f"vol_{w}"] = rets.rolling(w).std()
    feat["mom_vol_adj"] = feat["mom_10"] / feat["vol_21"].replace(0, np.nan)

    vol_ma21 = volumes.rolling(21).mean()
    feat["vol_rel"] = volumes / vol_ma21.replace(0, np.nan)
    feat["vol_trend"] = vol_ma21 / volumes.rolling(63).mean().replace(0, np.nan)

    roll_max = prices.rolling(63).max()
    roll_min = prices.rolling(63).min()
    feat["dist_high_63"] = prices / roll_max - 1
    feat["dist_low_63"] = prices / roll_min - 1
    feat["price_pos_63"] = (prices - roll_min) / (roll_max - roll_min).replace(0, np.nan)

    for w in [10, 21]:
        feat[f"excesso_{w}"] = feat[f"mom_{w}"].sub(benchmark.pct_change(w), axis=0)

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
    """Empilha features + target em formato longo (Data, ticker, features..., fwd_10)."""
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


# =============================================================================
# MODELO
# =============================================================================

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
        self.vol_threshold = float(self.panel["vol_ma21"].quantile(self.liq_percentile))

    def _train_lgbm(self, X: np.ndarray, y: np.ndarray) -> lgb.LGBMRegressor:
        model = lgb.LGBMRegressor(**self.lgbm_params)
        model.fit(X, y)
        return model

    def generate_rankings(
        self,
        only_mondays: bool = True,
    ) -> Dict[pd.Timestamp, List[str]]:
        """
        Walk-forward: a cada segunda (ou cada data), treina com dados anteriores,
        aplica filtro de liquidez e sticky turnover. Retorna dict data -> top N tickers.
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

        for mon in signal_dates:
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
                score_history[mon] = pd.Series(scores, index=test_liq["ticker"].values)
            except Exception:
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
            # completa se ainda faltar
            for t in top_raw:
                if len(new_port) >= self.n_positions:
                    break
                if t not in new_port:
                    new_port.append(t)

            rankings[mon] = new_port[: self.n_positions]
            prev = rankings[mon]

        return rankings

    def score_on_date(self, date: pd.Timestamp) -> pd.Series:
        """Score LGBM para uma data específica (útil para relatório semanal)."""
        train = self.panel[self.panel["Data"] < date]
        test = self.panel[self.panel["Data"] == date]
        if len(train) < 1000 or len(test) == 0:
            return pd.Series(dtype=float)

        test_liq = test[test["vol_ma21"] >= self.vol_threshold]
        if len(test_liq) < self.n_positions:
            test_liq = test

        model = self._train_lgbm(train[FEATURE_NAMES].values, train["fwd_10"].values)
        scores = model.predict(test_liq[FEATURE_NAMES].values)
        return pd.Series(scores, index=test_liq["ticker"].values).sort_values(ascending=False)


# =============================================================================
# BACKTEST REALISTA
# =============================================================================

def triangular_price(low: float, high: float, close: float) -> float:
    """Preço probabilístico triangular centrado no Close, limitado ao range do dia."""
    if np.isnan(low) or np.isnan(high) or np.isnan(close) or high <= low:
        return close if not np.isnan(close) else np.nan
    close = float(np.clip(close, low, high))
    return float(np.random.triangular(low, close, high))


def run_backtest(
    rankings: Dict[pd.Timestamp, List[str]],
    prices: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    capital: float = CAPITAL,
    n_positions: int = N_POSITIONS,
    stop_pct: float = STOP_PCT,
    take_rr: float = TAKE_RR,
    slippage_entry: float = SLIPPAGE_ENTRY,
    slippage_stop: float = SLIPPAGE_STOP,
    slippage_take: float = SLIPPAGE_TAKE,
    cost_pct: float = COST_PCT,
    seed: int = 42,
    start_eval: Optional[pd.Timestamp] = None,
) -> dict:
    """
    Backtest realista:
    - Sinal na segunda → execução na terça
    - Preço triangular (Low, Close, High) + slippage + custo B3
    - Stop -5% / Take 1:2,5 verificados no High/Low diário

    Retorna dict com: total_return, cagr, sharpe, max_dd, final_equity,
                      n_trades, equity (Series), trades (list)
    """
    np.random.seed(seed)
    dates = prices.index.sort_values()

    # Mapa segunda → próxima terça
    monday_to_tuesday: Dict[pd.Timestamp, pd.Timestamp] = {}
    for i, d in enumerate(dates):
        if d.weekday() == 0:
            for j in range(i + 1, min(i + 5, len(dates))):
                if dates[j].weekday() == 1:
                    monday_to_tuesday[d] = dates[j]
                    break

    cash = capital
    positions: Dict[str, dict] = {}  # ticker -> {qty, entry, stop, take}
    equity_curve = []
    trades = []
    pending_orders = None
    pending_signal_date = None
    n_trades = 0

    for date in dates:
        px = prices.loc[date]
        hi = highs.loc[date]
        lo = lows.loc[date]

        # --- Executar ordens pendentes na terça ---
        if pending_orders is not None and pending_signal_date is not None:
            exec_date = monday_to_tuesday.get(pending_signal_date)
            if exec_date is not None and date == exec_date:
                pos_value = sum(
                    p["qty"] * px[t]
                    for t, p in positions.items()
                    if t in px.index and not np.isnan(px[t])
                )
                equity = cash + pos_value
                target_value = equity / n_positions

                # Vender saídas
                for t in list(positions.keys()):
                    if t not in pending_orders:
                        ep = triangular_price(
                            lo.get(t, np.nan) if hasattr(lo, "get") else np.nan,
                            hi.get(t, np.nan) if hasattr(hi, "get") else np.nan,
                            px.get(t, np.nan) if hasattr(px, "get") else np.nan,
                        )
                        if np.isnan(ep) or ep <= 0:
                            ep = px.get(t, positions[t]["entry"])
                        ep *= 1 - slippage_entry
                        proceeds = positions[t]["qty"] * ep * (1 - cost_pct)
                        cash += proceeds
                        trades.append(
                            {"date": date, "ticker": t, "side": "SELL",
                             "qty": positions[t]["qty"], "price": ep}
                        )
                        del positions[t]
                        n_trades += 1

                # Comprar / ajustar
                for t, target_qty in pending_orders.items():
                    raw = triangular_price(
                        lo.get(t, np.nan) if hasattr(lo, "get") else np.nan,
                        hi.get(t, np.nan) if hasattr(hi, "get") else np.nan,
                        px.get(t, np.nan) if hasattr(px, "get") else np.nan,
                    )
                    if np.isnan(raw) or raw <= 0:
                        continue
                    ep = raw * (1 + slippage_entry)
                    cur = positions[t]["qty"] if t in positions else 0
                    diff = target_qty - cur

                    if diff > 0:
                        cost = diff * ep * (1 + cost_pct)
                        if cost <= cash:
                            cash -= cost
                            stop_p = ep * (1 + stop_pct) * (1 - slippage_stop)
                            risk = ep - stop_p
                            take_p = (ep + risk * take_rr) * (1 - slippage_take)
                            positions[t] = {
                                "qty": cur + diff,
                                "entry": ep,
                                "stop": stop_p,
                                "take": take_p,
                            }
                            trades.append(
                                {"date": date, "ticker": t, "side": "BUY",
                                 "qty": diff, "price": ep}
                            )
                            n_trades += 1
                    elif diff < 0:
                        cash += abs(diff) * raw * (1 - slippage_entry) * (1 - cost_pct)
                        positions[t]["qty"] = target_qty
                        trades.append(
                            {"date": date, "ticker": t, "side": "SELL",
                             "qty": abs(diff), "price": raw * (1 - slippage_entry)}
                        )
                        n_trades += 1

                pending_orders = None
                pending_signal_date = None

        # --- Stops / Takes ---
        to_close = []
        for t, pos in list(positions.items()):
            if t not in px.index or np.isnan(px[t]):
                continue
            day_low = lo[t] if t in lo.index and not np.isnan(lo[t]) else px[t]
            day_high = hi[t] if t in hi.index and not np.isnan(hi[t]) else px[t]

            if pos["stop"] and day_low <= pos["stop"]:
                cash += pos["qty"] * pos["stop"] * (1 - cost_pct)
                trades.append(
                    {"date": date, "ticker": t, "side": "STOP",
                     "qty": pos["qty"], "price": pos["stop"]}
                )
                to_close.append(t)
                n_trades += 1
            elif pos["take"] and day_high >= pos["take"]:
                cash += pos["qty"] * pos["take"] * (1 - cost_pct)
                trades.append(
                    {"date": date, "ticker": t, "side": "TAKE",
                     "qty": pos["qty"], "price": pos["take"]}
                )
                to_close.append(t)
                n_trades += 1
        for t in to_close:
            del positions[t]

        # --- Sinal na segunda ---
        if date in rankings:
            top = rankings[date]
            pos_value = sum(
                p["qty"] * px[t]
                for t, p in positions.items()
                if t in px.index and not np.isnan(px[t])
            )
            equity = cash + pos_value
            target_value = equity / n_positions
            orders = {}
            for t in top:
                pref = px.get(t, np.nan) if hasattr(px, "get") else np.nan
                if np.isnan(pref) or pref <= 0:
                    continue
                qty = int(target_value / pref)
                if qty > 0:
                    orders[t] = qty
            if orders:
                pending_orders = orders
                pending_signal_date = date

        pos_value = sum(
            p["qty"] * px[t]
            for t, p in positions.items()
            if t in px.index and not np.isnan(px[t])
        )
        equity_curve.append({"Data": date, "Equity": cash + pos_value})

    eq = pd.DataFrame(equity_curve).set_index("Data")

    if start_eval is not None:
        eq = eq.loc[eq.index >= start_eval]
        if len(eq) < 20:
            return {}
        first = eq["Equity"].iloc[0]
        total_ret = eq["Equity"].iloc[-1] / first - 1
        final = eq["Equity"].iloc[-1] * (capital / first)
    else:
        first = capital
        total_ret = eq["Equity"].iloc[-1] / capital - 1
        final = eq["Equity"].iloc[-1]

    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 0.01)
    cagr = (eq["Equity"].iloc[-1] / first) ** (1 / years) - 1
    ret = eq["Equity"].pct_change()
    vol = ret.std() * np.sqrt(252)
    sharpe = (ret.mean() * 252) / vol if vol > 0 else 0.0
    max_dd = (eq["Equity"] / eq["Equity"].cummax() - 1).min()

    return {
        "total_return": total_ret,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "final_equity": final,
        "n_trades": n_trades,
        "equity": eq["Equity"],
        "trades": trades,
    }


# =============================================================================
# HELPERS DE DADOS
# =============================================================================

def load_ohlcv_csv(
    path: str,
    benchmarks: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    """
    Carrega CSV no formato: Data, ticker, O, H, L, C, V
    Retorna: prices, highs, lows, volumes, bova (Series)
    """
    if benchmarks is None:
        benchmarks = ["BOVA11.SA", "SMAL11.SA", "^BVSP"]

    df = pd.read_csv(path)
    df["Data"] = pd.to_datetime(df["Data"])
    df = df.sort_values(["ticker", "Data"]).reset_index(drop=True)

    stocks = df[~df["ticker"].isin(benchmarks)].copy()
    bench = df[df["ticker"] == "BOVA11.SA"].copy()

    prices = stocks.pivot(index="Data", columns="ticker", values="C")
    highs = stocks.pivot(index="Data", columns="ticker", values="H")
    lows = stocks.pivot(index="Data", columns="ticker", values="L")
    volumes = stocks.pivot(index="Data", columns="ticker", values="V")

    min_obs = int(len(prices) * 0.7)
    valid = prices.dropna(axis=1, thresh=min_obs).columns.tolist()
    prices = prices[valid]
    highs = highs[valid]
    lows = lows[valid]
    volumes = volumes[valid]

    bova = (
        bench.set_index("Data")["C"]
        .sort_index()
        .reindex(prices.index)
        .ffill()
    )
    return prices, highs, lows, volumes, bova


# =============================================================================
# EXEMPLO DE USO
# =============================================================================

if __name__ == "__main__":
    import sys

    csv_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "cotacoes_ibrx_ohlcv_completo.csv"
    )

    print("Carregando dados...")
    prices, highs, lows, volumes, bova = load_ohlcv_csv(csv_path)
    print(f"  {prices.shape[0]} dias × {prices.shape[1]} tickers")

    print("Gerando rankings (LGBM + sticky + liquidez)...")
    model = QuantB3Model(prices, volumes, bova)
    rankings = model.generate_rankings()
    print(f"  {len(rankings)} datas de sinal")

    print("Rodando backtest realista...")
    result = run_backtest(rankings, prices, highs, lows, seed=42)

    print("\n=== RESULTADO ===")
    print(f"  CAGR:          {result['cagr']*100:.2f}%")
    print(f"  Sharpe:        {result['sharpe']:.2f}")
    print(f"  Max Drawdown:  {result['max_dd']*100:.1f}%")
    print(f"  Retorno total: {result['total_return']*100:.1f}%")
    print(f"  Capital final: R$ {result['final_equity']:.0f}")
    print(f"  Nº trades:     {result['n_trades']}")
