-- api/db/migrations/004_leads_idempotency.sql
-- PostgreSQL 15+
-- Adds idempotency_key to leads and enforces uniqueness per source.

BEGIN;

ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'leads_idempotency_unique_per_source'
  ) THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_idempotency_unique_per_source
      UNIQUE (source_id, idempotency_key);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_leads_source_idempotency
  ON leads(source_id, idempotency_key);

COMMIT;

