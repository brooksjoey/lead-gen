-- Invoices Table (invoices)

CREATE TABLE IF NOT EXISTS invoices (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  buyer_id        INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,
  offer_id        INTEGER NOT NULL REFERENCES offers(id) ON DELETE RESTRICT,

  period_start    TIMESTAMPTZ NOT NULL,
  period_end      TIMESTAMPTZ NOT NULL,
  due_date        TIMESTAMPTZ NOT NULL,

  invoice_number  VARCHAR(50) NOT NULL UNIQUE,
  status          invoice_status NOT NULL DEFAULT 'draft',

  total_leads     INTEGER NOT NULL DEFAULT 0,
  amount_due      DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  tax_amount      DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  total_amount    DECIMAL(10,2) NOT NULL DEFAULT 0.00,

  payment_method  payment_method,
  paid_at         TIMESTAMPTZ,
  transaction_id  VARCHAR(200),

  disputed_at     TIMESTAMPTZ,
  dispute_reason  TEXT,
  resolved_at     TIMESTAMPTZ,
  resolution_notes TEXT,

  CONSTRAINT check_valid_period CHECK (period_start < period_end),
  CONSTRAINT check_non_negative_leads CHECK (total_leads >= 0),
  CONSTRAINT check_non_negative_amount CHECK (amount_due >= 0)
);

-- Optional Audit Table (lead_duplicate_events)

CREATE TABLE IF NOT EXISTS lead_duplicate_events (
  id                BIGSERIAL PRIMARY KEY,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  lead_id           INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  matched_lead_id   INTEGER NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,

  offer_id          INTEGER NOT NULL REFERENCES offers(id) ON DELETE RESTRICT,
  source_id         INTEGER NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,

  match_keys        TEXT[] NOT NULL,
  window_hours      INTEGER NOT NULL,
  match_mode        VARCHAR(8) NOT NULL,
  include_sources   VARCHAR(16) NOT NULL,

  action            VARCHAR(8) NOT NULL,
  reason_code       VARCHAR(64) NOT NULL
);

-- Audit Logs Table

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50) NOT NULL,
    resource_id INTEGER,
    before_state JSONB,
    after_state JSONB,
    ip_address INET,
    user_agent TEXT
);

