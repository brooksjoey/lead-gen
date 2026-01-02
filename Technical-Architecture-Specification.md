# LeadGen System: Complete Technical Architecture Specification

## System Overview

LeadGen v1.0 is a deterministic, event-driven lead distribution platform implementing a B2B2C marketplace model for configurable local service verticals and markets. The system operates on a pay-per-lead model with automated validation, routing, billing, and delivery pipelines.

**Seamless Transition Goal**: adding a new niche and/or geography is accomplished by inserting configuration and reference data (market/vertical/offer/source/rules), without code changes.

## Core Technical Stack

### Infrastructure Layer

- **Container Orchestration**: Docker Compose v3.8

- **Reverse Proxy**: Nginx 1.24-alpine with TLS termination

- **Database**: PostgreSQL 15-alpine (with asyncpg driver)

- **Caching/Queue**: Redis 7-alpine (RQ-ready)

- **Application Server**: Uvicorn ASGI server (Python 3.9+)

### Application Layer

- **Web Framework**: FastAPI 0.104+ (with Pydantic v2)

- **ORM**: SQLAlchemy 2.0+ with async support

- **Background Tasks**: asyncio (with aiohttp for async HTTP)

- **Logging**: structlog (JSON formatting)

- **Validation**: Pydantic plus custom business logic

### Data Layer

- **Database Schema**: Normalized relational model

- **Indexing Strategy**: Composite indexes based on query patterns

- **Data Retention**: Configurable TTL policies

- **Backup Strategy**: WAL archiving plus periodic database dumps

## System Architecture Components

### Network Architecture

```
Client → [Nginx:80/443] → [FastAPI:8000] ↔ [PostgreSQL:5432]
                              ↓
                      [Worker] → [External APIs]
                              ↓
                     [Redis:6379] (future queue)
```

**Key Port Bindings:**

- **80/443**: Nginx HTTP/HTTPS (SSL termination)

- **8000**: FastAPI application (internal)

- **5432**: PostgreSQL (exposed for management)

- **6379**: Redis cache/queue

## Database Schema Specification

### Lead Status and Billing Status Enums

```sql
CREATE TYPE lead_status AS ENUM (
  'received', 'validated', 'delivered', 'accepted', 'rejected'
);

CREATE TYPE billing_status AS ENUM (
  'pending', 'billed', 'paid', 'disputed', 'refunded'
);
```

### Invoice Status and Payment Method Enums

```sql
CREATE TYPE invoice_status AS ENUM (
  'draft', 'sent', 'paid', 'overdue', 'cancelled', 'disputed'
);

CREATE TYPE payment_method AS ENUM (
  'stripe', 'manual', 'bank_transfer', 'check'
);
```

### Markets Table (markets)

```sql
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
```

### Verticals Table (verticals)

```sql
CREATE TABLE verticals (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  slug            VARCHAR(64) NOT NULL UNIQUE,    -- e.g., "plumbing", "roofing"
  name            VARCHAR(200) NOT NULL,          -- display name
  is_active       BOOLEAN NOT NULL DEFAULT true
);
```

### Validation Policies Table (validation_policies)

Stores market/vertical specific validation rules as configuration, not code.

```sql
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
```

### Routing Policies Table (routing_policies)

```sql
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
```

### Offers Table (offers)

Canonical unit of sale: a vertical in a market, with attached validation + routing policies.

```sql
CREATE TABLE offers (
  id                    SERIAL PRIMARY KEY,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            TIMESTAMPTZ,

  market_id             INTEGER NOT NULL REFERENCES markets(id) ON DELETE RESTRICT,
  vertical_id           INTEGER NOT NULL REFERENCES verticals(id) ON DELETE RESTRICT,

  name                  VARCHAR(200) NOT NULL,           -- e.g., "Emergency Plumbing - Austin"
  is_active             BOOLEAN NOT NULL DEFAULT true,

  default_price_per_lead DECIMAL(10,2) NOT NULL,
  invoice_threshold     DECIMAL(10,2) NOT NULL DEFAULT 500.00,

  validation_policy_id  INTEGER NOT NULL REFERENCES validation_policies(id) ON DELETE RESTRICT,
  routing_policy_id     INTEGER NOT NULL REFERENCES routing_policies(id) ON DELETE RESTRICT,

  CONSTRAINT offers_unique_market_vertical_name UNIQUE (market_id, vertical_id, name),
  CONSTRAINT offers_price_positive CHECK (default_price_per_lead > 0),
  CONSTRAINT offers_threshold_non_negative CHECK (invoice_threshold >= 0)
);
```

### Sources Table (sources)

Represents where a lead originated (landing page, API partner, form embed), mapped to an offer.

```sql
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
```

### Buyers Table (buyers)

Remove CSV service area fields and global "exclusive"; scope is per-offer/service-area.

```sql
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
```

### Buyer Offer Enrollment Table (buyer_offers)

Defines buyer participation and pricing/capacity per offer.

```sql
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
```

### Buyer Service Areas Table (buyer_service_areas)

Normalizes service coverage. Eliminates CSV fields and enables multi-market seamless expansion.

```sql
CREATE TABLE buyer_service_areas (
  id              SERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMPTZ,

  buyer_id        INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,
  market_id       INTEGER NOT NULL REFERENCES markets(id) ON DELETE CASCADE,

  scope_type      VARCHAR(16) NOT NULL,     -- "postal_code", "city"
  scope_value     VARCHAR(64) NOT NULL,     -- e.g., "78701" or "Austin"

  is_active       BOOLEAN NOT NULL DEFAULT true,

  CONSTRAINT buyer_service_areas_scope_type_valid
    CHECK (scope_type IN ('postal_code','city')),
  CONSTRAINT buyer_service_areas_unique UNIQUE (buyer_id, market_id, scope_type, scope_value)
);
```

### Offer Exclusivity Rules Table (offer_exclusivities)

Enforces exclusive buyer per offer+service-area (postal_code or city).

```sql
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
```

### Leads Table (leads)

Add market/vertical/offer/source binding + idempotency to make "transition" deterministic.

```sql
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
```

### Invoices Table (invoices)

Attach invoices to offer for clean multi-market accounting and reporting.

```sql
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
```

### Index Strategy for Performance

```sql
-- Leads: multi-tenant read patterns (offer/market/vertical + time series)
CREATE INDEX idx_leads_offer_created_at ON leads(offer_id, created_at DESC);
CREATE INDEX idx_leads_market_created_at ON leads(market_id, created_at DESC);
CREATE INDEX idx_leads_vertical_created_at ON leads(vertical_id, created_at DESC);
CREATE INDEX idx_leads_source_created_at ON leads(source_id, created_at DESC);

CREATE INDEX idx_leads_email ON leads(email);
CREATE INDEX idx_leads_phone ON leads(phone);
CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_leads_billing_status ON leads(billing_status);
CREATE INDEX idx_leads_buyer_created_at ON leads(buyer_id, created_at DESC);

-- Duplicate detection (typical: by offer + phone/email + time window)
CREATE INDEX idx_leads_offer_phone_created ON leads(offer_id, phone, created_at DESC);
CREATE INDEX idx_leads_offer_email_created ON leads(offer_id, email, created_at DESC);

-- Duplicate detection (normalized fields for fast lookups)
CREATE INDEX IF NOT EXISTS idx_leads_offer_norm_phone_created
  ON leads(offer_id, normalized_phone, created_at DESC)
  WHERE normalized_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_offer_norm_email_created
  ON leads(offer_id, normalized_email, created_at DESC)
  WHERE normalized_email IS NOT NULL;

-- Optional: for same_source_only duplicate detection
CREATE INDEX IF NOT EXISTS idx_leads_offer_source_norm_phone_created
  ON leads(offer_id, source_id, normalized_phone, created_at DESC)
  WHERE normalized_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_offer_source_norm_email_created
  ON leads(offer_id, source_id, normalized_email, created_at DESC)
  WHERE normalized_email IS NOT NULL;

-- Idempotency lookup (scoped by source)
CREATE INDEX idx_leads_source_idempotency ON leads(source_id, idempotency_key);

-- Buyer lookup by offer and priority
CREATE INDEX idx_buyer_offers_offer_active_priority
  ON buyer_offers(offer_id, is_active, routing_priority DESC);

-- Buyer service area resolution
CREATE INDEX idx_buyer_service_areas_market_scope
  ON buyer_service_areas(market_id, scope_type, scope_value)
  WHERE is_active = true;

-- Exclusivity lookup
CREATE INDEX idx_offer_exclusivities_offer_scope
  ON offer_exclusivities(offer_id, scope_type, scope_value)
  WHERE is_active = true;

-- Sources: classification resolution
CREATE INDEX idx_sources_offer_id ON sources(offer_id);
CREATE INDEX idx_sources_active_key ON sources(is_active, source_key);

-- HTTP mapping lookup (exact hostname; then longest-prefix match)
CREATE INDEX idx_sources_active_hostname ON sources(is_active, hostname);
CREATE INDEX idx_sources_active_hostname_prefix ON sources(is_active, hostname, path_prefix);

-- Invoices: by buyer + offer + period
CREATE INDEX idx_invoices_buyer_offer_period
  ON invoices(buyer_id, offer_id, period_start, period_end);

CREATE INDEX idx_invoices_status_due
  ON invoices(status, due_date);

CREATE INDEX idx_invoices_paid_at
  ON invoices(paid_at) WHERE paid_at IS NOT NULL;
```

