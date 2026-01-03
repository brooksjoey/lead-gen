-- Markets Table (markets)

CREATE TABLE IF NOT EXISTS markets (
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

CREATE TABLE IF NOT EXISTS verticals (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  slug            VARCHAR(64) NOT NULL UNIQUE,    -- e.g., "plumbing", "roofing"
  name            VARCHAR(200) NOT NULL,          -- display name
  is_active       BOOLEAN NOT NULL DEFAULT true
);

-- Validation Policies Table (validation_policies)

CREATE TABLE IF NOT EXISTS validation_policies (
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

CREATE TABLE IF NOT EXISTS routing_policies (
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

CREATE TABLE IF NOT EXISTS offers (
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

CREATE TABLE IF NOT EXISTS sources (
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

