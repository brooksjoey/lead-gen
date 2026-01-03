-- Index Strategy for Performance

-- Leads: multi-tenant read patterns (offer/market/vertical + time series)
CREATE INDEX IF NOT EXISTS idx_leads_offer_created_at ON leads(offer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_market_created_at ON leads(market_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_vertical_created_at ON leads(vertical_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_source_created_at ON leads(source_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_billing_status ON leads(billing_status);
CREATE INDEX IF NOT EXISTS idx_leads_buyer_created_at ON leads(buyer_id, created_at DESC);

-- Duplicate detection (typical: by offer + phone/email + time window)
CREATE INDEX IF NOT EXISTS idx_leads_offer_phone_created ON leads(offer_id, phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_offer_email_created ON leads(offer_id, email, created_at DESC);

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
CREATE INDEX IF NOT EXISTS idx_leads_source_idempotency ON leads(source_id, idempotency_key);

-- Buyer lookup by offer and priority
CREATE INDEX IF NOT EXISTS idx_buyer_offers_offer_active_priority
  ON buyer_offers(offer_id, is_active, routing_priority DESC);

-- Buyer service area resolution
CREATE INDEX IF NOT EXISTS idx_buyer_service_areas_market_scope
  ON buyer_service_areas(market_id, scope_type, scope_value)
  WHERE is_active = true;

-- Exclusivity lookup
CREATE INDEX IF NOT EXISTS idx_offer_exclusivities_offer_scope
  ON offer_exclusivities(offer_id, scope_type, scope_value)
  WHERE is_active = true;

-- Sources: classification resolution
CREATE INDEX IF NOT EXISTS idx_sources_offer_id ON sources(offer_id);
CREATE INDEX IF NOT EXISTS idx_sources_active_key ON sources(is_active, source_key);

-- HTTP mapping lookup (exact hostname; then longest-prefix match)
CREATE INDEX IF NOT EXISTS idx_sources_active_hostname ON sources(is_active, hostname);
CREATE INDEX IF NOT EXISTS idx_sources_active_hostname_prefix ON sources(is_active, hostname, path_prefix);

-- Invoices: by buyer + offer + period
CREATE INDEX IF NOT EXISTS idx_invoices_buyer_offer_period
  ON invoices(buyer_id, offer_id, period_start, period_end);

CREATE INDEX IF NOT EXISTS idx_invoices_status_due
  ON invoices(status, due_date);

CREATE INDEX IF NOT EXISTS idx_invoices_paid_at
  ON invoices(paid_at) WHERE paid_at IS NOT NULL;

-- Lead duplicate events indexes
CREATE INDEX IF NOT EXISTS idx_lde_lead_id ON lead_duplicate_events(lead_id);
CREATE INDEX IF NOT EXISTS idx_lde_offer_created_at ON lead_duplicate_events(offer_id, created_at DESC);

