-- Buyers Table (buyers)

CREATE TABLE IF NOT EXISTS buyers (
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

CREATE TABLE IF NOT EXISTS buyer_offers (
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

CREATE TABLE IF NOT EXISTS buyer_service_areas (
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

CREATE TABLE IF NOT EXISTS offer_exclusivities (
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