## Lead Ingestion Classification Contract

### Purpose

Deterministically resolve every inbound lead to exactly one `sources.id` and therefore exactly one `offers.id` (and its `market_id` and `vertical_id`) with no hardcoded market/niche logic.

### Guarantees

- **Deterministic**: identical request inputs resolve to the same `sources.id`.
- **Unambiguous**: resolution either yields exactly one source or fails with a classified error.
- **Stable**: changing routing/validation does not change source resolution.
- **Config-driven**: adding markets/verticals/offers/sources requires only DB inserts/updates.

### Resolution Inputs

**Accepted Identification Inputs (in priority order):**

1. `source_id` (header or body): direct numeric ID (admin/internal only)
2. `source_key` (body): stable string identifier
3. **HTTP mapping**: request Host + request Path using `sources.hostname` + `sources.path_prefix`

### Canonicalization Rules

- **source_key**: `strip()`; must match `[A-Za-z0-9][A-Za-z0-9._:-]{1,127}` (2–128 chars)
- **hostname**: lower-case; strip port; if missing Host header → fail
- **path**: must start with `/`; if empty → `/`

### Deterministic Resolution Algorithm (Normative)

#### Priority 1: source_id (Direct)

If `source_id` is provided:

- SELECT source by id AND `is_active = true`
- If not found → 400 `invalid_source`
- If found → accept and bind `offer_id`

#### Priority 2: source_key (Stable External ID)

If `source_key` is provided:

- SELECT source by `source_key` AND `is_active = true`
- If not found → 400 `invalid_source_key`
- If found → accept and bind `offer_id`

#### Priority 3: HTTP Mapping (Host + Longest Path Prefix)

If neither `source_id` nor `source_key` is provided:

1. Resolve `hostname = lower(strip_port(request.host))`
2. Resolve `path = request.url.path` (normalized)
3. Query all active sources with matching hostname and (NULL prefix OR prefix match)
4. Choose single best match:
   - Prefer the row with the longest `path_prefix` satisfying `path LIKE path_prefix || '%'`
   - If multiple rows tie for longest prefix → 409 `ambiguous_source_mapping`
   - If none found → 400 `unmapped_source`

### Invariants

- A resolved `sources.id` implies exactly one `offers.id` via `sources.offer_id`.
- `offers.id` implies `market_id` and `vertical_id` as the system-of-record for classification.
- Lead insertion MUST store `source_id`, `offer_id`, `market_id`, `vertical_id` exactly as resolved.

### Reference SQL (Normative)

**Resolve by source_key:**

```sql
SELECT
  s.id            AS source_id,
  s.offer_id      AS offer_id,
  o.market_id     AS market_id,
  o.vertical_id   AS vertical_id
FROM sources s
JOIN offers o ON o.id = s.offer_id
WHERE s.is_active = true
  AND s.source_key = :source_key
LIMIT 1;
```

**Resolve by hostname + longest path_prefix:**

```sql
WITH candidates AS (
  SELECT
    s.id            AS source_id,
    s.offer_id      AS offer_id,
    o.market_id     AS market_id,
    o.vertical_id   AS vertical_id,
    s.path_prefix   AS path_prefix,
    LENGTH(COALESCE(s.path_prefix, '')) AS prefix_len
  FROM sources s
  JOIN offers o ON o.id = s.offer_id
  WHERE s.is_active = true
    AND s.hostname = :hostname
    AND (
      s.path_prefix IS NULL
      OR :path LIKE s.path_prefix || '%'
    )
),
ranked AS (
  SELECT *
  FROM candidates
  ORDER BY prefix_len DESC, source_id ASC
)
SELECT *
FROM ranked
LIMIT 2;
```

**Interpretation rule:**

- 0 rows → unmapped
- 1 row → resolved
- 2 rows where `prefix_len` equal → ambiguous (fail)
- 2 rows where `prefix_len` differs → take first (longest prefix)

### Reference Implementation (Async SQLAlchemy 2.x)

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request


_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")


class SourceResolutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResolvedClassification:
    source_id: int
    offer_id: int
    market_id: int
    vertical_id: int


def _strip_port(host: str) -> str:
    host = host.strip()
    if not host:
        return host
    # IPv6 in brackets: [::1]:8000
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            return host[: end + 1].lower()
        return host.lower()
    # hostname:port
    if ":" in host:
        return host.split(":", 1)[0].lower()
    return host.lower()


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    return path


def _validate_source_key(source_key: str) -> str:
    source_key = source_key.strip()
    if not _SOURCE_KEY_RE.match(source_key):
        raise SourceResolutionError(
            code="invalid_source_key_format",
            message="source_key must match /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/",
        )
    return source_key


def derive_idempotency_key(
    *,
    source_id: int,
    email: str,
    phone: str,
    postal_code: str,
    message: Optional[str],
) -> str:
    # Deterministic fallback when client does not provide idempotency_key.
    # Scoped by source_id so distinct sources do not collide.
    parts = [
        str(source_id),
        email.strip().lower(),
        re.sub(r"\s+", "", phone.strip()),
        postal_code.strip().upper(),
        (message or "").strip(),
    ]
    raw = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def resolve_classification(
    *,
    session: AsyncSession,
    request: Request,
    source_id: Optional[int],
    source_key: Optional[str],
) -> ResolvedClassification:
    # Priority 1: direct source_id (internal/admin)
    if source_id is not None:
        row = await session.execute(
            text(
                """
                SELECT
                  s.id        AS source_id,
                  s.offer_id  AS offer_id,
                  o.market_id AS market_id,
                  o.vertical_id AS vertical_id
                FROM sources s
                JOIN offers o ON o.id = s.offer_id
                WHERE s.is_active = true
                  AND s.id = :source_id
                LIMIT 1
                """
            ),
            {"source_id": int(source_id)},
        )
        rec = row.mappings().first()
        if not rec:
            raise SourceResolutionError("invalid_source", "source_id not found or inactive")
        return ResolvedClassification(
            source_id=int(rec["source_id"]),
            offer_id=int(rec["offer_id"]),
            market_id=int(rec["market_id"]),
            vertical_id=int(rec["vertical_id"]),
        )

    # Priority 2: source_key (stable external)
    if source_key:
        sk = _validate_source_key(source_key)
        row = await session.execute(
            text(
                """
                SELECT
                  s.id        AS source_id,
                  s.offer_id  AS offer_id,
                  o.market_id AS market_id,
                  o.vertical_id AS vertical_id
                FROM sources s
                JOIN offers o ON o.id = s.offer_id
                WHERE s.is_active = true
                  AND s.source_key = :source_key
                LIMIT 1
                """
            ),
            {"source_key": sk},
        )
        rec = row.mappings().first()
        if not rec:
            raise SourceResolutionError("invalid_source_key", "source_key not found or inactive")
        return ResolvedClassification(
            source_id=int(rec["source_id"]),
            offer_id=int(rec["offer_id"]),
            market_id=int(rec["market_id"]),
            vertical_id=int(rec["vertical_id"]),
        )

    # Priority 3: HTTP mapping (Host + longest prefix)
    host = request.headers.get("host", "").strip()
    hostname = _strip_port(host)
    if not hostname:
        raise SourceResolutionError("missing_host_header", "Host header is required for source mapping")

    path = _normalize_path(request.url.path)

    row = await session.execute(
        text(
            """
            WITH candidates AS (
              SELECT
                s.id            AS source_id,
                s.offer_id      AS offer_id,
                o.market_id     AS market_id,
                o.vertical_id   AS vertical_id,
                s.path_prefix   AS path_prefix,
                LENGTH(COALESCE(s.path_prefix, '')) AS prefix_len
              FROM sources s
              JOIN offers o ON o.id = s.offer_id
              WHERE s.is_active = true
                AND s.hostname = :hostname
                AND (
                  s.path_prefix IS NULL
                  OR :path LIKE s.path_prefix || '%'
                )
            ),
            ranked AS (
              SELECT *
              FROM candidates
              ORDER BY prefix_len DESC, source_id ASC
            )
            SELECT *
            FROM ranked
            LIMIT 2
            """
        ),
        {"hostname": hostname, "path": path},
    )
    recs = list(row.mappings().all())

    if not recs:
        raise SourceResolutionError("unmapped_source", "No active source matched hostname/path")

    if len(recs) == 1:
        rec = recs[0]
        return ResolvedClassification(
            source_id=int(rec["source_id"]),
            offer_id=int(rec["offer_id"]),
            market_id=int(rec["market_id"]),
            vertical_id=int(rec["vertical_id"]),
        )

    # Two candidates returned: verify ambiguity rules.
    first, second = recs[0], recs[1]
    if int(first["prefix_len"]) == int(second["prefix_len"]):
        raise SourceResolutionError(
            "ambiguous_source_mapping",
            "Multiple sources matched with equal specificity (path_prefix length)",
        )

    return ResolvedClassification(
        source_id=int(first["source_id"]),
        offer_id=int(first["offer_id"]),
        market_id=int(first["market_id"]),
        vertical_id=int(first["vertical_id"]),
    )
