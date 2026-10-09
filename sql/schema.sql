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

-- Destinatários de e-mail configurados pelo dashboard
CREATE TABLE IF NOT EXISTS email_recipients (
    id          bigserial PRIMARY KEY,
    email       text NOT NULL UNIQUE,
    label       text,
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
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
CREATE INDEX IF NOT EXISTS idx_email_recipients_active ON email_recipients (active);

-- Diário operacional registrado pelo dashboard
CREATE TABLE IF NOT EXISTS journal_entries (
    id          bigserial PRIMARY KEY,
    entry_date  date NOT NULL DEFAULT current_date,
    ticker      text,
    category    text NOT NULL DEFAULT 'Decisão',
    note        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_journal_entries_date ON journal_entries (entry_date DESC, created_at DESC);
ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;

-- IBRX Model Watch: eventos validados usados exclusivamente como features.
CREATE TABLE IF NOT EXISTS market_events (
    id                bigserial PRIMARY KEY,
    ticker            text,
    event_type        text NOT NULL,
    event_class       text NOT NULL DEFAULT 'POINT',
    published_at      date NOT NULL,
    effective_date    date,
    valid_from        date,
    valid_to          date,
    source_name       text NOT NULL,
    source_url        text,
    source_reference  text,
    summary           text,
    status            text NOT NULL DEFAULT 'PENDING_VALIDATION',
    confirmed         boolean NOT NULL DEFAULT false,
    confirmed_by      text,
    confirmed_at      timestamptz,
    confirmation_note text,
    source_event_id   text UNIQUE,
    known_at          timestamptz,
    available_from    date,
    feature_from      date,
    feature_to        date,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_market_event_class CHECK (event_class IN ('POINT', 'REGIME')),
    CONSTRAINT chk_market_event_status CHECK (
        status IN ('PENDING_VALIDATION', 'REJECTED', 'CONFIRMED')
    ),
    CONSTRAINT chk_market_event_confirmation CHECK (
        (status = 'CONFIRMED' AND confirmed = true AND confirmed_at IS NOT NULL
         AND confirmed_by IS NOT NULL AND length(trim(confirmed_by)) > 0)
        OR status <> 'CONFIRMED'
    ),
    CONSTRAINT chk_market_event_dates CHECK (
        valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from
    ),
    CONSTRAINT chk_market_event_feature_dates CHECK (
        feature_to IS NULL OR feature_from IS NULL OR feature_to >= feature_from
    )
);
CREATE INDEX IF NOT EXISTS idx_market_events_status_published
    ON market_events (status, confirmed, published_at);
CREATE INDEX IF NOT EXISTS idx_market_events_ticker_dates
    ON market_events (ticker, published_at, valid_to);

-- Fonte bruta do IBRX Model Watch: nunca é lida pelo modelo diretamente.
CREATE TABLE IF NOT EXISTS market_event_staging (
    source_event_id          text PRIMARY KEY,
    event_type               text NOT NULL,
    ticker                   text,
    alert_date               date,
    official_disclosure_date date,
    effective_from           date,
    effective_to             date,
    validation_status        text NOT NULL,
    oos_enabled              boolean NOT NULL DEFAULT false,
    source_confirmed         boolean NOT NULL DEFAULT false,
    official_source_url      text,
    secondary_source_url     text,
    source_message_id        text,
    event_stage              text,
    validated_as_of          date,
    notes                    text,
    raw_payload              jsonb NOT NULL,
    imported_at              timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_event_staging_validation
    ON market_event_staging (validation_status, oos_enabled, source_confirmed);
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
