"""
QuantB3 — Dashboard Streamlit
Cockpit quantitativo para acompanhamento da simulação.

Deploy: Streamlit Community Cloud
Autenticação: senha simples via st.secrets
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    CAPITAL,
    N_POSITIONS,
    SIMULATION_LABEL,
    STOP_PCT,
    TAKE_RR,
)

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================

st.set_page_config(
    page_title="QuantB3 | Cockpit Quantitativo",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS customizado
st.markdown("""
<style>
    /* Fonte e cores */
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Inter:wght@300;400;500;600;700&display=swap');

    .main { background-color: #0a0e1a; }
    .stApp { background-color: #0a0e1a; }

    /* Cards de métricas */
    .metric-card {
        background: linear-gradient(135deg, #111827 0%, #1a2332 100%);
        border: 1px solid #1e3a5f;
        border-radius: 8px;
        padding: 1.2rem;
        margin: 0.3rem 0;
    }

    .metric-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.75rem;
        font-weight: 500;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.3rem;
    }

    .metric-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.6rem;
        font-weight: 600;
        color: #e2e8f0;
    }

    .metric-delta-pos { color: #10b981; font-size: 0.85rem; }
    .metric-delta-neg { color: #ef4444; font-size: 0.85rem; }

    /* Badges de ação */
    .badge-buy {
        background: #064e3b;
        color: #6ee7b7;
        padding: 2px 8px;
        border-radius: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-sell {
        background: #450a0a;
        color: #fca5a5;
        padding: 2px 8px;
        border-radius: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-hold {
        background: #1e3a5f;
        color: #93c5fd;
        padding: 2px 8px;
        border-radius: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-out {
        background: #1f2937;
        color: #9ca3af;
        padding: 2px 8px;
        border-radius: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.75rem;
        font-weight: 600;
    }

    /* Simulação banner */
    .sim-banner {
        background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
        border-left: 4px solid #f59e0b;
        padding: 0.6rem 1rem;
        border-radius: 0 6px 6px 0;
        font-family: 'Inter', sans-serif;
        font-size: 0.8rem;
        color: #fbbf24;
        margin-bottom: 1rem;
    }

    /* Tabelas */
    .stDataFrame { border-radius: 8px; overflow: hidden; }

    /* Sidebar */
    .css-1d391kg { background-color: #0f172a; }

    /* Títulos de seção */
    .section-title {
        font-family: 'Inter', sans-serif;
        font-size: 0.7rem;
        font-weight: 600;
        color: #4b5563;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        padding: 0.5rem 0;
        border-bottom: 1px solid #1e293b;
        margin-bottom: 1rem;
    }

    /* Login */
    .login-container {
        max-width: 400px;
        margin: 5rem auto;
        padding: 2rem;
        background: #111827;
        border: 1px solid #1e3a5f;
        border-radius: 12px;
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# AUTENTICAÇÃO
# =============================================================================

def check_password() -> bool:
    """Verifica autenticação por senha com hash SHA-256."""

    def _hash(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    # Pega hash configurado (Streamlit Secrets ou env var)
    stored_hash = ""
    try:
        stored_hash = st.secrets.get("DASHBOARD_PASSWORD_HASH", "")
    except Exception:
        pass

    if not stored_hash:
        stored_hash = os.getenv("DASHBOARD_PASSWORD_HASH", "")

    if not stored_hash:
        # Sem senha configurada: acesso livre (dev mode)
        return True

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    # Tela de login
    st.markdown("""
    <div style='text-align:center; padding: 3rem 0 1rem 0;'>
        <div style='font-family: JetBrains Mono, monospace; font-size: 2rem;
                    font-weight: 600; color: #e2e8f0; letter-spacing: -0.02em;'>
            QUANT<span style='color: #3b82f6;'>B3</span>
        </div>
        <div style='font-family: Inter, sans-serif; font-size: 0.8rem;
                    color: #4b5563; margin-top: 0.3rem; letter-spacing: 0.1em;
                    text-transform: uppercase;'>
            Cockpit Quantitativo
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("---")
        password = st.text_input(
            "Senha de acesso",
            type="password",
            placeholder="Digite sua senha...",
            key="login_password",
        )
        if st.button("Entrar", use_container_width=True, type="primary"):
            if _hash(password) == stored_hash:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Senha incorreta")

    return False


# =============================================================================
# FUNÇÕES DE DADOS (com cache)
# =============================================================================

@st.cache_data(ttl=300)  # Cache por 5 minutos
def load_equity_curve() -> pd.DataFrame:
    """Carrega curva de equity do banco."""
    try:
        from src.db.repositories import get_equity_curve
        df = get_equity_curve()
        return df
    except Exception as e:
        st.warning(f"Erro ao carregar equity: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_current_positions() -> list:
    """Carrega posições atuais."""
    try:
        from src.db.repositories import get_current_positions
        return get_current_positions()
    except Exception as e:
        st.warning(f"Erro ao carregar posições: {e}")
        return []


@st.cache_data(ttl=300)
def load_latest_signals() -> list:
    """Carrega sinais mais recentes."""
    try:
        from src.db.repositories import get_latest_signal_date, get_signals
        latest_date = get_latest_signal_date()
        if latest_date:
            return get_signals(latest_date)
        return []
    except Exception as e:
        st.warning(f"Erro ao carregar sinais: {e}")
        return []


@st.cache_data(ttl=300)
def load_recent_orders(days: int = 14) -> list:
    """Carrega ordens recentes."""
    try:
        from src.db.repositories import get_orders
        start = date.today() - timedelta(days=days)
        return get_orders(start_date=start)
    except Exception as e:
        st.warning(f"Erro ao carregar ordens: {e}")
        return []


@st.cache_data(ttl=300)
def load_recent_runs(limit: int = 20) -> list:
    """Carrega histórico de jobs."""
    try:
        from src.db.repositories import get_runs
        return get_runs(limit=limit)
    except Exception as e:
        st.warning(f"Erro ao carregar runs: {e}")
        return []


@st.cache_data(ttl=60)
def load_current_prices(tickers: list) -> dict:
    """Carrega preços atuais via yfinance."""
    if not tickers:
        return {}
    try:
        import yfinance as yf
        data = yf.download(
            tickers,
            period="2d",
            auto_adjust=True,
            progress=False,
        )
        if data.empty:
            return {}
        if isinstance(data.columns, pd.MultiIndex):
            closes = data["Close"].iloc[-1]
        else:
            closes = data["Close"]
        return closes.to_dict()
    except Exception:
        return {}


# =============================================================================
# COMPONENTES DE UI
# =============================================================================

def render_metric_card(label: str, value: str, delta: Optional[str] = None, delta_positive: bool = True):
    """Renderiza um card de métrica."""
    delta_html = ""
    if delta:
        cls = "metric-delta-pos" if delta_positive else "metric-delta-neg"
        icon = "▲" if delta_positive else "▼"
        delta_html = f'<div class="{cls}">{icon} {delta}</div>'

    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


def render_action_badge(action: str) -> str:
    """Retorna HTML de badge para ação."""
    cls_map = {
        "BUY": "badge-buy",
        "SELL": "badge-sell",
        "HOLD": "badge-hold",
        "OUT": "badge-out",
        "STOP": "badge-sell",
        "TAKE": "badge-buy",
    }
    cls = cls_map.get(action, "badge-out")
    return f'<span class="{cls}">{action}</span>'


def format_currency(value: float) -> str:
    """Formata valor como moeda brasileira."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_pct(value: float) -> str:
    """Formata valor como percentual."""
    return f"{value:+.2f}%"


# =============================================================================
# PÁGINAS DO DASHBOARD
# =============================================================================

def page_home():
    """Página inicial — resumo geral."""
    st.markdown('<div class="sim-banner">⚠️  OPERAÇÃO SIMULADA — SEM CAPITAL REAL</div>', unsafe_allow_html=True)

    # Carrega dados
    equity_df = load_equity_curve()
    positions = load_current_positions()
    signals = load_latest_signals()

    # Métricas principais
    col1, col2, col3, col4 = st.columns(4)

    if not equity_df.empty:
        last = equity_df.iloc[-1]
        equity = last["equity"]
        cash = last["cash"]
        pos_value = last["pos_value"]
        n_pos = last.get("n_positions", len(positions))

        # Variação desde início
        first_equity = equity_df.iloc[0]["equity"]
        total_ret = (equity / first_equity - 1) * 100
        ret_positive = total_ret >= 0

        # Variação semanal
        week_ago = equity_df[equity_df["date"] <= (pd.Timestamp.now() - pd.Timedelta(days=7))]
        if not week_ago.empty:
            week_ret = (equity / week_ago.iloc[-1]["equity"] - 1) * 100
        else:
            week_ret = 0.0

        with col1:
            render_metric_card(
                "Patrimônio Total",
                format_currency(equity),
                format_pct(total_ret),
                ret_positive,
            )
        with col2:
            render_metric_card("Caixa Disponível", format_currency(cash))
        with col3:
            render_metric_card("Em Posições", format_currency(pos_value))
        with col4:
            render_metric_card(
                "Posições Ativas",
                str(int(n_pos)),
                f"{format_pct(week_ret)} (7d)",
                week_ret >= 0,
            )
    else:
        with col1:
            render_metric_card("Patrimônio Total", format_currency(CAPITAL), "Início da simulação")
        with col2:
            render_metric_card("Caixa Disponível", format_currency(CAPITAL))
        with col3:
            render_metric_card("Em Posições", "R$ 0,00")
        with col4:
            render_metric_card("Posições Ativas", "0")

    st.markdown("---")

    # Equity curve
    col_chart, col_signals = st.columns([3, 2])

    with col_chart:
        st.markdown('<div class="section-title">Curva de Patrimônio</div>', unsafe_allow_html=True)

        if not equity_df.empty and len(equity_df) > 1:
            fig = go.Figure()

            # Linha de equity
            fig.add_trace(go.Scatter(
                x=equity_df["date"],
                y=equity_df["equity"],
                mode="lines",
                name="QuantB3",
                line=dict(color="#3b82f6", width=2),
                fill="tozeroy",
                fillcolor="rgba(59, 130, 246, 0.08)",
            ))

            # Linha de capital inicial
            fig.add_hline(
                y=CAPITAL,
                line_dash="dash",
                line_color="#374151",
                annotation_text=f"Capital inicial: {format_currency(CAPITAL)}",
                annotation_font_color="#6b7280",
            )

            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter", color="#9ca3af", size=11),
                xaxis=dict(
                    gridcolor="#1e293b",
                    showgrid=True,
                    zeroline=False,
                ),
                yaxis=dict(
                    gridcolor="#1e293b",
                    showgrid=True,
                    zeroline=False,
                    tickprefix="R$ ",
                    tickformat=",.0f",
                ),
                legend=dict(
                    bgcolor="rgba(0,0,0,0)",
                    bordercolor="#1e293b",
                ),
                margin=dict(l=0, r=0, t=10, b=0),
                height=280,
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Aguardando dados de equity. O gráfico aparecerá após o primeiro ciclo operacional.")

    with col_signals:
        st.markdown('<div class="section-title">Último Sinal Gerado</div>', unsafe_allow_html=True)

        if signals:
            from src.db.repositories import get_latest_signal_date
            latest_date = get_latest_signal_date()
            if latest_date:
                st.caption(f"Data: {latest_date.strftime('%d/%m/%Y')}")

            top_signals = [s for s in signals if s.get("action") in ("BUY", "HOLD")][:8]

            for sig in top_signals:
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.markdown(f"**{sig['ticker']}**")
                with col_b:
                    st.markdown(render_action_badge(sig.get("action", "OUT")), unsafe_allow_html=True)
                with col_c:
                    score = sig.get("score", 0)
                    st.caption(f"{score:.3f}")
        else:
            st.info("Nenhum sinal disponível ainda.")


def page_portfolio():
    """Página de carteira atual."""
    st.markdown('<div class="sim-banner">⚠️  OPERAÇÃO SIMULADA — SEM CAPITAL REAL</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Carteira Atual</div>', unsafe_allow_html=True)

    positions = load_current_positions()

    if not positions:
        st.info("Nenhuma posição aberta no momento.")
        return

    # Carrega preços atuais
    tickers = [p["ticker"] for p in positions]
    current_prices = load_current_prices(tickers)

    # Monta DataFrame
    rows = []
    total_value = 0.0
    total_cost = 0.0

    for pos in positions:
        ticker = pos["ticker"]
        qty = pos["qty"]
        avg_price = pos.get("avg_price", 0)
        stop = pos.get("stop_price", 0) or 0
        take = pos.get("take_price", 0) or 0

        current = current_prices.get(ticker, avg_price)
        value = qty * current
        cost_basis = qty * avg_price
        pl = value - cost_basis
        pl_pct = (current / avg_price - 1) * 100 if avg_price > 0 else 0

        total_value += value
        total_cost += cost_basis

        rows.append({
            "Ticker": ticker,
            "Qtd": qty,
            "P. Médio": avg_price,
            "P. Atual": current,
            "Valor": value,
            "P&L (R$)": pl,
            "P&L (%)": pl_pct,
            "Stop": stop,
            "Take": take,
        })

    df = pd.DataFrame(rows)

    # Formata para exibição
    def color_pl(val):
        if isinstance(val, (int, float)):
            color = "#10b981" if val >= 0 else "#ef4444"
            return f"color: {color}"
        return ""

    styled = df.style.applymap(color_pl, subset=["P&L (R$)", "P&L (%)"]).format({
        "P. Médio": "R$ {:.2f}",
        "P. Atual": "R$ {:.2f}",
        "Valor": "R$ {:.2f}",
        "P&L (R$)": "R$ {:.2f}",
        "P&L (%)": "{:.2f}%",
        "Stop": "R$ {:.2f}",
        "Take": "R$ {:.2f}",
    })

    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Resumo
    total_pl = total_value - total_cost
    total_pl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

    col1, col2, col3 = st.columns(3)
    with col1:
        render_metric_card("Valor Total em Posições", format_currency(total_value))
    with col2:
        render_metric_card(
            "P&L Total",
            format_currency(total_pl),
            format_pct(total_pl_pct),
            total_pl >= 0,
        )
    with col3:
        render_metric_card("Número de Posições", str(len(positions)))

    # Gráfico de alocação
    if rows:
        st.markdown("---")
        st.markdown('<div class="section-title">Alocação por Ativo</div>', unsafe_allow_html=True)

        fig = px.pie(
            df,
            values="Valor",
            names="Ticker",
            color_discrete_sequence=px.colors.sequential.Blues_r,
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", color="#9ca3af"),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=0, r=0, t=10, b=0),
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)


def page_signals():
    """Página de sinais semanais."""
    st.markdown('<div class="sim-banner">⚠️  OPERAÇÃO SIMULADA — SEM CAPITAL REAL</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Sinais da Semana</div>', unsafe_allow_html=True)

    signals = load_latest_signals()

    if not signals:
        st.info("Nenhum sinal disponível. O sistema gera sinais toda segunda-feira após o fechamento.")
        return

    from src.db.repositories import get_latest_signal_date
    latest_date = get_latest_signal_date()
    if latest_date:
        st.caption(f"Gerado em: {latest_date.strftime('%d/%m/%Y')} | Execução: {_next_weekday(latest_date, 1).strftime('%d/%m/%Y')}")

    # Separa por ação
    buy_signals = [s for s in signals if s.get("action") == "BUY"]
    sell_signals = [s for s in signals if s.get("action") == "SELL"]
    hold_signals = [s for s in signals if s.get("action") == "HOLD"]
    out_signals = [s for s in signals if s.get("action") == "OUT"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Comprar", len(buy_signals), delta=None)
    with col2:
        st.metric("Vender", len(sell_signals), delta=None)
    with col3:
        st.metric("Manter", len(hold_signals), delta=None)
    with col4:
        st.metric("Fora", len(out_signals), delta=None)

    st.markdown("---")

    # Tabela completa
    rows = []
    for sig in sorted(signals, key=lambda x: x.get("rank") or 999):
        rows.append({
            "Rank": sig.get("rank", "-"),
            "Ticker": sig.get("ticker", ""),
            "Ação": sig.get("action", ""),
            "Score": sig.get("score", 0),
            "Qtd Alvo": sig.get("target_qty", 0),
            "Ref (R$)": sig.get("ref_price", 0),
            "Stop (R$)": sig.get("stop_price", 0),
            "Take (R$)": sig.get("take_price", 0),
        })

    df = pd.DataFrame(rows)

    def color_action(val):
        colors = {
            "BUY": "color: #10b981; font-weight: 600",
            "SELL": "color: #ef4444; font-weight: 600",
            "HOLD": "color: #60a5fa; font-weight: 600",
            "OUT": "color: #6b7280",
        }
        return colors.get(val, "")

    styled = df.style.applymap(color_action, subset=["Ação"]).format({
        "Score": "{:.4f}",
        "Ref (R$)": "R$ {:.2f}",
        "Stop (R$)": "R$ {:.2f}",
        "Take (R$)": "R$ {:.2f}",
    })

    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Gráfico de scores
    st.markdown("---")
    st.markdown('<div class="section-title">Scores LGBM (Top 20)</div>', unsafe_allow_html=True)

    top20 = sorted(signals, key=lambda x: -(x.get("score") or 0))[:20]
    if top20:
        df_scores = pd.DataFrame([
            {"Ticker": s["ticker"], "Score": s.get("score", 0), "Ação": s.get("action", "OUT")}
            for s in top20
        ])

        color_map = {"BUY": "#10b981", "SELL": "#ef4444", "HOLD": "#3b82f6", "OUT": "#374151"}
        df_scores["Cor"] = df_scores["Ação"].map(color_map).fillna("#374151")

        fig = go.Figure(go.Bar(
            x=df_scores["Ticker"],
            y=df_scores["Score"],
            marker_color=df_scores["Cor"],
            text=df_scores["Ação"],
            textposition="outside",
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", color="#9ca3af", size=11),
            xaxis=dict(gridcolor="#1e293b"),
            yaxis=dict(gridcolor="#1e293b", title="Score LGBM"),
            margin=dict(l=0, r=0, t=30, b=0),
            height=300,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)


def page_orders():
    """Página de histórico de ordens."""
    st.markdown('<div class="section-title">Histórico de Ordens</div>', unsafe_allow_html=True)

    orders = load_recent_orders(days=30)

    if not orders:
        st.info("Nenhuma ordem registrada nos últimos 30 dias.")
        return

    rows = []
    for o in orders:
        rows.append({
            "Data Exec.": o.get("exec_date", ""),
            "Ticker": o.get("ticker", ""),
            "Lado": o.get("side", ""),
            "Qtd": o.get("qty", 0),
            "Preço": o.get("price") or 0,
            "Custo": o.get("cost") or 0,
            "Status": o.get("status", ""),
        })

    df = pd.DataFrame(rows)

    def color_side(val):
        colors = {
            "BUY": "color: #10b981",
            "SELL": "color: #ef4444",
            "STOP": "color: #f59e0b",
            "TAKE": "color: #a78bfa",
            "PENDING": "color: #6b7280",
        }
        return colors.get(val, "")

    styled = df.style.applymap(color_side, subset=["Lado", "Status"]).format({
        "Preço": "R$ {:.2f}",
        "Custo": "R$ {:.4f}",
    })

    st.dataframe(styled, use_container_width=True, hide_index=True)


def page_equity():
    """Página de análise de equity e performance."""
    st.markdown('<div class="section-title">Análise de Performance</div>', unsafe_allow_html=True)

    equity_df = load_equity_curve()

    if equity_df.empty or len(equity_df) < 2:
        st.info("Dados insuficientes para análise. Aguarde pelo menos 2 pontos de equity.")
        return

    equity_df = equity_df.sort_values("date")
    equity_df["ret"] = equity_df["equity"].pct_change()
    equity_df["drawdown"] = equity_df["equity"] / equity_df["equity"].cummax() - 1

    # Métricas
    first = equity_df.iloc[0]["equity"]
    last = equity_df.iloc[-1]["equity"]
    total_ret = (last / first - 1) * 100

    days = (equity_df.iloc[-1]["date"] - equity_df.iloc[0]["date"]).days
    years = max(days / 365.25, 0.01)
    cagr = ((last / first) ** (1 / years) - 1) * 100

    ret_series = equity_df["ret"].dropna()
    vol = ret_series.std() * (252 ** 0.5) * 100
    sharpe = (ret_series.mean() * 252) / (ret_series.std() * (252 ** 0.5)) if ret_series.std() > 0 else 0
    max_dd = equity_df["drawdown"].min() * 100

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_metric_card("Retorno Total", format_pct(total_ret), delta=None, delta_positive=total_ret >= 0)
    with col2:
        render_metric_card("CAGR", format_pct(cagr))
    with col3:
        render_metric_card("Sharpe", f"{sharpe:.2f}")
    with col4:
        render_metric_card("Max Drawdown", format_pct(max_dd), delta_positive=False)

    st.markdown("---")

    # Gráfico de equity
    st.markdown('<div class="section-title">Curva de Patrimônio</div>', unsafe_allow_html=True)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity_df["date"],
        y=equity_df["equity"],
        mode="lines",
        name="Patrimônio",
        line=dict(color="#3b82f6", width=2),
        fill="tozeroy",
        fillcolor="rgba(59, 130, 246, 0.08)",
    ))
    fig.add_hline(y=CAPITAL, line_dash="dash", line_color="#374151")
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#9ca3af", size=11),
        xaxis=dict(gridcolor="#1e293b"),
        yaxis=dict(gridcolor="#1e293b", tickprefix="R$ ", tickformat=",.0f"),
        margin=dict(l=0, r=0, t=10, b=0),
        height=250,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Gráfico de drawdown
    st.markdown('<div class="section-title">Drawdown</div>', unsafe_allow_html=True)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=equity_df["date"],
        y=equity_df["drawdown"] * 100,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(239, 68, 68, 0.15)",
        line=dict(color="#ef4444", width=1.5),
        name="Drawdown",
    ))
    fig2.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#9ca3af", size=11),
        xaxis=dict(gridcolor="#1e293b"),
        yaxis=dict(gridcolor="#1e293b", ticksuffix="%"),
        margin=dict(l=0, r=0, t=10, b=0),
        height=200,
    )
    st.plotly_chart(fig2, use_container_width=True)


def page_runs():
    """Página de histórico de jobs."""
    st.markdown('<div class="section-title">Histórico de Execuções (Jobs)</div>', unsafe_allow_html=True)

    runs = load_recent_runs(limit=30)

    if not runs:
        st.info("Nenhuma execução registrada.")
        return

    rows = []
    for r in runs:
        started = r.get("started_at", "")
        finished = r.get("finished_at", "")
        duration = ""
        if started and finished:
            try:
                d = (pd.Timestamp(finished) - pd.Timestamp(started)).total_seconds()
                duration = f"{d:.0f}s"
            except Exception:
                pass

        rows.append({
            "Job": r.get("job", ""),
            "Início": started,
            "Fim": finished,
            "Duração": duration,
            "Status": r.get("status", ""),
            "Log": (r.get("log", "") or "")[:100],
        })

    df = pd.DataFrame(rows)

    def color_status(val):
        colors = {
            "success": "color: #10b981",
            "error": "color: #ef4444",
            "running": "color: #f59e0b",
        }
        return colors.get(val, "")

    styled = df.style.applymap(color_status, subset=["Status"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


# =============================================================================
# NAVEGAÇÃO E LAYOUT PRINCIPAL
# =============================================================================

def page_settings():
    """Gerencia destinatários de e-mail sem expor credenciais do provedor."""
    from src.db.repositories import get_email_recipients, set_email_recipient_active, upsert_email_recipient

    st.markdown('<div class="section-title">Notificações por e-mail</div>', unsafe_allow_html=True)
    st.caption("Os destinatários salvos aqui serão usados pelos jobs do GitHub Actions.")

    with st.form("add_email_recipient", clear_on_submit=True):
        email = st.text_input("E-mail do destinatário", placeholder="nome@empresa.com")
        label = st.text_input("Nome ou rótulo (opcional)", placeholder="Ex.: Operações")
        submitted = st.form_submit_button("Adicionar destinatário", use_container_width=True)
        if submitted:
            if not email or "@" not in email:
                st.error("Informe um endereço de e-mail válido.")
            else:
                try:
                    upsert_email_recipient(email, label)
                    st.success("Destinatário salvo.")
                except Exception as e:
                    st.error(f"Não foi possível salvar o destinatário: {e}")

    try:
        recipients = get_email_recipients()
    except Exception as e:
        st.error(f"Não foi possível carregar os destinatários: {e}")
        return

    if not recipients:
        st.info("Nenhum destinatário configurado.")
        return

    for recipient in recipients:
        cols = st.columns([4, 2, 1])
        cols[0].write(recipient["email"])
        cols[1].caption(recipient.get("label") or "Sem rótulo")
        is_active = bool(recipient["active"])
        action = "Desativar" if is_active else "Ativar"
        if cols[2].button(action, key=f"recipient_{recipient['id']}"):
            try:
                set_email_recipient_active(recipient["id"], not is_active)
                st.rerun()
            except Exception as e:
                st.error(f"Não foi possível atualizar o destinatário: {e}")


def _next_weekday(d: date, weekday: int) -> date:
    days_ahead = weekday - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return d + timedelta(days=days_ahead)


def main():
    """Ponto de entrada principal do dashboard."""

    # Verifica autenticação
    if not check_password():
        return

    # Sidebar
    with st.sidebar:
        st.markdown("""
        <div style='padding: 1rem 0;'>
            <div style='font-family: JetBrains Mono, monospace; font-size: 1.3rem;
                        font-weight: 600; color: #e2e8f0;'>
                QUANT<span style='color: #3b82f6;'>B3</span>
            </div>
            <div style='font-family: Inter, sans-serif; font-size: 0.7rem;
                        color: #4b5563; margin-top: 0.2rem; letter-spacing: 0.1em;
                        text-transform: uppercase;'>
                Cockpit Quantitativo v1.0
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        page = st.radio(
            "Navegação",
            options=["Resumo", "Carteira", "Sinais", "Ordens", "Performance", "Jobs", "Configurações"],
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Info do modelo
        st.markdown("""
        <div style='font-family: Inter, sans-serif; font-size: 0.72rem; color: #4b5563;'>
            <div style='color: #6b7280; font-weight: 600; margin-bottom: 0.5rem;
                        text-transform: uppercase; letter-spacing: 0.08em;'>
                Modelo Ativo
            </div>
            <div>LightGBM_Fwd10</div>
            <div>Sticky + LiqP10</div>
            <div style='margin-top: 0.5rem;'>Capital: R$ 2.000</div>
            <div>Posições: 8</div>
            <div>Stop: -5%</div>
            <div>Take: 1:2,5</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        # Botão de atualizar
        if st.button("Atualizar dados", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        # Logout
        if st.button("Sair", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # Conteúdo principal
    if page == "Resumo":
        st.title("Resumo Geral")
        page_home()
    elif page == "Carteira":
        st.title("Carteira Atual")
        page_portfolio()
    elif page == "Sinais":
        st.title("Sinais Semanais")
        page_signals()
    elif page == "Ordens":
        st.title("Histórico de Ordens")
        page_orders()
    elif page == "Performance":
        st.title("Análise de Performance")
        page_equity()
    elif page == "Jobs":
        st.title("Histórico de Jobs")
        page_runs()
    elif page == "Configurações":
        st.title("Configurações")
        page_settings()


if __name__ == "__main__":
    main()
