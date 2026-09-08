-- Diário operacional do dashboard QuantB3
-- Pode ser executado de forma segura mais de uma vez no SQL Editor do Supabase.

CREATE TABLE IF NOT EXISTS journal_entries (
    id          bigserial PRIMARY KEY,
    entry_date  date NOT NULL DEFAULT current_date,
    ticker      text,
    category    text NOT NULL DEFAULT 'Decisão',
    note        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_journal_entries_date
    ON journal_entries (entry_date DESC, created_at DESC);

ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;
