"""
QuantB3 — Configurações Centrais
=================================
Parâmetros oficiais alinhados ao Memorial LightGBM v2.1
NUNCA alterar sem atualizar o memorial correspondente.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CAPITAL E CARTEIRA
# =============================================================================
CAPITAL = 2000.0
N_POSITIONS = 8

# =============================================================================
# MODELO LGBM (Memorial v2.1 — CONGELADO)
# =============================================================================
FORWARD_DAYS = 10
TRAIN_MIN_DAYS = 378
LIQ_PERCENTILE = 0.10
STICKY_BUFFER = 4

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
# GESTÃO DE RISCO (Memorial v2.1 — CONGELADO)
# =============================================================================
STOP_PCT = -0.05
TAKE_RR = 2.5

# =============================================================================
# EXECUÇÃO SIMULADA (Memorial v2.1 — CONGELADO)
# =============================================================================
SLIPPAGE_ENTRY = 0.0005
SLIPPAGE_STOP = 0.0010
SLIPPAGE_TAKE = 0.0005
COST_PCT = 0.0003  # emolumentos B3

# =============================================================================
# CALENDÁRIO OPERACIONAL
# =============================================================================
REBALANCE_WEEKDAY = 0   # segunda-feira
EXECUTION_WEEKDAY = 1   # terça-feira
RECONCILE_WEEKDAY = 2   # quarta-feira

# =============================================================================
# BENCHMARKS E UNIVERSO
# =============================================================================
BENCHMARKS = ["BOVA11.SA", "SMAL11.SA", "^BVSP"]
BOVA_TICKER = "BOVA11.SA"
MIN_OBS_PCT = 0.70  # mínimo de 70% de observações para incluir ticker

# =============================================================================
# BANCO DE DADOS (Supabase)
# =============================================================================
DATABASE_URL = os.getenv("DATABASE_URL", "")

# =============================================================================
# NOTIFICAÇÕES
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "brevo")
EMAIL_API_KEY = os.getenv("EMAIL_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.mail.yahoo.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
EMAIL_SMTP_PASSWORD = os.getenv("EMAIL_SMTP_PASSWORD", "")

# =============================================================================
# AUTENTICAÇÃO DO DASHBOARD
# =============================================================================
DASHBOARD_PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH", "")

# =============================================================================
# AMBIENTE
# =============================================================================
ENV = os.getenv("ENV", "development")
IS_PRODUCTION = ENV == "production"

# =============================================================================
# DADOS
# =============================================================================
CSV_PATH = os.getenv("CSV_PATH", "cotacoes_ibrx_ohlcv_completo.csv")
YFINANCE_RETRY_ATTEMPTS = 3
YFINANCE_RETRY_DELAY = 5  # segundos
YFINANCE_TIMEOUT = 15  # segundos por requisição; evita travar o job em ativos indisponíveis
YFINANCE_BATCH_SIZE = 10
YFINANCE_BATCH_TIMEOUT = 30  # limite absoluto por lote no runner Linux

# Ativos que o Yahoo Finance retornou como indisponíveis na coleta de 2026-08-10.
# Mantenha-os fora das consultas até que a fonte volte a fornecer cotações.
YFINANCE_TICKER_BLACKLIST = frozenset({
    "AZUL4.SA", "BRFS3.SA", "CCRO3.SA", "CIEL3.SA", "CPLE6.SA",
    "CRFB3.SA", "ELET3.SA", "ELET6.SA", "EMBR3.SA", "GOLL4.SA",
    "JBSS3.SA",
})

# =============================================================================
# SIMULAÇÃO
# =============================================================================
MONTE_CARLO_SEEDS = list(range(50))  # 50 seeds para Monte Carlo
SIMULATION_LABEL = "OPERAÇÃO SIMULADA — SEM CAPITAL REAL"
