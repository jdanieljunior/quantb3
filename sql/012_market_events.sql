-- IBRX Model Watch: eventos validados usados exclusivamente como features.
CREATE TABLE IF NOT EXISTS market_events (
    id               bigserial PRIMARY KEY,
    ticker           text,
    event_type       text NOT NULL,
    event_class      text NOT NULL DEFAULT 'POINT',
    published_at     date NOT NULL,
    effective_date   date,
    valid_from       date,
    valid_to         date,
    source_name      text NOT NULL,
    source_url       text,
    source_reference text,
    summary          text,
    status           text NOT NULL DEFAULT 'PENDING_VALIDATION',
    confirmed        boolean NOT NULL DEFAULT false,
    confirmed_by     text,
    confirmed_at     timestamptz,
    confirmation_note text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_market_event_class CHECK (event_class IN ('POINT', 'REGIME')),
    CONSTRAINT chk_market_event_status CHECK (
        status IN ('PENDING_VALIDATION', 'REJECTED', 'CONFIRMED')
    ),
    CONSTRAINT chk_market_event_confirmation CHECK (
        (status = 'CONFIRMED' AND confirmed = true AND confirmed_at IS NOT NULL
         AND confirmed_by IS NOT NULL AND length(trim(confirmed_by)) > 0)
        OR (status <> 'CONFIRMED')
    ),
    CONSTRAINT chk_market_event_dates CHECK (
        valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from
    )
);

CREATE INDEX IF NOT EXISTS idx_market_events_status_published
    ON market_events (status, confirmed, published_at);
CREATE INDEX IF NOT EXISTS idx_market_events_ticker_dates
    ON market_events (ticker, published_at, valid_to);
