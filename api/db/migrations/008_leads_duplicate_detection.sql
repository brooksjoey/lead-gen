-- Database migration for idempotency constraint
ALTER TABLE leads 
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128),
    ADD COLUMN IF NOT EXISTS normalized_phone VARCHAR(32),
    ADD COLUMN IF NOT EXISTS normalized_email VARCHAR(320),
    ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS duplicate_of_lead_id INTEGER REFERENCES leads(id);

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

CREATE INDEX IF NOT EXISTS idx_leads_offer_norm_phone_created 
    ON leads(offer_id, normalized_phone, created_at DESC) 
    WHERE normalized_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_offer_norm_email_created 
    ON leads(offer_id, normalized_email, created_at DESC) 
    WHERE normalized_email IS NOT NULL;