```

### Operational Rules (Non-Negotiable for Seamless Transition)

Every new landing page/integration must be provisioned with:

- `sources.source_key` (recommended) and/or `hostname` + `path_prefix`
- `sources.offer_id` pointing to the intended `offers.id`

Any time two sources share the same hostname, `path_prefix` MUST be unique and non-overlapping by length tie to avoid ambiguity.

If you rely on HTTP mapping, use distinct path prefixes per offer (e.g., `/lp/plumbing/`, `/lp/roofing/`) and avoid shared roots like `/`.

## Lead Ingestion Idempotency Contract

### Purpose

Guarantee that retries, duplicate posts, client timeouts, and webhook resubmits do not create duplicate lead rows, do not double-route, and do not double-bill—while remaining compatible with multi-market/multi-vertical "seamless transition".

### Scope

Idempotency is enforced at the Lead Ingestion boundary (POST /api/leads) and is scoped to the resolved source.

### Deterministic Rules (Normative)

#### R1. Idempotency Key Acceptance

**If `idempotency_key` is provided by the client:**

- It MUST be accepted if it matches the format rules below.
- It MUST be used verbatim after canonicalization.
- It MUST be stored on the lead row.
- All replays with the same `(source_id, idempotency_key)` MUST return the same lead result.

**If `idempotency_key` is not provided:**

- The server MUST derive one deterministically using a canonical function that:
  - Is stable across restarts and deployments
  - Is scoped by resolved `source_id`
  - Uses fields that materially represent "same lead"
- The derived key MUST be stored and treated identically to a client-provided key.

#### R2. Canonicalization + Validation

- **Allowed chars**: `[A-Za-z0-9._:-]`
- **Length**: 16–128 characters after canonicalization
- **Canonicalization**: `strip()` only (do not lowercase or mutate beyond trimming)
- **If invalid**: 400 `invalid_idempotency_key_format`

#### R3. Uniqueness and Concurrency

Idempotency MUST be enforced in Postgres with a unique constraint:

```sql
UNIQUE (source_id, idempotency_key)
```

Insertion MUST be concurrency-safe using:

```sql
INSERT ... ON CONFLICT (source_id, idempotency_key) DO UPDATE ... RETURNING id
```

Or `DO NOTHING` followed by a SELECT, but must be race-safe.

#### R4. Response Stability

All requests resolving to the same `(source_id, idempotency_key)` MUST:

- Return the same `lead_id`
- Return the same classification fields (`source_id`, `offer_id`, `market_id`, `vertical_id`)
- Preferably return the current processing status (`received`/`validated`/`delivered`/...) and `buyer`/`price` if already assigned.

#### R5. Idempotency vs Duplicate Detection

- **Idempotency** prevents accidental duplicates caused by retries.
- **Duplicate detection** prevents "same person submitting again" within a window.
- They are separate:
  - **Idempotency key collision** = same request replay
  - **Duplicate detection** = business rule (may reject or accept depending on policy)

### Database Requirements (Normative)

#### Leads Table Constraint (UPDATED)

```sql
-- MUST exist for correctness; unique scoped by source
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'leads_idempotency_unique_per_source'
  ) THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_idempotency_unique_per_source
      UNIQUE (source_id, idempotency_key);
  END IF;
END $$;
```

#### Index for Lookups (RECOMMENDED)

```sql
CREATE INDEX IF NOT EXISTS idx_leads_source_idempotency
  ON leads(source_id, idempotency_key);
