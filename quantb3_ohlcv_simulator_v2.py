"""
QUANTB3 — Gerador OHLCV v2 (mais realista)
==========================================
Melhorias vs v1:
  1. Jumps (Merton) no mercado e no residual idiossincrático
  2. Vol dinâmica EWMA/GARCH-like no residual de cada ação
  3. Fatores setoriais (correlação residual entre ações do mesmo setor)
  4. OHLC com posição calibrada de O/C no range
  5. Volume com persistência (AR) + sensibilidade a |r|
  6. Calendário aproximado de feriados B3

Uso:
    python quantb3_ohlcv_simulator_v2.py --n-days 60 --n-tickers 10 --seed 42
    python quantb3_ohlcv_simulator_v2.py --n-days 120 --tickers PETR4.SA,VALE3.SA,ITUB4.SA

Requisitos: pandas, numpy
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# CONSTANTES / SETORES
# =============================================================================

DEFAULT_CSV_CANDIDATES = [
    "cotacoes_ibrx_ohlcv_completo.csv",
    "artifacts/cotacoes_ibrx_ohlcv_completo.csv",
    "/home/workdir/artifacts/cotacoes_ibrx_ohlcv_completo.csv",
]

BENCHMARKS = ["BOVA11.SA", "SMAL11.SA", "^BVSP"]

# Mapeamento manual ticker -> setor (aprox. IBRX; tickers sem .SA também aceitos)
SECTOR_MAP = {
    # Bancos / financeiro
    "ITUB4": "financeiro", "ITUB3": "financeiro", "BBDC4": "financeiro",
    "BBDC3": "financeiro", "BBAS3": "financeiro", "SANB11": "financeiro",
    "BPAC11": "financeiro", "BPAN4": "financeiro", "B3SA3": "financeiro",
    "CIEL3": "financeiro", "IRBR3": "financeiro", "PSSA3": "financeiro",
    "BBSE3": "financeiro", "CXSE3": "financeiro",
    # Commodities / mineração / siderurgia
    "VALE3": "commodities", "CSNA3": "commodities", "GGBR4": "commodities",
    "GOAU4": "commodities", "USIM5": "commodities", "CMIN3": "commodities",
    "BRAP4": "commodities",
    # Petróleo / energia
    "PETR4": "petroleo", "PETR3": "petroleo", "PRIO3": "petroleo",
    "RECV3": "petroleo", "CSAN3": "petroleo", "UGPA3": "petroleo",
    "VBBR3": "petroleo",
    # Elétricas / utilities
    "ELET3": "utilities", "ELET6": "utilities", "EQTL3": "utilities",
    "ENGI11": "utilities", "CMIG4": "utilities", "CPLE6": "utilities",
    "SBSP3": "utilities", "SAPR11": "utilities", "TAEE11": "utilities",
    "CPFE3": "utilities", "NEOE3": "utilities", "EGIE3": "utilities",
    "AXIA3": "utilities", "AXIA6": "utilities",
    # Varejo / consumo
    "MGLU3": "consumo", "LREN3": "consumo", "ARZZ3": "consumo",
    "SOMA3": "consumo", "PETZ3": "consumo", "ASAI3": "consumo",
    "PCAR3": "consumo", "CRFB3": "consumo", "NTCO3": "consumo",
    "VIVA3": "consumo", "GUAR3": "consumo",
    # Bebidas / alimentos
    "ABEV3": "alimentos", "BRFS3": "alimentos", "JBSS3": "alimentos",
    "MRFG3": "alimentos", "BEEF3": "alimentos", "SMTO3": "alimentos",
    # Shoppers / e-commerce / tech
    "TOTS3": "tech", "LWSA3": "tech", "POSI3": "tech",
    # Saúde
    "RADL3": "saude", "HAPV3": "saude", "RDOR3": "saude",
    "FLRY3": "saude", "QUAL3": "saude",
    # Construção / imobiliário
    "CYRE3": "construcao", "MRVE3": "construcao", "EZTC3": "construcao",
    "DIRR3": "construcao", "CURY3": "construcao", "HBSA3": "construcao",
    # Telecom / mídia
    "VIVT3": "telecom", "TIMS3": "telecom",
    # Papel / celulose
    "SUZB3": "papel", "KLBN11": "papel",
    # Transporte / logística
    "RAIL3": "transporte", "CCRO3": "transporte", "EMBR3": "transporte",
    "GOLL4": "transporte", "AZUL4": "transporte",
    # Outros
    "WEGE3": "industrial", "RENT3": "industrial", "RAIZ4": "industrial",
    "RRRP3": "petroleo", "MULT3": "consumo",
}

# Feriados B3 aproximados (fixos + regras simples; suficiente para simulação)
FIXED_HOLIDAYS_MD = {
    (1, 1),    # Ano Novo
    (4, 21),   # Tiradentes
    (5, 1),    # Trabalho
    (9, 7),    # Independência
    (10, 12),  # N. Sra. Aparecida
    (11, 2),   # Finados
    (11, 15),  # Proclamação
    (12, 25),  # Natal
}


def _ticker_root(t: str) -> str:
    return t.replace(".SA", "").upper()


def get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(_ticker_root(ticker), "outros")


def is_b3_holiday(dt: pd.Timestamp) -> bool:
    if (dt.month, dt.day) in FIXED_HOLIDAYS_MD:
        return True
    # Carnaval / Corpus Christi etc. variam — omitidos de propósito (aproximação)
    return False


def b3_business_days(start: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    """Próximos n dias úteis B3 (seg–sex, sem feriados fixos)."""
    dates = []
    cur = start + pd.Timedelta(days=1)
    while len(dates) < n:
        if cur.weekday() < 5 and not is_b3_holiday(cur):
            dates.append(cur)
        cur += pd.Timedelta(days=1)
    return pd.DatetimeIndex(dates)


# =============================================================================
# CARGA
# =============================================================================

def find_csv(path: Optional[str] = None) -> str:
    if path and Path(path).exists():
        return path
    for p in DEFAULT_CSV_CANDIDATES:
        if Path(p).exists():
            return p
    raise FileNotFoundError("CSV não encontrado. Use --csv caminho/arquivo.csv")


def load_pivots(csv_path: str):
    df = pd.read_csv(csv_path)
    df["Data"] = pd.to_datetime(df["Data"])
    df = df.sort_values(["ticker", "Data"])

    stocks = df[~df["ticker"].isin(BENCHMARKS)].copy()
    bova_df = df[df["ticker"] == "BOVA11.SA"].copy()

    o = stocks.pivot(index="Data", columns="ticker", values="O")
    h = stocks.pivot(index="Data", columns="ticker", values="H")
    l = stocks.pivot(index="Data", columns="ticker", values="L")
    c = stocks.pivot(index="Data", columns="ticker", values="C")
    v = stocks.pivot(index="Data", columns="ticker", values="V")

    min_obs = int(len(c) * 0.7)
    valid = c.dropna(axis=1, thresh=min_obs).columns.tolist()
    o, h, l, c, v = o[valid], h[valid], l[valid], c[valid], v[valid]

    bova = (
        bova_df.set_index("Data")["C"].sort_index().reindex(c.index).ffill()
    )
    return o, h, l, c, v, bova


# =============================================================================
# CALIBRAÇÃO
# =============================================================================

def _student_t_df(residuals: np.ndarray) -> float:
    x = residuals[np.isfinite(residuals)]
    if len(x) < 50:
        return 8.0
    x = x - np.mean(x)
    m2 = np.mean(x ** 2)
    m4 = np.mean(x ** 4)
    if m2 <= 0:
        return 8.0
    kurt = m4 / (m2 ** 2)
    if kurt <= 3.1:
        return 30.0
    df = 6.0 / (kurt - 3.0) + 4.0
    return float(np.clip(df, 4.5, 30.0))


def _calibrate_jumps(rets: np.ndarray, threshold_sigma: float = 2.5) -> dict:
    """Estima probabilidade e tamanho de jumps a partir de outliers."""
    r = rets[np.isfinite(rets)]
    if len(r) < 50:
        return {"p": 0.02, "mu_j": 0.0, "sigma_j": 0.03}
    s = np.std(r)
    if s <= 0:
        return {"p": 0.02, "mu_j": 0.0, "sigma_j": 0.03}
    mask = np.abs(r) > threshold_sigma * s
    p = float(mask.mean())
    p = float(np.clip(p, 0.005, 0.08))
    jumps = r[mask]
    if len(jumps) >= 5:
        mu_j = float(np.mean(jumps))
        sigma_j = float(np.std(jumps))
    else:
        mu_j, sigma_j = 0.0, 3.0 * s
    sigma_j = max(sigma_j, 0.01)
    return {"p": p, "mu_j": mu_j, "sigma_j": sigma_j}


def calibrate_market(bova: pd.Series) -> dict:
    ret = bova.pct_change().dropna()
    ewma_var = ret.pow(2).ewm(alpha=0.06, adjust=False).mean()
    jumps = _calibrate_jumps(ret.values)
    return {
        "mu": float(ret.mean()),
        "sigma": float(ret.std()),
        "last_price": float(bova.iloc[-1]),
        "last_ewma_sigma": float(np.sqrt(ewma_var.iloc[-1])),
        "jumps": jumps,
        "ret_sample": ret.values,
    }


def calibrate_stock(ticker, o, h, l, c, v, bova) -> Optional[dict]:
    if ticker not in c.columns:
        return None
    price = c[ticker].dropna()
    if len(price) < 100:
        return None

    common = price.index.intersection(bova.dropna().index)
    if len(common) < 100:
        return None

    r_i = price.reindex(common).pct_change()
    r_m = bova.reindex(common).pct_change()
    aligned = pd.concat([r_i, r_m], axis=1, keys=["ri", "rm"]).dropna()
    if len(aligned) < 80:
        return None

    rm = aligned["rm"].values
    ri = aligned["ri"].values
    var_m = np.var(rm)
    if var_m <= 0:
        return None
    beta = float(np.cov(ri, rm, ddof=1)[0, 1] / var_m)
    alpha = float(np.mean(ri) - beta * np.mean(rm))
    resid = ri - (alpha + beta * rm)
    sigma_resid = float(max(np.std(resid, ddof=1), 1e-6))
    df_t = _student_t_df(resid)

    # EWMA var do residual (para estado inicial)
    resid_s = pd.Series(resid)
    ewma_var = resid_s.pow(2).ewm(alpha=0.06, adjust=False).mean()
    last_ewma_sig = float(np.sqrt(ewma_var.iloc[-1]))

    # GARCH(1,1) approx via momentos / defaults estáveis
    # ω, α, β com persistência ~0.95
    garch = {"omega": 1e-6, "alpha": 0.08, "beta": 0.88, "last_var": last_ewma_sig ** 2}

    jumps = _calibrate_jumps(resid)

    # Range / gap / posições
    hh = h[ticker].reindex(common)
    ll = l[ticker].reindex(common)
    cc = c[ticker].reindex(common)
    oo = o[ticker].reindex(common)
    range_pct = ((hh - ll) / cc.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    range_mean = float(range_pct.mean()) if len(range_pct) else 0.02
    range_std = float(range_pct.std()) if len(range_pct) > 10 else range_mean * 0.4

    c_shift = cc.shift(1)
    gap = ((oo - c_shift) / c_shift.replace(0, np.nan)).dropna()
    gap_mean = float(gap.mean()) if len(gap) else 0.0
    gap_std = float(gap.std()) if len(gap) > 10 else 0.005

    denom = (hh - ll).replace(0, np.nan)
    o_pos = ((oo - ll) / denom).clip(0, 1).dropna()
    c_pos = ((cc - ll) / denom).clip(0, 1).dropna()

    # Volume AR(1)
    vv = v[ticker].reindex(common).replace(0, np.nan).dropna()
    log_v = np.log(vv.clip(lower=1))
    if len(log_v) > 30:
        x0 = log_v.values[:-1]
        x1 = log_v.values[1:]
        var0 = np.var(x0)
        ar1 = float(np.cov(x0, x1, ddof=1)[0, 1] / var0) if var0 > 0 else 0.3
        ar1 = float(np.clip(ar1, 0.0, 0.95))
        innov = x1 - ar1 * x0
        log_v_std = float(np.std(innov))
    else:
        ar1, log_v_std = 0.4, 0.3

    abs_r = aligned["ri"].abs().reindex(log_v.index).dropna()
    log_v_al = log_v.reindex(abs_r.index).dropna()
    abs_r = abs_r.reindex(log_v_al.index)
    if len(log_v_al) > 50 and abs_r.std() > 0:
        sens = float(np.cov(log_v_al, abs_r, ddof=1)[0, 1] / np.var(abs_r))
    else:
        sens = 5.0

    return {
        "ticker": ticker,
        "sector": get_sector(ticker),
        "alpha": alpha,
        "beta": beta,
        "sigma_resid": sigma_resid,
        "df_t": df_t,
        "garch": garch,
        "jumps": jumps,
        "last_price": float(price.iloc[-1]),
        "range_mean": max(range_mean, 0.005),
        "range_std": max(range_std, 0.002),
        "gap_mean": gap_mean,
        "gap_std": max(gap_std, 0.001),
        "o_pos_mean": float(o_pos.mean()) if len(o_pos) else 0.45,
        "o_pos_std": float(o_pos.std()) if len(o_pos) > 10 else 0.2,
        "c_pos_mean": float(c_pos.mean()) if len(c_pos) else 0.55,
        "c_pos_std": float(c_pos.std()) if len(c_pos) > 10 else 0.2,
        "log_v_mean": float(log_v.mean()),
        "log_v_std": max(log_v_std, 0.1),
        "log_v_ar1": ar1,
        "log_v_last": float(log_v.iloc[-1]),
        "vol_sens": sens,
        "residuals": resid,  # para calibrar fator setorial
    }


def calibrate_sector_factors(
    stocks_cal: Dict[str, dict],
) -> Dict[str, dict]:
    """
    Para cada setor, estima a variância do fator comum residual.
    Modelo: resid_i = σ_s * F_s + σ_idio_i * ε_i
    Aproximação: var do fator = média das cov entre pares do setor.
    """
    sectors: Dict[str, List[str]] = {}
    for t, cal in stocks_cal.items():
        sectors.setdefault(cal["sector"], []).append(t)

    sector_params = {}
    for sec, tickers in sectors.items():
        if len(tickers) < 2:
            sector_params[sec] = {"var_factor": 0.0, "tickers": tickers}
            continue
        # alinhar resíduos pelo comprimento mínimo
        resids = []
        min_len = min(len(stocks_cal[t]["residuals"]) for t in tickers)
        if min_len < 50:
            sector_params[sec] = {"var_factor": 0.0, "tickers": tickers}
            continue
        for t in tickers:
            r = stocks_cal[t]["residuals"][-min_len:]
            resids.append(r - np.mean(r))
        R = np.vstack(resids)  # (n_stocks, T)
        # média das covariâncias off-diagonal
        cov = np.cov(R)
        n = cov.shape[0]
        off = []
        for i in range(n):
            for j in range(i + 1, n):
                off.append(cov[i, j])
        var_f = float(max(np.mean(off), 0.0)) if off else 0.0
        # limita: fator não pode explicar mais que ~70% da var média
        mean_var = float(np.mean(np.diag(cov)))
        var_f = min(var_f, 0.7 * mean_var)
        sector_params[sec] = {"var_factor": var_f, "tickers": tickers, "mean_var": mean_var}
    return sector_params


def calibrate_universe(o, h, l, c, v, bova, tickers: Optional[Sequence[str]] = None):
    mkt = calibrate_market(bova)
    if tickers is None:
        tickers = list(c.columns)
    stocks = {}
    for t in tickers:
        cal = calibrate_stock(t, o, h, l, c, v, bova)
        if cal is not None:
            stocks[t] = cal
    sectors = calibrate_sector_factors(stocks)
    return mkt, stocks, sectors


# =============================================================================
# SIMULAÇÃO
# =============================================================================

def _sample_student_t(df: float, size, rng: np.random.Generator) -> np.ndarray:
    x = rng.standard_t(df, size=size)
    if df > 2:
        x = x / np.sqrt(df / (df - 2))
    return x


def simulate_market_returns(mkt: dict, n_days: int, rng: np.random.Generator) -> np.ndarray:
    mu = mkt["mu"]
    var = mkt["last_ewma_sigma"] ** 2
    lam = 0.94
    jp = mkt["jumps"]
    rets = np.zeros(n_days)
    for t in range(n_days):
        sigma_t = np.sqrt(max(var, 1e-12))
        r = rng.normal(mu, sigma_t)
        # jump
        if rng.random() < jp["p"]:
            r += rng.normal(jp["mu_j"], jp["sigma_j"])
        rets[t] = r
        var = lam * var + (1 - lam) * r ** 2
    return rets


def simulate_sector_factors(
    sectors: Dict[str, dict],
    n_days: int,
    rng: np.random.Generator,
) -> Dict[str, np.ndarray]:
    """Um caminho de fator comum por setor."""
    out = {}
    for sec, p in sectors.items():
        vf = p.get("var_factor", 0.0)
        if vf <= 0:
            out[sec] = np.zeros(n_days)
        else:
            out[sec] = rng.normal(0, np.sqrt(vf), size=n_days)
    return out


def simulate_stock_ohlcv(
    cal: dict,
    market_rets: np.ndarray,
    sector_factor: np.ndarray,
    rng: np.random.Generator,
) -> pd.DataFrame:
    n = len(market_rets)
    alpha, beta = cal["alpha"], cal["beta"]
    df_t = cal["df_t"]
    g = cal["garch"]
    jp = cal["jumps"]

    # Variância idiossincrática: total residual var - sector factor var
    # sigma_idio^2 ≈ sigma_resid^2 - var_factor (aproximado via garch last)
    var = g["last_var"]
    omega, a_g, b_g = g["omega"], g["alpha"], g["beta"]

    rets = np.zeros(n)
    for t in range(n):
        sig = np.sqrt(max(var, 1e-12))
        eps = _sample_student_t(df_t, 1, rng)[0] * sig
        # fator setorial já vem em unidades de retorno
        r = alpha + beta * market_rets[t] + sector_factor[t] + eps
        if rng.random() < jp["p"]:
            r += rng.normal(jp["mu_j"], jp["sigma_j"])
        rets[t] = r
        # GARCH update no residual efetivo (r - alpha - beta*rm - sector)
        resid_t = r - alpha - beta * market_rets[t] - sector_factor[t]
        var = omega + a_g * resid_t ** 2 + b_g * var

    # Preços
    c0 = cal["last_price"]
    closes = c0 * np.cumprod(1 + rets)

    opens = np.zeros(n)
    highs = np.zeros(n)
    lows = np.zeros(n)
    volumes = np.zeros(n)

    prev_c = c0
    log_v_prev = cal["log_v_last"]

    for t in range(n):
        gap = float(np.clip(rng.normal(cal["gap_mean"], cal["gap_std"]), -0.08, 0.08))
        o_t = prev_c * (1 + gap)
        c_t = closes[t]
        abs_r = abs(rets[t])

        # Range
        range_base = rng.normal(cal["range_mean"], cal["range_std"])
        range_base = max(range_base, abs_r * 1.1, 0.004)
        range_pct = range_base * (1 + abs_r / (cal["range_mean"] + 1e-6))
        range_pct = float(np.clip(range_pct, 0.004, 0.08))

        # Posições de O e C no range (calibradas)
        o_pos = float(np.clip(rng.normal(cal["o_pos_mean"], cal["o_pos_std"]), 0.05, 0.95))
        c_pos = float(np.clip(rng.normal(cal["c_pos_mean"], cal["c_pos_std"]), 0.05, 0.95))

        # Constrói L, H a partir de O, C e range
        body_high = max(o_t, c_t)
        body_low = min(o_t, c_t)
        # range total desejado
        span = max(body_high - body_low, body_high * range_pct * 0.3)
        target_span = max(span, body_high * range_pct)
        # distribui pavios
        extra = max(target_span - (body_high - body_low), 0)
        wick_up = extra * (1 - max(o_pos, c_pos)) * rng.uniform(0.3, 1.0)
        wick_dn = extra * min(o_pos, c_pos) * rng.uniform(0.3, 1.0)
        h_t = body_high + wick_up
        l_t = body_low - wick_dn
        h_t = max(h_t, body_high)
        l_t = min(l_t, body_low)
        if (h_t - l_t) / max(c_t, 1e-6) > 0.08:
            mid = (h_t + l_t) / 2.0
            h_t = max(mid * 1.04, body_high)
            l_t = min(mid * 0.96, body_low)
        if h_t <= l_t:
            h_t = l_t * 1.002

        # Volume AR(1) + sensibilidade a |r|
        log_v = (
            cal["log_v_mean"] * (1 - cal["log_v_ar1"])
            + cal["log_v_ar1"] * log_v_prev
            + cal["vol_sens"] * abs_r * 0.5
            + rng.normal(0, cal["log_v_std"])
        )
        vol_t = float(max(np.exp(log_v), 1.0))
        log_v_prev = log_v

        opens[t] = o_t
        highs[t] = h_t
        lows[t] = l_t
        volumes[t] = vol_t
        prev_c = c_t

    return pd.DataFrame({"O": opens, "H": highs, "L": lows, "C": closes, "V": volumes})


def simulate_universe(
    mkt: dict,
    stocks_cal: Dict[str, dict],
    sectors: Dict[str, dict],
    n_days: int,
    start_date: Optional[pd.Timestamp] = None,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    market_rets = simulate_market_returns(mkt, n_days, rng)
    sector_paths = simulate_sector_factors(sectors, n_days, rng)

    if start_date is None:
        start_date = pd.Timestamp.today().normalize()
    dates = b3_business_days(start_date, n_days)

    frames = []
    for ticker, cal in stocks_cal.items():
        sub_rng = np.random.default_rng(int(rng.integers(0, 2**31 - 1)))
        sec = cal["sector"]
        sf = sector_paths.get(sec, np.zeros(n_days))
        ohlcv = simulate_stock_ohlcv(cal, market_rets, sf, sub_rng)
        ohlcv["Data"] = dates
        ohlcv["ticker"] = ticker
        frames.append(ohlcv[["Data", "ticker", "O", "H", "L", "C", "V"]])

    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["Data", "ticker"]).reset_index(drop=True)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Simulador OHLCV v2 (jumps + GARCH + setores)")
    parser.add_argument("--csv", type=str, default=None)
    parser.add_argument("--n-days", type=int, default=60)
    parser.add_argument("--tickers", type=str, default=None)
    parser.add_argument("--n-tickers", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--out", type=str, default="ohlcv_simulado_v2.csv")
    args = parser.parse_args()

    csv_path = find_csv(args.csv)
    print(f"CSV: {csv_path}")
    o, h, l, c, v, bova = load_pivots(csv_path)
    print(f"Histórico: {c.shape[0]} dias × {c.shape[1]} tickers")

    if args.tickers:
        tickers = []
        for t in args.tickers.split(","):
            t = t.strip()
            if t in c.columns:
                tickers.append(t)
            elif f"{t}.SA" in c.columns:
                tickers.append(f"{t}.SA")
            else:
                print(f"  Aviso: {t} não encontrado")
    else:
        tickers = list(v.mean().sort_values(ascending=False).head(args.n_tickers).index)

    if not tickers:
        raise SystemExit("Nenhum ticker válido.")

    print(f"Tickers ({len(tickers)}): {', '.join(tickers)}")
    print("Calibrando (mercado + ações + setores)...")
    mkt, stocks_cal, sectors = calibrate_universe(o, h, l, c, v, bova, tickers)
    print(f"  Mercado μ={mkt['mu']*100:.3f}%/dia  σ={mkt['sigma']*100:.3f}%  "
          f"jump_p={mkt['jumps']['p']*100:.1f}%")
    print(f"  Ações: {len(stocks_cal)} | Setores: {list(sectors.keys())}")
    for sec, sp in sectors.items():
        vf = sp.get("var_factor", 0)
        print(f"    {sec}: var_fator={vf:.6f}  n={len(sp.get('tickers', []))}")

    start = pd.Timestamp(args.start) if args.start else pd.Timestamp.today().normalize()
    print(f"Simulando {args.n_days} dias B3 a partir de {start.date()} (seed={args.seed})...")
    sim = simulate_universe(mkt, stocks_cal, sectors, args.n_days, start_date=start, seed=args.seed)

    out_path = Path(args.out)
    sim.to_csv(out_path, index=False)
    print(f"\nSalvo: {out_path.resolve()}")
    print(f"  Linhas: {len(sim)} | {sim['Data'].min().date()} → {sim['Data'].max().date()}")
    print("\nAmostra:")
    print(sim.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
