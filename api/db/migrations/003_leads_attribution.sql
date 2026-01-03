-- api/db/migrations/003_leads_attribution.sql
-- Adds attribution bindings to leads: source_id, offer_id, market_id, vertical_id.
-- Uses NOT VALID constraints to remain safe on existing data; new code must always set these fields.

BEGIN;

-- Add columns (nullable initially to avoid breaking existing rows).
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS source_id   BIGINT,
  ADD COLUMN IF NOT EXISTS offer_id    BIGINT,
  ADD COLUMN IF NOT EXISTS market_id   BIGINT,
  ADD COLUMN IF NOT EXISTS vertical_id BIGINT;

-- Foreign keys (NOT VALID to allow existing NULLs; validate after backfill if needed).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'leads_source_fk') THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_source_fk
      FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE RESTRICT NOT VALID;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'leads_offer_fk') THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_offer_fk
      FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE RESTRICT NOT VALID;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'leads_market_fk') THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_market_fk
      FOREIGN KEY (market_id) REFERENCES markets(id) ON DELETE RESTRICT NOT VALID;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'leads_vertical_fk') THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_vertical_fk
      FOREIGN KEY (vertical_id) REFERENCES verticals(id) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

-- Guard rail: enforce non-null attribution for NEW rows without breaking existing rows.
-- Implemented as NOT VALID CHECK; validate after any backfill/cleanup.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'leads_attribution_not_null') THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_attribution_not_null
      CHECK (
        source_id IS NOT NULL
        AND offer_id IS NOT NULL
        AND market_id IS NOT NULL
        AND vertical_id IS NOT NULL
      ) NOT VALID;
  END IF;
END $$;

-- Indexes to support routing/validation/analytics lookups.
CREATE INDEX IF NOT EXISTS idx_leads_offer_created_at     ON leads(offer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_market_created_at    ON leads(market_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_vertical_created_at  ON leads(vertical_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_source_created_at    ON leads(source_id, created_at DESC);

COMMIT;