```

### Reference Implementation (Async SQLAlchemy 2.x + Postgres)

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class IdempotencyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonicalize_idempotency_key(key: str) -> str:
    k = key.strip()
    if not _IDEMPOTENCY_RE.match(k):
        raise IdempotencyError(
            code="invalid_idempotency_key_format",
            message="idempotency_key must match /^[A-Za-z0-9._:-]{16,128}$/ after trimming",
        )
    return k


def _norm_email(email: str) -> str:
    return email.strip().lower()


def _norm_phone(phone: str) -> str:
    # Minimal normalization: remove whitespace; do not strip symbols aggressively here unless
    # your upstream already canonicalizes to E.164.
    return re.sub(r"\s+", "", phone.strip())


def _norm_postal(postal_code: str) -> str:
    return postal_code.strip().upper()


def derive_idempotency_key(
    *,
    source_id: int,
    name: str,
    email: str,
    phone: str,
    country_code: str,
    postal_code: str,
    message: Optional[str],
) -> str:
    """
    Deterministic server-side idempotency key derivation.

    Properties:
    - scoped by source_id
    - stable across restarts
    - uses fields that define "same submission"
    - SHA-256 hex => 64 chars (always valid)
    """
    if not email or not phone or not postal_code:
        raise IdempotencyError(
            code="idempotency_derivation_failed",
            message="email, phone, and postal_code are required to derive idempotency_key",
        )

    parts = [
        f"source_id={source_id}",
        f"name={name.strip()}",
        f"email={_norm_email(email)}",
        f"phone={_norm_phone(phone)}",
        f"country={country_code.strip().upper()}",
        f"postal={_norm_postal(postal_code)}",
        f"message={(message or '').strip()}",
    ]
    payload = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()  # 64 chars, hex


@dataclass(frozen=True)
class LeadInsertResult:
    lead_id: int
    created_new: bool


async def upsert_lead_stub_idempotent(
    *,
    session: AsyncSession,
    # classification (already resolved)
    source_id: int,
    offer_id: int,
    market_id: int,
    vertical_id: int,
    # lead payload
    source: str,
    name: str,
    email: str,
    phone: str,
    country_code: str,
    postal_code: str,
    city: Optional[str],
    region_code: Optional[str],
    message: Optional[str],
    utm_source: Optional[str],
    utm_medium: Optional[str],
    utm_campaign: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
    # idempotency
    idempotency_key: Optional[str],
    now: Optional[datetime] = None,
) -> LeadInsertResult:
    """
    Creates (or reuses) a lead row deterministically keyed by (source_id, idempotency_key).

    This function ONLY establishes the immutable identity row and classification binding.
    Subsequent phases (validation/routing/billing) MUST operate on lead_id and be idempotent
    in their own right (status transitions guarded by WHERE clauses / expected state).
    """
    if now is None:
        # Use DB time for authoritative timestamps; this is only used if you want to store updated_at.
        pass

    if idempotency_key:
        key = canonicalize_idempotency_key(idempotency_key)
    else:
        key = derive_idempotency_key(
            source_id=source_id,
            name=name,
            email=email,
            phone=phone,
            country_code=country_code,
            postal_code=postal_code,
            message=message,
        )

    # Concurrency-safe upsert: return the existing lead id if it already exists.
    # DO UPDATE is a no-op update that allows RETURNING always.
    row = await session.execute(
        text(
            """
            INSERT INTO leads (
              created_at,
              updated_at,
              market_id,
              vertical_id,
              offer_id,
              source_id,
              idempotency_key,
              source,
              name,
              email,
              phone,
              country_code,
              postal_code,
              city,
              region_code,
              message,
              utm_source,
              utm_medium,
              utm_campaign,
              ip_address,
              user_agent
            )
            VALUES (
              CURRENT_TIMESTAMP,
              CURRENT_TIMESTAMP,
              :market_id,
              :vertical_id,
              :offer_id,
              :source_id,
              :idempotency_key,
              :source,
              :name,
              :email,
              :phone,
              :country_code,
              :postal_code,
              :city,
              :region_code,
              :message,
              :utm_source,
              :utm_medium,
              :utm_campaign,
              :ip_address,
              :user_agent
            )
            ON CONFLICT (source_id, idempotency_key)
            DO UPDATE SET
              updated_at = CURRENT_TIMESTAMP
            RETURNING
              id AS lead_id,
              (xmax = 0) AS created_new
            """
        ),
        {
            "market_id": market_id,
            "vertical_id": vertical_id,
            "offer_id": offer_id,
            "source_id": source_id,
            "idempotency_key": key,
            "source": source,
            "name": name,
            "email": email,
            "phone": phone,
            "country_code": country_code.strip().upper(),
            "postal_code": postal_code,
            "city": city,
            "region_code": region_code,
            "message": message,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": utm_campaign,
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
    )
    rec = row.mappings().first()
    if not rec:
        # Should never happen; indicates a DB-level issue.
        raise IdempotencyError("idempotency_insert_failed", "Failed to insert or fetch lead row")

    return LeadInsertResult(
        lead_id=int(rec["lead_id"]),
        created_new=bool(rec["created_new"]),
    )
```

### Mandatory Downstream Idempotency (Phase Guards) (Normative)

To prevent double-routing and double-billing when reprocessing the same lead:

- **Validation transition** must be guarded: `UPDATE leads SET status='validated' WHERE id=:id AND status='received'`
- **Delivery transition** must be guarded: `UPDATE leads SET status='delivered', buyer_id=:b WHERE id=:id AND status='validated'`
- **Billing transition** must be guarded (you already have this pattern): `WHERE billing_status='pending'`

These guards ensure that even if your worker picks up the same lead twice, outcomes remain single-commit.

## Duplicate Detection Contract

### Purpose

Prevent low-quality "repeat submissions" from being treated as new leads while preserving correct behavior for:

- multi-market / multi-vertical offers
- source-scoped idempotency
- configurable per-offer windows and rules
- concurrency-safe ingestion

### Definitions

- **Idempotency:** same request replay → same `(source_id, idempotency_key)` → same lead row.
- **Duplicate detection:** different request (new idempotency key) but materially the same lead within a configured window → policy-driven outcome (reject, flag, accept).

### Scope

Duplicate detection is executed during ingestion **after** classification + idempotent lead row creation, and before validation/routing transitions.

### Normative Policy Inputs (from validation_policies.rules)

`validation_policies.rules` MUST support the following keys:

```json
{
  "duplicate_detection": {
    "enabled": true,
    "window_hours": 24,
    "scope": "offer",                   
    "keys": ["phone", "email"],         
    "match_mode": "any",                
    "exclude_statuses": ["rejected"],    
    "include_sources": "any",            
    "action": "reject",                 
    "reason_code": "duplicate_recent",
    "min_fields": ["phone"],            
    "normalize": {
      "email": "lower_trim",
      "phone": "e164_or_digits",
      "postal_code": "upper_trim"
    }
  }
}
```

#### Semantics

- `enabled`: if false/missing → duplicate detection is skipped.
- `window_hours`: lookback window for duplicate checks.
- `scope`: `"offer"` (required). Duplicate detection must be scoped at least to `offer_id`.
- `keys`: subset of `["phone","email"]` (required).
- `match_mode`:
  - `"any"`: duplicate if any key matches within window
  - `"all"`: duplicate if all configured keys match within window (requires presence of all keys)
- `exclude_statuses`: prior leads with these statuses are ignored in duplicate detection.
- `include_sources`:
  - `"any"`: match across all sources within the offer
  - `"same_source_only"`: match only within the same `source_id`
- `action`:
  - `"reject"`: set lead status to `rejected` with reason and stop pipeline
  - `"flag"`: continue pipeline but set a flag + record duplicate reference
  - `"accept"`: record duplicate reference but do not change behavior
- `min_fields`: minimum fields required to run check; if not present → skip check.
- `normalize`: canonicalization strategy for email/phone.

### Required Schema Additions (Normative)

#### Leads: Add normalized columns + duplicate reference

```sql
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS normalized_email VARCHAR(320),
  ADD COLUMN IF NOT EXISTS normalized_phone VARCHAR(32),
  ADD COLUMN IF NOT EXISTS duplicate_of_lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS is_duplicate BOOLEAN NOT NULL DEFAULT false;

-- Enforce basic length constraints via CHECKs (optional, recommended)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'leads_normalized_phone_len') THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_normalized_phone_len
      CHECK (normalized_phone IS NULL OR LENGTH(normalized_phone) BETWEEN 7 AND 32);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'leads_normalized_email_len') THEN
    ALTER TABLE leads
      ADD CONSTRAINT leads_normalized_email_len
      CHECK (normalized_email IS NULL OR LENGTH(normalized_email) BETWEEN 3 AND 320);
  END IF;
END $$;
```

#### Optional: Separate duplicate events table (audit-grade)

```sql
CREATE TABLE IF NOT EXISTS lead_duplicate_events (
  id                BIGSERIAL PRIMARY KEY,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

  lead_id           INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  matched_lead_id   INTEGER NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,

  offer_id          INTEGER NOT NULL REFERENCES offers(id) ON DELETE RESTRICT,
  source_id         INTEGER NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,

  match_keys        TEXT[] NOT NULL,          -- e.g., {"phone"} or {"email","phone"}
  window_hours      INTEGER NOT NULL,
  match_mode        VARCHAR(8) NOT NULL,      -- "any" | "all"
  include_sources   VARCHAR(16) NOT NULL,     -- "any" | "same_source_only"

  action            VARCHAR(8) NOT NULL,      -- "reject" | "flag" | "accept"
  reason_code       VARCHAR(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lde_lead_id ON lead_duplicate_events(lead_id);
CREATE INDEX IF NOT EXISTS idx_lde_offer_created_at ON lead_duplicate_events(offer_id, created_at DESC);
```

### Index Design (Normative)

Duplicate lookup must be fast under high write volume. Use partial indexes by offer and recent time, keyed by normalized fields.

```sql
-- Lookup by offer + normalized_phone within time window
CREATE INDEX IF NOT EXISTS idx_leads_offer_norm_phone_created
  ON leads(offer_id, normalized_phone, created_at DESC)
  WHERE normalized_phone IS NOT NULL;

-- Lookup by offer + normalized_email within time window
CREATE INDEX IF NOT EXISTS idx_leads_offer_norm_email_created
  ON leads(offer_id, normalized_email, created_at DESC)
  WHERE normalized_email IS NOT NULL;

-- If include_sources="same_source_only" is used commonly:
CREATE INDEX IF NOT EXISTS idx_leads_offer_source_norm_phone_created
  ON leads(offer_id, source_id, normalized_phone, created_at DESC)
  WHERE normalized_phone IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_leads_offer_source_norm_email_created
  ON leads(offer_id, source_id, normalized_email, created_at DESC)
  WHERE normalized_email IS NOT NULL;
```

