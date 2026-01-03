-- Markets Table (markets)

CREATE TABLE markets (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  name            VARCHAR(200) NOT NULL,          -- e.g., "Austin, TX", "Tampa, FL"
  country_code    CHAR(2) NOT NULL DEFAULT 'US',  -- ISO 3166-1 alpha-2
  region_code     VARCHAR(20),                    -- e.g., "US-TX" (ISO 3166-2), optional
  timezone        VARCHAR(64) NOT NULL,           -- e.g., "America/Chicago"
  currency        CHAR(3) NOT NULL DEFAULT 'USD', -- ISO 4217

  is_active       BOOLEAN NOT NULL DEFAULT true
);

-- Verticals Table (verticals)

CREATE TABLE verticals (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  slug            VARCHAR(64) NOT NULL UNIQUE,    -- e.g., "plumbing", "roofing"
  name            VARCHAR(200) NOT NULL,          -- display name
  is_active       BOOLEAN NOT NULL DEFAULT true
);

-- Validation Policies Table (validation_policies)

CREATE TABLE validation_policies (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  name            VARCHAR(200) NOT NULL,
  version         INTEGER NOT NULL DEFAULT 1,

  -- Rules live here (examples: allowed_postal_codes, duplicate_window_hours, phone_region, etc.)
  rules           JSONB NOT NULL,

  is_active       BOOLEAN NOT NULL DEFAULT true,

  CONSTRAINT validation_policies_rules_is_object
    CHECK (jsonb_typeof(rules) = 'object')
);

-- Routing Policies Table (routing_policies)

CREATE TABLE routing_policies (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  name            VARCHAR(200) NOT NULL,
  version         INTEGER NOT NULL DEFAULT 1,

  -- Config: strategy, exclusivity behavior, fairness, caps, tie-breakers, etc.
  config          JSONB NOT NULL,

  is_active       BOOLEAN NOT NULL DEFAULT true,

  CONSTRAINT routing_policies_config_is_object
    CHECK (jsonb_typeof(config) = 'object')
);

-- Offers Table (offers)

CREATE TABLE offers (
  id                    SERIAL PRIMARY KEY,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            TIMESTAMPTZ,

  market_id             INTEGER NOT NULL REFERENCES markets(id) ON DELETE RESTRICT,
  vertical_id           INTEGER NOT NULL REFERENCES verticals(id) ON DELETE RESTRICT,

  name                  VARCHAR(200) NOT NULL,           -- e.g., "Service Name - Market"
  is_active             BOOLEAN NOT NULL DEFAULT true,

  default_price_per_lead DECIMAL(10,2) NOT NULL,
  invoice_threshold     DECIMAL(10,2) NOT NULL DEFAULT 500.00,

  validation_policy_id  INTEGER NOT NULL REFERENCES validation_policies(id) ON DELETE RESTRICT,
  routing_policy_id     INTEGER NOT NULL REFERENCES routing_policies(id) ON DELETE RESTRICT,

  CONSTRAINT offers_unique_market_vertical_name UNIQUE (market_id, vertical_id, name),
  CONSTRAINT offers_price_positive CHECK (default_price_per_lead > 0),
  CONSTRAINT offers_threshold_non_negative CHECK (invoice_threshold >= 0)
);

-- Sources Table (sources)

CREATE TABLE sources (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  offer_id         INTEGER NOT NULL REFERENCES offers(id) ON DELETE RESTRICT,

  -- Stable, human-manageable identifier used by landing pages / integrations
  source_key      VARCHAR(128) NOT NULL,

  kind            VARCHAR(32) NOT NULL,         -- "landing_page", "partner_api", "embed_form"
  name            VARCHAR(200) NOT NULL,        -- display label

  -- Deterministic HTTP mapping fields (optional; used when source_key not provided)
  hostname        VARCHAR(255),                -- exact match on lower(hostname)
  path_prefix     VARCHAR(255),                -- normalized prefix, must start with "/"

  -- Optional auth for programmatic ingestion (store hash, never plaintext)
  api_key_hash    VARCHAR(255),

  is_active       BOOLEAN NOT NULL DEFAULT true,

  CONSTRAINT sources_source_key_unique UNIQUE (source_key),
  CONSTRAINT sources_kind_valid CHECK (kind IN ('landing_page','partner_api','embed_form')),
  CONSTRAINT sources_path_prefix_format CHECK (path_prefix IS NULL OR path_prefix ~ '^/'),
  CONSTRAINT sources_http_mapping_requires_hostname CHECK (
    (path_prefix IS NULL AND hostname IS NULL) OR (hostname IS NOT NULL)
  )
);

