-- Leads Table (leads)

CREATE TABLE IF NOT EXISTS leads (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  -- Deterministic classification
  market_id       INTEGER NOT NULL REFERENCES markets(id) ON DELETE RESTRICT,
  vertical_id     INTEGER NOT NULL REFERENCES verticals(id) ON DELETE RESTRICT,
  offer_id        INTEGER NOT NULL REFERENCES offers(id) ON DELETE RESTRICT,
  source_id       INTEGER NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,

  -- Idempotency (prevents duplicates across retries/reposts)
  idempotency_key VARCHAR(128), -- provided by client/source or derived (e.g., hash)
  
  -- Core lead data (PII)
  source          VARCHAR(100) NOT NULL DEFAULT 'landing_page',
  name            VARCHAR(200) NOT NULL,
  email           VARCHAR(200) NOT NULL,
  phone           VARCHAR(20) NOT NULL,

  -- Location (generalized)
  country_code    CHAR(2) NOT NULL DEFAULT 'US',
  postal_code     VARCHAR(16) NOT NULL,  -- replaces zip
  city            VARCHAR(128),
  region_code     VARCHAR(20),           -- e.g., "US-TX"
  message         TEXT,

  -- State tracking
  status          lead_status NOT NULL DEFAULT 'received',
  validation_reason VARCHAR(500),

  -- Buyer relationship
  buyer_id        INTEGER REFERENCES buyers(id) ON DELETE SET NULL,
  delivered_at    TIMESTAMPTZ,
  accepted_at     TIMESTAMPTZ,
  rejected_at     TIMESTAMPTZ,
  rejection_reason VARCHAR(500),

  -- Billing lifecycle
  billing_status  billing_status NOT NULL DEFAULT 'pending',
  price           DECIMAL(10,2),
  billed_at       TIMESTAMPTZ,
  paid_at         TIMESTAMPTZ,

  -- Attribution tracking
  utm_source      VARCHAR(100),
  utm_medium      VARCHAR(100),
  utm_campaign     VARCHAR(100),
  ip_address      INET,
  user_agent      TEXT,

  -- Duplicate detection (normalized fields for matching)
  normalized_email VARCHAR(320),
  normalized_phone VARCHAR(32),
  duplicate_of_lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
  is_duplicate BOOLEAN NOT NULL DEFAULT false,

  CONSTRAINT leads_idempotency_unique_per_source
    UNIQUE (source_id, idempotency_key),
  CONSTRAINT leads_normalized_phone_len
    CHECK (normalized_phone IS NULL OR LENGTH(normalized_phone) BETWEEN 7 AND 32),
  CONSTRAINT leads_normalized_email_len
    CHECK (normalized_email IS NULL OR LENGTH(normalized_email) BETWEEN 3 AND 320)
);