### Normalization Strategy (Normative)

#### Email normalization

- `lower_trim`: `strip()`, lowercase.
- Reject empty after trim → NULL.

#### Phone normalization

Two supported modes:

- `e164_or_digits`:
  - If already E.164 (`+` followed by digits, length 8–16), keep.
  - Else strip all non-digits.
  - If result length < 7 → NULL.

No country inference is performed in duplicate detection. If you want country-aware parsing, do it earlier and store canonical E.164 in `phone`.

### Duplicate Detection Algorithm (Normative)

#### Required Inputs

- resolved classification: `offer_id`, `source_id`
- persisted lead row: `lead_id`, `created_at`
- policy: `validation_policies.rules.duplicate_detection`

#### Output

One of:

- `not_duplicate`
- `duplicate_reject(matched_lead_id)`
- `duplicate_flag(matched_lead_id)`
- `duplicate_accept(matched_lead_id)`

#### Matching Rules

- Window: consider prior leads where `created_at >= now() - window_hours`.
- Exclusions: ignore prior leads whose status is in `exclude_statuses`.
- Scope: always `offer_id = :offer_id`.
- Sources:
  - `any`: ignore `source_id`
  - `same_source_only`: require `source_id = :source_id`
- Match keys:
  - `any`: if either phone or email matches
  - `all`: both must match (and both must be present)

### Reference Implementation (Async SQLAlchemy 2.x)

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Literal, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


MatchMode = Literal["any", "all"]
IncludeSources = Literal["any", "same_source_only"]
DuplicateAction = Literal["reject", "flag", "accept"]


class DuplicateDetectionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DuplicatePolicy:
    enabled: bool
    window_hours: int
    scope: Literal["offer"]
    keys: Sequence[Literal["phone", "email"]]
    match_mode: MatchMode
    exclude_statuses: Sequence[str]
    include_sources: IncludeSources
    action: DuplicateAction
    reason_code: str
    min_fields: Sequence[Literal["phone", "email"]]
    normalize_email: Literal["lower_trim"]
    normalize_phone: Literal["e164_or_digits"]


@dataclass(frozen=True)
class DuplicateResult:
    is_duplicate: bool
    action: Optional[DuplicateAction]
    matched_lead_id: Optional[int]
    matched_keys: Sequence[str]


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164_RE = re.compile(r"^\+[1-9]\d{7,15}$")


def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    e = email.strip().lower()
    if not e:
        return None
    # Syntax is validated elsewhere; here we only ensure it is plausible.
    if not _EMAIL_RE.match(e):
        return None
    return e


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    p = phone.strip()
    if not p:
        return None
    if _E164_RE.match(p):
        return p
    digits = re.sub(r"\D+", "", p)
    if len(digits) < 7:
        return None
    return digits


def _require_min_fields(
    *,
    policy: DuplicatePolicy,
    normalized_phone: Optional[str],
    normalized_email: Optional[str],
) -> bool:
    for f in policy.min_fields:
        if f == "phone" and not normalized_phone:
            return False
        if f == "email" and not normalized_email:
            return False
    return True


async def detect_duplicate(
    *,
    session: AsyncSession,
    lead_id: int,
    offer_id: int,
    source_id: int,
    policy: DuplicatePolicy,
    phone: Optional[str],
    email: Optional[str],
) -> DuplicateResult:
    if not policy.enabled:
        return DuplicateResult(False, None, None, ())

    if policy.scope != "offer":
        raise DuplicateDetectionError("invalid_policy_scope", "duplicate detection scope must be 'offer'")

    norm_phone = normalize_phone(phone) if "phone" in policy.keys else None
    norm_email = normalize_email(email) if "email" in policy.keys else None

    if not _require_min_fields(policy=policy, normalized_phone=norm_phone, normalized_email=norm_email):
        return DuplicateResult(False, None, None, ())

    if not norm_phone and not norm_email:
        return DuplicateResult(False, None, None, ())

    window_hours = int(policy.window_hours)
    if window_hours <= 0 or window_hours > 24 * 365:
        raise DuplicateDetectionError("invalid_window_hours", "window_hours must be within (0, 8760]")

    include_sources = policy.include_sources
    match_mode = policy.match_mode

    # Candidate selection SQL: fetch the best match (most recent) and which keys matched.
    # We ignore the current lead_id and only look back within the window.
    sql = """
    WITH candidates AS (
      SELECT
        l.id AS matched_lead_id,
        l.created_at AS matched_created_at,
        (CASE WHEN :norm_phone IS NOT NULL AND l.normalized_phone = :norm_phone THEN 1 ELSE 0 END) AS phone_match,
        (CASE WHEN :norm_email IS NOT NULL AND l.normalized_email = :norm_email THEN 1 ELSE 0 END) AS email_match
      FROM leads l
      WHERE l.offer_id = :offer_id
        AND l.id <> :lead_id
        AND l.created_at >= (CURRENT_TIMESTAMP - (:window_hours::int * INTERVAL '1 hour'))
        AND (l.status <> ALL(:exclude_statuses))
        AND (:include_sources_any OR l.source_id = :source_id)
        AND (
          (:norm_phone IS NOT NULL AND l.normalized_phone = :norm_phone)
          OR
          (:norm_email IS NOT NULL AND l.normalized_email = :norm_email)
        )
    ),
    filtered AS (
      SELECT *
      FROM candidates
      WHERE
        CASE
          WHEN :match_mode = 'any' THEN (phone_match = 1 OR email_match = 1)
          WHEN :match_mode = 'all' THEN
            (
              (:norm_phone IS NULL OR phone_match = 1)
              AND
              (:norm_email IS NULL OR email_match = 1)
              AND
              -- for 'all' ensure both keys requested are present and match
              (CASE
                 WHEN (:norm_phone IS NOT NULL AND :norm_email IS NOT NULL) THEN (phone_match = 1 AND email_match = 1)
                 ELSE true
               END)
            )
          ELSE false
        END
    )
    SELECT
      matched_lead_id,
      phone_match,
      email_match
    FROM filtered
    ORDER BY matched_created_at DESC, matched_lead_id DESC
    LIMIT 1
    """

    res = await session.execute(
        text(sql),
        {
            "offer_id": offer_id,
            "source_id": source_id,
            "lead_id": lead_id,
            "window_hours": window_hours,
            "exclude_statuses": list(policy.exclude_statuses) if policy.exclude_statuses else [],
            "include_sources_any": include_sources == "any",
            "match_mode": match_mode,
            "norm_phone": norm_phone,
            "norm_email": norm_email,
        },
    )
    rec = res.mappings().first()
    if not rec:
        # Persist normalized values even if not a duplicate
        await _persist_normalized_fields(
            session=session,
            lead_id=lead_id,
            normalized_phone=norm_phone,
            normalized_email=norm_email,
        )
        return DuplicateResult(False, None, None, ())

    matched_lead_id = int(rec["matched_lead_id"])
    matched_keys = []
    if int(rec["phone_match"]) == 1:
        matched_keys.append("phone")
    if int(rec["email_match"]) == 1:
        matched_keys.append("email")

    # Persist normalized values + duplicate flags deterministically.
    await _mark_duplicate(
        session=session,
        lead_id=lead_id,
        normalized_phone=norm_phone,
        normalized_email=norm_email,
        matched_lead_id=matched_lead_id,
        action=policy.action,
        reason_code=policy.reason_code,
    )

    return DuplicateResult(True, policy.action, matched_lead_id, tuple(matched_keys))


async def _persist_normalized_fields(
    *,
    session: AsyncSession,
    lead_id: int,
    normalized_phone: Optional[str],
    normalized_email: Optional[str],
) -> None:
    await session.execute(
        text(
            """
            UPDATE leads
            SET
              updated_at = CURRENT_TIMESTAMP,
              normalized_phone = COALESCE(:normalized_phone, normalized_phone),
              normalized_email = COALESCE(:normalized_email, normalized_email)
            WHERE id = :lead_id
            """
        ),
        {
            "lead_id": lead_id,
            "normalized_phone": normalized_phone,
            "normalized_email": normalized_email,
        },
    )


