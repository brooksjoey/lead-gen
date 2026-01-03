-- api/db/migrations/002_reference_entities.sql
-- Reference entities for multi-market / multi-vertical / offer-driven attribution.
-- PostgreSQL 15+

BEGIN;

-- markets
CREATE TABLE IF NOT EXISTS markets (
  id            BIGSERIAL PRIMARY KEY,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMPTZ,
  name          VARCHAR(200) NOT NULL,           -- e.g., "Austin TX", "Tampa FL", "ZIP cluster X"
  timezone      VARCHAR(64)  NOT NULL,           -- IANA tz, e.g., "America/Chicago"
  is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'markets_name_unique') THEN
    ALTER TABLE markets ADD CONSTRAINT markets_name_unique UNIQUE (name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_markets_active_name ON markets(is_active, name);

-- verticals
CREATE TABLE IF NOT EXISTS verticals (
  id            BIGSERIAL PRIMARY KEY,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMPTZ,
  name          VARCHAR(200) NOT NULL,           -- e.g., "plumbing", "roof repair"
  slug          VARCHAR(128) NOT NULL,           -- stable identifier, e.g., "plumbing"
  is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'verticals_slug_unique') THEN
    ALTER TABLE verticals ADD CONSTRAINT verticals_slug_unique UNIQUE (slug);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_verticals_active_slug ON verticals(is_active, slug);

-- offers: optional abstraction, but treated as first-class to support per-offer pricing + policies + routing
CREATE TABLE IF NOT EXISTS offers (
  id                     BIGSERIAL PRIMARY KEY,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at             TIMESTAMPTZ,

  market_id              BIGINT NOT NULL REFERENCES markets(id) ON DELETE RESTRICT,
  vertical_id            BIGINT NOT NULL REFERENCES verticals(id) ON DELETE RESTRICT,

  name                   VARCHAR(200) NOT NULL,                 -- display name
  offer_key              VARCHAR(128) NOT NULL,                 -- stable identifier for ops/config

  default_price_per_lead_cents INTEGER NOT NULL CHECK (default_price_per_lead_cents >= 0),

  is_active              BOOLEAN NOT NULL DEFAULT TRUE
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'offers_offer_key_unique') THEN
    ALTER TABLE offers ADD CONSTRAINT offers_offer_key_unique UNIQUE (offer_key);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'offers_market_vertical_key_unique') THEN
    ALTER TABLE offers ADD CONSTRAINT offers_market_vertical_key_unique UNIQUE (market_id, vertical_id, offer_key);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_offers_market_vertical ON offers(market_id, vertical_id);
CREATE INDEX IF NOT EXISTS idx_offers_active_key ON offers(is_active, offer_key);

-- sources: deterministic attribution boundary (landing page / campaign / embed / partner api)
CREATE TABLE IF NOT EXISTS sources (
  id            BIGSERIAL PRIMARY KEY,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMPTZ,

  offer_id      BIGINT NOT NULL REFERENCES offers(id) ON DELETE RESTRICT,

  source_key    VARCHAR(128) NOT NULL,           -- stable identifier used by landing pages / integrations
  kind          VARCHAR(32)  NOT NULL,           -- "landing_page", "partner_api", "embed_form"
  name          VARCHAR(200) NOT NULL,

  hostname      VARCHAR(255),                    -- lower(host), no port
  path_prefix   VARCHAR(255),                    -- normalized prefix beginning with "/"
  api_key_hash  VARCHAR(255),                    -- store hash only

  is_active     BOOLEAN NOT NULL DEFAULT TRUE,

  CONSTRAINT sources_kind_valid CHECK (kind IN ('landing_page','partner_api','embed_form')),
  CONSTRAINT sources_path_prefix_format CHECK (path_prefix IS NULL OR path_prefix ~ '^/'),
  CONSTRAINT sources_http_mapping_requires_hostname CHECK (
    (path_prefix IS NULL AND hostname IS NULL) OR (hostname IS NOT NULL)
  )
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sources_source_key_unique') THEN
    ALTER TABLE sources ADD CONSTRAINT sources_source_key_unique UNIQUE (source_key);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_sources_offer_id ON sources(offer_id);
CREATE INDEX IF NOT EXISTS idx_sources_active_key ON sources(is_active, source_key);
CREATE INDEX IF NOT EXISTS idx_sources_active_hostname ON sources(is_active, hostname);
CREATE INDEX IF NOT EXISTS idx_sources_active_hostname_prefix ON sources(is_active, hostname, path_prefix);

COMMIT;