-- Buyers Table (buyers)

CREATE TABLE buyers (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  -- Business information
  name            VARCHAR(200) NOT NULL,
  email           VARCHAR(200) NOT NULL UNIQUE,
  phone           VARCHAR(20) NOT NULL,
  company         VARCHAR(200),

  -- Delivery defaults (may be overridden per offer)
  webhook_url     VARCHAR(500),
  webhook_secret  VARCHAR(200),
  email_notifications BOOLEAN NOT NULL DEFAULT true,
  sms_notifications   BOOLEAN NOT NULL DEFAULT false,

  -- Buyer lifecycle
  is_active       BOOLEAN NOT NULL DEFAULT true,

  -- Billing
  balance         DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  credit_limit    DECIMAL(10,2),

  billing_cycle   VARCHAR(20) NOT NULL DEFAULT 'weekly',
  payment_method  VARCHAR(50),
  payment_method_id VARCHAR(200),

  CONSTRAINT check_non_negative_balance CHECK (balance >= 0)
);

-- Buyer Offer Enrollment Table (buyer_offers)

CREATE TABLE buyer_offers (
  id                  SERIAL PRIMARY KEY,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          TIMESTAMPTZ,

  buyer_id            INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,
  offer_id            INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,

  is_active           BOOLEAN NOT NULL DEFAULT true,

  routing_priority    INTEGER NOT NULL DEFAULT 1,
  capacity_per_day    INTEGER,                  -- NULL = unlimited
  capacity_per_hour   INTEGER,                  -- optional

  price_per_lead      DECIMAL(10,2),            -- NULL => offers.default_price_per_lead

  -- Optional per-offer delivery overrides
  webhook_url_override VARCHAR(500),
  email_override       VARCHAR(200),
  sms_override         VARCHAR(20),

  -- Optional buyer constraints for routing
  min_balance_required DECIMAL(10,2),           -- NULL = no minimum
  pause_until          TIMESTAMPTZ,

  CONSTRAINT buyer_offers_unique UNIQUE (buyer_id, offer_id),
  CONSTRAINT buyer_offers_priority_positive CHECK (routing_priority >= 1),
  CONSTRAINT buyer_offers_capacity_positive CHECK (capacity_per_day IS NULL OR capacity_per_day >= 0),
  CONSTRAINT buyer_offers_price_positive CHECK (price_per_lead IS NULL OR price_per_lead > 0)
);

-- Buyer Service Areas Table (buyer_service_areas)

CREATE TABLE buyer_service_areas (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  buyer_id        INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,
  market_id       INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,

  scope_type      VARCHAR(16) NOT NULL,     -- "postal_code", "city"
  scope_value     VARCHAR(64) NOT NULL,     -- e.g., "12345" or "City Name"

  is_active       BOOLEAN NOT NULL DEFAULT true,

  CONSTRAINT buyer_service_areas_scope_type_valid
    CHECK (scope_type IN ('postal_code','city')),
  CONSTRAINT buyer_service_areas_unique UNIQUE (buyer_id, market_id, scope_type, scope_value)
);

-- Offer Exclusivity Rules Table (offer_exclusivities)

CREATE TABLE offer_exclusivities (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  offer_id         INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
  scope_type       VARCHAR(16) NOT NULL,     -- "postal_code", "city"
  scope_value      VARCHAR(64) NOT NULL,

  buyer_id         INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,

  is_active        BOOLEAN NOT NULL DEFAULT true,

  CONSTRAINT offer_exclusivities_scope_type_valid
    CHECK (scope_type IN ('postal_code','city')),
  CONSTRAINT offer_exclusivities_unique UNIQUE (offer_id, scope_type, scope_value)
);

-- Leads Table (leads)

CREATE TABLE leads (
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

-- Invoices Table (invoices)

CREATE TABLE invoices (
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

CREATE TABLE audit_logs (
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