async def _mark_duplicate(
    *,
    session: AsyncSession,
    lead_id: int,
    normalized_phone: Optional[str],
    normalized_email: Optional[str],
    matched_lead_id: int,
    action: DuplicateAction,
    reason_code: str,
) -> None:
    # Action semantics:
    # - reject: transition to rejected if still received (do not clobber later states)
    # - flag/accept: mark is_duplicate but do not change status
    if action == "reject":
        await session.execute(
            text(
                """
                UPDATE leads
                SET
                  updated_at = CURRENT_TIMESTAMP,
                  normalized_phone = COALESCE(:normalized_phone, normalized_phone),
                  normalized_email = COALESCE(:normalized_email, normalized_email),
                  is_duplicate = true,
                  duplicate_of_lead_id = :matched_lead_id,
                  status = CASE WHEN status = 'received' THEN 'rejected' ELSE status END,
                  validation_reason = CASE WHEN status = 'received' THEN :reason_code ELSE validation_reason END
                WHERE id = :lead_id
                """
            ),
            {
                "lead_id": lead_id,
                "normalized_phone": normalized_phone,
                "normalized_email": normalized_email,
                "matched_lead_id": matched_lead_id,
                "reason_code": reason_code,
            },
        )
    else:
        await session.execute(
            text(
                """
                UPDATE leads
                SET
                  updated_at = CURRENT_TIMESTAMP,
                  normalized_phone = COALESCE(:normalized_phone, normalized_phone),
                  normalized_email = COALESCE(:normalized_email, normalized_email),
                  is_duplicate = true,
                  duplicate_of_lead_id = :matched_lead_id
                WHERE id = :lead_id
                """
            ),
            {
                "lead_id": lead_id,
                "normalized_phone": normalized_phone,
                "normalized_email": normalized_email,
                "matched_lead_id": matched_lead_id,
            },
        )
