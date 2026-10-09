-- Auditoria do IBRX Model Watch e reforço point-in-time de market_events.
-- Executar após sql/012_market_events.sql.

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

ALTER TABLE market_events
    ADD COLUMN IF NOT EXISTS source_event_id text,
    ADD COLUMN IF NOT EXISTS known_at timestamptz,
    ADD COLUMN IF NOT EXISTS available_from date,
    ADD COLUMN IF NOT EXISTS feature_from date,
    ADD COLUMN IF NOT EXISTS feature_to date;

CREATE UNIQUE INDEX IF NOT EXISTS uq_market_events_source_event_id
    ON market_events (source_event_id)
    WHERE source_event_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_market_event_feature_dates'
    ) THEN
        ALTER TABLE market_events
            ADD CONSTRAINT chk_market_event_feature_dates CHECK (
                feature_to IS NULL OR feature_from IS NULL OR feature_to >= feature_from
            );
    END IF;
END $$;
