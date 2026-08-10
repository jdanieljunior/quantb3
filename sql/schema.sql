-- QuantB3 — Schema PostgreSQL (Supabase)
-- Versão: 1.0
-- Executar no SQL Editor do Supabase

-- Preços diários OHLCV
CREATE TABLE IF NOT EXISTS prices (
    date        date NOT NULL,
    ticker      text NOT NULL,
    o           double precision,
    h           double precision,
    l           double precision,
    c           double precision,
    v           double precision,
    PRIMARY KEY (date, ticker)
);

-- Sinais gerados (segunda-feira)
CREATE TABLE IF NOT EXISTS signals (
    signal_date date NOT NULL,
    ticker      text NOT NULL,
    score       double precision,
    rank        int,
    action      text,              -- BUY / SELL / HOLD / OUT
    target_qty  int,
    ref_price   double precision,
    stop_price  double precision,
    take_price  double precision,
    created_at  timestamptz DEFAULT now(),
    PRIMARY KEY (signal_date, ticker)
);

-- Ordens (planejadas e/ou executadas)
CREATE TABLE IF NOT EXISTS orders (
    id          bigserial PRIMARY KEY,
    signal_date date,
    exec_date   date,
    ticker      text NOT NULL,
    side        text NOT NULL,     -- BUY / SELL / STOP / TAKE
    qty         int NOT NULL,
    price       double precision,
    cost        double precision,
    status      text NOT NULL,     -- PENDING / FILLED / CANCELLED
    note_id     text,
    created_at  timestamptz DEFAULT now()
);

-- Posição oficial simulada
CREATE TABLE IF NOT EXISTS positions (
    as_of       date NOT NULL,
    ticker      text NOT NULL,
    qty         int NOT NULL,
    avg_price   double precision NOT NULL,
    stop_price  double precision,
    take_price  double precision,
    updated_at  timestamptz DEFAULT now(),
    PRIMARY KEY (as_of, ticker)
);

-- Snapshot de carteira / equity
CREATE TABLE IF NOT EXISTS equity (
    date        date PRIMARY KEY,
    equity      double precision NOT NULL,
    cash        double precision NOT NULL,
    pos_value   double precision NOT NULL,
    n_positions int
);

-- Notificações enviadas
CREATE TABLE IF NOT EXISTS notifications (
    id          bigserial PRIMARY KEY,
    channel     text NOT NULL,     -- email / telegram
    kind        text NOT NULL,     -- signal_report / trade_notes / reconcile
    payload     text,
    status      text,              -- sent / failed
    sent_at     timestamptz DEFAULT now()
);

-- Log de jobs
CREATE TABLE IF NOT EXISTS runs (
    id          bigserial PRIMARY KEY,
    job         text NOT NULL,     -- monday / tuesday / wednesday / daily_prices
    started_at  timestamptz,
    finished_at timestamptz,
    status      text,              -- success / error
    log         text
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices (ticker, date DESC);
CREATE INDEX IF NOT EXISTS idx_orders_exec_date ON orders (exec_date);
CREATE INDEX IF NOT EXISTS idx_orders_signal_date ON orders (signal_date);
CREATE INDEX IF NOT EXISTS idx_signals_signal_date ON signals (signal_date);
CREATE INDEX IF NOT EXISTS idx_positions_as_of ON positions (as_of DESC);
CREATE INDEX IF NOT EXISTS idx_runs_job ON runs (job, started_at DESC);