```

### Required Ingestion Integration Point (Normative)

After `resolve_classification()` and `upsert_lead_stub_idempotent()`:

1. Load offer's `validation_policy.rules`
2. Parse `duplicate_detection` section into `DuplicatePolicy`
3. Call `detect_duplicate(...)`
4. If result is `reject`:
   - return `202` or `400` based on your API semantics (recommend `202` with status `rejected` to keep clients simple)
   - do not proceed to validation/routing/billing
5. Otherwise proceed

### Query/Index Justification (Normative)

- `(offer_id, normalized_phone|normalized_email, created_at DESC)` supports tight lookbacks per offer.
- Optional `(offer_id, source_id, ...)` indexes prevent scanning when `include_sources="same_source_only"` is common.
- Using normalized columns avoids repeated expensive normalization during query time and makes matching consistent across all sources and markets.

## API Specification

### REST Endpoints

#### POST /api/leads – Lead Ingestion

Classification requirement: every lead must resolve to an offer (either explicit identifiers or resolvable source mapping).

**Idempotency**: All requests are idempotent. If `idempotency_key` is provided, it must be 16-128 characters matching `[A-Za-z0-9._:-]`. If not provided, the server derives one deterministically from lead data scoped by `source_id`. Replays with the same `(source_id, idempotency_key)` return the same `lead_id` and current processing status.

**Request Body (recommended):**

```json
{
  "source": "landing_page",
  "source_key": "austin-plumbing-v1", 
  "idempotency_key": "c1a9d3b2d6c84c2b9b6f9adf4b4e1c1f",

  "name": "John Smith",
  "email": "john@example.com",
  "phone": "+15125550123",
  "country_code": "US",
  "postal_code": "78701",
  "message": "Emergency plumbing needed",

  "utm_source": "google",
  "utm_medium": "cpc",
  "utm_campaign": "plumbing_austin",

  "consent": true,
  "gdpr_consent": true
}
```

**Response (202 Accepted) - First Request:**

```json
{
  "lead_id": 12345,
  "status": "accepted",
  "buyer_id": 7,
  "source_id": 31,
  "offer_id": 12,
  "market_id": 4,
  "vertical_id": 2,
  "price": 45.00
}
```

**Response (202 Accepted) - Replay (Same idempotency_key):**

```json
{
  "lead_id": 12345,
  "status": "delivered",
  "buyer_id": 7,
  "source_id": 31,
  "offer_id": 12,
  "market_id": 4,
  "vertical_id": 2,
  "price": 45.00
}
```

**Response (400 Bad Request) - Invalid idempotency_key format:**

```json
{
  "detail": {
    "code": "invalid_idempotency_key_format",
    "message": "idempotency_key must match /^[A-Za-z0-9._:-]{16,128}$/ after trimming"
  }
}
```

**Response (400 Bad Request) - Validation failure:**

```json
{
  "detail": {
    "lead_id": 12345,
    "reason": "Invalid postal_code for offer",
    "message": "Lead did not pass validation"
  }
}
```

#### GET /health – System Health Check

**Response:**

```json
{
  "status": "healthy",
  "service": "leadgen_api",
  "environment": "production",
  "version": "1.0.0",
  "database": "connected",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Webhook Delivery Specification

**Endpoint**: Buyer's configured webhook_url

**Method**: POST

**Content-Type**: application/json

**Headers:**

- **X-Webhook-Signature**: HMAC-SHA256(payload, webhook_secret)

- **X-LeadGen-Delivery-Id**: {uuid}

- **X-LeadGen-Event**: lead.delivered

- **User-Agent**: LeadGen/1.0

**Payload:**

```json
{
  "event": "lead.delivered",
  "data": {
    "lead_id": 12345,
    "received_at": "2024-01-15T10:30:00Z",
    "delivered_at": "2024-01-15T10:30:05Z",
    "contact": {
      "name": "John Smith",
      "phone": "+15125550123",
      "email": "john@example.com",
      "zip": "78701"
    },
    "details": {
      "message": "Emergency plumbing needed",
      "source": "landing_page"
    },
    "metadata": {
      "price": 45.00,
      "buyer_id": 7
    }
  }
}
```

## Business Logic Flows

### Lead Processing Pipeline

#### Ingestion Phase

```
Input → Parse → Resolve Classification → Resolve/Derive Idempotency Key → Upsert Lead (status=received)
```

**Technical Details:**

- Request parsing via FastAPI dependency injection

- Classification resolution (source → offer → market/vertical) per Lead Ingestion Classification Contract

- Idempotency key handling: accept client-provided key or derive deterministically (scoped by source_id)

- Concurrency-safe upsert using `INSERT ... ON CONFLICT (source_id, idempotency_key) DO UPDATE ... RETURNING id`

- CSRF token validation (implemented in production)

- Rate limiting: 10 requests/minute per IP (configured via Nginx)

- Bot detection: Basic User-Agent filtering

#### Validation Phase

All validation rules are derived from the offer's validation_policy.rules (JSONB), not hardcoded to any one market or niche.

**Policy Examples (rules JSONB):**

- Duplicate window: duplicate_window_hours

- Allowed service areas: allowed_postal_codes and/or allowed_cities

- Phone validation: phone_region or allowed_country_codes

- Field requirements per vertical: required_fields

- Disposable email: disposable_email_blocklist_enabled

- Optional MX lookup: mx_lookup_enabled

**Deterministic flow:**

```
Lead Data → Load Offer → Load Validation Policy → Execute Duplicate Detection → Execute Plugins → Persist validation_reason on fail → Transition status to validated on success
```

**Duplicate Detection (per policy):**

Duplicate detection runs after lead row creation and before validation. It checks for materially the same lead (matching phone/email) within a configured time window, scoped to the offer. Actions: `reject` (stop pipeline), `flag` (continue with flag), or `accept` (record but continue).

**Idempotency Guard:**

```sql
UPDATE leads 
SET status = 'validated', validation_reason = NULL
WHERE id = :lead_id AND status = 'received'
```

This ensures validation transition is idempotent—replays of the same lead do not double-validate.

#### Routing Phase

Routing decisions are derived from:

- offers.routing_policy_id

- buyer_offers (enrollment, priority, caps, per-offer pricing/overrides)

- buyer_service_areas (market coverage)

- offer_exclusivities (exclusive buyer per scope)

**Buyer Selection Algorithm:**

```python
def select_buyer(lead):
    # 1) Exclusive buyer (offer + scope)
    exclusive = get_exclusive_buyer(
        offer_id=lead.offer_id,
        scope_type="postal_code",
        scope_value=lead.postal_code,
    )
    if exclusive:
        return exclusive

    # 2) Eligible buyers for offer + market + service area
    candidates = get_eligible_buyers_for_offer_and_area(
        offer_id=lead.offer_id,
        market_id=lead.market_id,
        postal_code=lead.postal_code,
        city=lead.city,
    )

    # 3) Priority + fairness per routing_policy.config
    return policy_select(candidates, routing_policy_config=load_routing_config(lead.offer_id))
```

#### Delivery Phase

```
Validated Lead → Select Buyer → Update Status (delivered) → Format Payload → Attempt Webhook (3 retries) → Fallback to Email → Log Result
```

**Idempotency Guard:**

```sql
UPDATE leads 
SET status = 'delivered', buyer_id = :buyer_id, delivered_at = CURRENT_TIMESTAMP
WHERE id = :lead_id AND status = 'validated'
```

This ensures delivery transition is idempotent—replays do not double-route to different buyers.

**Retry Strategy:**

- Attempt 1: Immediate

- Attempt 2: 5-second delay

- Attempt 3: 15-second delay

- Exponential backoff configurable

#### Billing Phase

```
Delivered Lead → Atomic Balance Update → Check Threshold → Generate Invoice
```

**Atomic Update Implementation:**

```sql
-- Prevents double-billing race conditions (idempotency guard: billing_status = 'pending')
WITH lead_update AS (
    UPDATE leads 
    SET billing_status = 'billed', 
        price = :price,
        billed_at = CURRENT_TIMESTAMP
    WHERE id = :lead_id 
      AND billing_status = 'pending'
    RETURNING id
),
buyer_update AS (
    UPDATE buyers 
    SET balance = balance + :price
    WHERE id = :buyer_id
      AND EXISTS (SELECT 1 FROM lead_update)
    RETURNING id, balance
)
SELECT * FROM buyer_update;
```

**Idempotency Guard:** The `WHERE billing_status = 'pending'` clause ensures billing is idempotent—replays do not double-bill the same lead.

## Configuration Management

### Environment Variables (.env)

Remove market-specific hardcoding (e.g., ALLOWED_ZIP_PREFIXES). Validation/routing live in DB policies.

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/leadgen_db
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40

# Redis
REDIS_URL=redis://redis:6379/0

# Security
SECRET_KEY=64-byte-base64-encoded-random-string
JWT_ALGORITHM=HS256
ENVIRONMENT=production  # development, staging, production

# Source Resolution (optional)
# If using deterministic source mapping without hostname/path matching:
DEFAULT_SOURCE_KEY=

# Email (SMTP) - provider-agnostic
SMTP_HOST=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USER=your_user
SMTP_PASSWORD=your_password
FROM_EMAIL=leads@yourdomain.com

# SMS (Twilio)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890

# Webhook Configuration
WEBHOOK_TIMEOUT_SECONDS=5
WEBHOOK_MAX_RETRIES=3
WEBHOOK_RETRY_DELAY=1

# Business Rules (platform-wide defaults only)
DEFAULT_INVOICE_THRESHOLD=500.00
DEFAULT_DUPLICATE_WINDOW_HOURS=24

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Nginx Configuration Highlights

```nginx
# Security headers
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'" always;

# Rate limiting (per IP)
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req zone=api burst=20 nodelay;

# File upload limits
client_max_body_size 10M;
client_body_buffer_size 128k;

# Static file caching
location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

## Monitoring and Observability

### Key Performance Indicators (KPIs)

```sql
-- Daily metrics
SELECT 
    DATE(created_at) as day,
    COUNT(*) as total_leads,
    COUNT(CASE WHEN status = 'delivered' THEN 1 END) as delivered,
    COUNT(CASE WHEN status = 'rejected' THEN 1 END) as rejected,
    SUM(CASE WHEN billing_status = 'billed' THEN price ELSE 0 END) as revenue,
    AVG(EXTRACT(EPOCH FROM (delivered_at - created_at))) as avg_delivery_time_seconds
FROM leads
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(created_at)
ORDER BY day DESC;
```

### Health Check Endpoints

- **GET /health**            # Basic system health
- **GET /health/db**         # Database connectivity
- **GET /health/redis**      # Redis connectivity
- **GET /metrics**           # Prometheus metrics (future)
- **GET /debug/headers**     # Request inspection

### Logging Strategy

```python
# Structured logging with context
logger.info(
    "lead_processed",
    lead_id=lead.id,
    status=lead.status,
    buyer_id=lead.buyer_id,
    processing_time_ms=processing_time,
    request_id=request.state.request_id,
    client_ip=request.client.host
)
```

**Log levels:**

- **DEBUG**: Detailed processing steps

- **INFO**: Business events (lead received, delivered)

- **WARNING**: Non-critical issues (webhook timeout)

- **ERROR**: System failures (database down)

- **CRITICAL**: Data loss scenarios

## Security Implementation

### Data Protection

- **PII Encryption**: Phone numbers encrypted at rest (SQLAlchemy encryption extension ready)

- **SSL/TLS**: Enforce HTTPS for all traffic (TLS termination at Nginx)

- **CSRF Protection**: Synchronizer token pattern implemented for form submissions

- **SQL Injection Prevention**: Parameterized queries via SQLAlchemy

- **XSS Prevention**: Strong Content-Security-Policy headers

- **Rate Limiting**: Nginx and application-level request rate limiting

### Access Control

- **Anonymous**: Submit leads only

- **Buyer**: View and update own leads (accept/reject)

- **Admin**: Full system access (manage buyers, configuration, reports)

- **System**: Internal service accounts (background tasks)

### Audit Trail

```sql
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
```

## Scalability Considerations

### Vertical Scaling Path

- **Phase 1 (0–100 leads/day)**: Single server running all services.

- **Phase 2 (100–1000 leads/day)**: Introduce database read replicas and a Redis cache.

- **Phase 3 (1k–10k leads/day)**: Split into microservices; add a message queue (RabbitMQ/Kafka).

- **Phase 4 (10k+ leads/day)**: Geographic sharding, use CDN for static content, and add a dedicated analytics cluster.

### Database Optimization

```sql
-- Partitioning for high-volume tables
CREATE TABLE leads_2024 PARTITION OF leads
FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

-- Connection pooling
-- (e.g., PgBouncer or pgpool-II to manage 50-100 concurrent DB connections)
```

### Caching Strategy

```python
# Redis cache keys
CACHE_KEYS = {
    'active_buyers': 'buyers:active',            # TTL: 5 minutes
    'zip_buyer_map': 'routing:zip:{zip_code}',   # TTL: 1 hour
    'lead_duplicate:{phone_hash}': 'leads:duplicate_check',  # TTL: 24 hours
    'buyer_balance:{buyer_id}': 'billing:balance',  # TTL: 10 minutes
}
```

## Deployment Architecture

### Container Specifications

```yaml
services:
  postgres:
    image: postgres:15-alpine
    command: >
      postgres 
      -c shared_preload_libraries=pg_stat_statements
      -c pg_stat_statements.track=all
      -c max_connections=200
      -c shared_buffers=256MB
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
      target: production
    environment:
      - GUNICORN_WORKERS=4
      - GUNICORN_THREADS=2
      - UVICORN_LOG_LEVEL=warning
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
```

### Production Readiness Checklist

- SSL certificates installed and auto-renewing

- Database backups configured (WAL streaming + daily full)

- Log aggregation (ELK stack or equivalent)

- Monitoring alerts (uptime, error rate, latency)

- Disaster recovery plan documented

- Load testing completed (1000 req/sec target)

- Security audit completed (OWASP Top 10)

- GDPR compliance measures implemented

## Failure Modes and Recovery

### Critical Failure Scenarios

- **Database Connection Loss**: Implement retry logic with exponential backoff for DB connections.

- **Webhook Delivery Failure**: Fallback to email delivery and queue the lead for manual review.

- **Duplicate Lead Processing**: Use idempotency keys and database constraints to prevent duplicate billing.

- **Payment Processing Failure**: Provide a grace period with automated retry attempts for payment charging.

### Disaster Recovery Plan

- **RPO (Recovery Point Objective)**: 15 minutes

- **RTO (Recovery Time Objective)**: 1 hour

**Backup Strategy:**

- **Real-time**: WAL streaming to a backup server

- **Hourly**: Point-in-time recovery snapshots

- **Daily**: Full database dump to cloud storage (S3/GCS)

- **Weekly**: Full system image backup

### Data Retention Policy

- **Leads**: 36 months (legal requirement in some jurisdictions)

- **Audit logs**: 7 years (tax compliance)

- **System logs**: 90 days

- **Backup files**: 365 days

- **Archived data**: Compressed and moved to cold storage after retention period

## Extension Points & API Surface

### Webhook Events System

```python
EVENT_TYPES = {
    'lead.received': 'Lead submitted to system',
    'lead.validated': 'Lead passed validation',
    'lead.delivered': 'Lead sent to buyer',
    'lead.accepted': 'Buyer accepted lead',
    'lead.rejected': 'Buyer rejected lead',
    'invoice.generated': 'New invoice created',
    'payment.received': 'Buyer payment processed',
    'buyer.balance_threshold': 'Buyer balance exceeds threshold',
}
```

### Plugin Architecture Hooks

```python
# Validation plugins
VALIDATION_PLUGINS = [
    'email_validation',
    'phone_validation', 
    'zip_validation',
    'duplicate_detection',
    'fraud_detection',  # Future
    'lead_scoring',     # Future
]

# Routing strategies
ROUTING_STRATEGIES = {
    'priority_based': 'Default priority system',
    'round_robin': 'Even distribution',
    'exclusive_zip': 'ZIP code exclusivity',
    'capacity_based': 'Based on buyer capacity',
    'performance_based': 'Based on historical conversion',
}
```

## Technical Debt & Future Roadmap

### Known Limitations (v1.0)

- Synchronous validation blocks API response during lead ingestion.

- Basic retry logic (no exponential backoff for webhook retries).

- Single database instance (no read replicas or automated failover).

- In-memory task queue (no persistent messaging queue).

- Manual buyer management (no self-service buyer portal).

### v2.0 Planned Enhancements

- **Async Task Queue**: Integrate Redis Queue (RQ) or Celery for background jobs.

- **Buyer Portal**: Develop a self-service dashboard with analytics.

- **Real-time Analytics**: Use a time-series database (e.g., TimescaleDB) for metrics.

- **Machine Learning**: Add lead scoring and fraud detection models.

- **Multi-tenancy**: Support multiple cities and service verticals.

- **API Versioning**: Implement semantic versioning with a deprecation schedule.

## Reference Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Client Browser                             │
│  • Landing Pages (multi-market/vertical)                           │
│  • Partner API Integrations                                         │
│  • Form Embeds                                                      │
└─────────────────┬───────────────────────────────────────────────────┘
                  │ HTTPS
┌─────────────────▼───────────────────────────────────────────────────┐
│                          Nginx Reverse Proxy                        │
│  ┌─────────────────────────┐  ┌──────────────────────────┐          │
│  │ Static File Serving     │  │ API Proxying             │          │
│  │ • landing/*             │  │ • /api/* → FastAPI       │          │
│  │ • SSL Termination       │  │ • Rate Limiting          │          │
│  │ • GZIP Compression      │  │ • Request Logging        │          │
│  └─────────────────────────┘  └──────────────────────────┘          │
└─────────────────┬───────────────────────────────────────────────────┘
                  │ HTTP/1.1
┌─────────────────▼───────────────────────────────────────────────────┐
│                         FastAPI Application                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Lead Ingestion Pipeline                     │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │   │
│  │  │ Classification│  │ Validation  │  │   Routing    │        │   │
│  │  │ Resolution    │  │ (Policy-    │  │ (Policy-     │        │   │
│  │  │ • source_key │  │  Driven)    │  │  Driven)     │        │   │
│  │  │ • hostname/   │  │ • Load      │  │ • Load       │        │   │
│  │  │   path       │  │   validation│  │   routing    │        │   │
│  │  │ • → source_id│  │   policy    │  │   policy     │        │   │
│  │  │ • → offer_id │  │ • Execute   │  │ • Select     │        │   │
│  │  │ • → market/  │  │   plugins   │  │   buyer      │        │   │
│  │  │   vertical   │  │             │  │              │        │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │ Middleware  │  │ API Routes  │  │ Background  │                  │
│  │ • CORS      │  │ • /leads    │  │ • Delivery  │                  │
│  │ • Logging   │  │ • /buyers   │  │ • Billing   │                  │
│  │ • Auth      │  │ • /health   │  │ • Reporting │                  │
│  └─────────────┘  └─────────────┘  └─────────────┘                  │
└─────────────────┬───────────────────────────────────────────────────┘
                  │ SQL + Connection Pool
┌─────────────────▼───────────────────────────────────────────────────┐
│                        PostgreSQL Database                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              Configuration & Reference Data                    │  │
│  │  • markets          • validation_policies                     │  │
│  │  • verticals        • routing_policies                         │  │
│  │  • offers           • sources                                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Transactional Data                          │  │
│  │  • leads (with market_id, vertical_id, offer_id, source_id)   │  │
│  │  • buyers                                                      │  │
│  │  • buyer_offers (per-offer enrollment)                        │  │
│  │  • buyer_service_areas (market coverage)                       │  │
│  │  • offer_exclusivities                                         │  │
│  │  • invoices (per offer)                                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────┐  ┌──────────────────────────┐          │
│  │ Connection Pool         │  │ Indexes & Performance   │          │
│  │ • 20-50 connections     │  │ • Multi-tenant indexes │          │
│  │ • Transaction isolation │  │ • Classification       │          │
│  │ • Read/write splitting  │  │   resolution indexes    │          │
│  └─────────────────────────┘  └──────────────────────────┘          │
└─────────────────┬───────────────────────────────────────────────────┘
                  │ Async Tasks
┌─────────────────▼───────────────────────────────────────────────────┐
│                        External Integrations                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │ SMTP Server │  │ Webhooks    │  │ SMS Gateway │                  │
│  │ • Lead      │  │ • Buyer     │  │ • Twilio    │                  │
│  │ delivery    │  │ systems     │  │ integration │                  │
│  │ • Invoice   │  │ • CRM       │  │             │                  │
│  │ sending     │  │ integration │  │             │                  │
│  └─────────────┘  └─────────────┘  └─────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘

Key Architectural Changes (Multi-Market/Vertical Support):
• Classification: Deterministic source → offer → market/vertical resolution
• Validation: Policy-driven rules stored in validation_policies (JSONB)
• Routing: Policy-driven buyer selection via routing_policies (JSONB)
• Buyers: Scoped per-offer via buyer_offers with per-offer pricing/capacity
• Service Areas: Normalized in buyer_service_areas (postal_code/city)
• Billing: Per-offer invoicing with offer_id on invoices
• Seamless Transition: Add new markets/verticals via DB config only
```

## Glossary of Terms

- **Lead**: A potential customer inquiry with contact information

- **Buyer**: Service provider who purchases leads (e.g., plumber)

- **Validation**: The process of verifying lead quality and eligibility

- **Routing**: The algorithm for matching leads to appropriate buyers

- **Billing**: The process of charging buyers for delivered leads

- **Webhook**: HTTP callback for real-time lead delivery

- **SLA**: Service Level Agreement (lead delivery time guarantee)

- **UTM**: Urchin Tracking Module parameters for attribution

- **PII**: Personally Identifiable Information (e.g., email, phone)

- **E.164**: International phone number formatting standard

- **Idempotency**: Property where identical requests produce the same result

- **Atomicity**: Database transactions that succeed or fail completely

- **Idempotency Key**: Unique identifier to prevent duplicate processing

This technical specification serves as the single source of truth for the system's architecture, implementation details, and operational procedures. All technical decisions, configurations, and extensions should reference this document for consistency and maintainability.

