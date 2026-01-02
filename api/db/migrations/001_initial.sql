CREATE TYPE IF NOT EXISTS lead_status AS ENUM ('received', 'validated', 'delivered', 'accepted', 'rejected');
CREATE TYPE IF NOT EXISTS billing_status AS ENUM ('pending', 'billed', 'paid', 'disputed', 'refunded');
CREATE TYPE IF NOT EXISTS invoice_status AS ENUM ('draft', 'sent', 'paid', 'overdue', 'cancelled', 'disputed');
CREATE TYPE IF NOT EXISTS payment_method AS ENUM ('stripe', 'manual', 'bank_transfer', 'check');

CREATE TABLE IF NOT EXISTS buyers (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ,
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL,
    company VARCHAR(200),
    webhook_url VARCHAR(500),
    webhook_secret VARCHAR(200),
    email_notifications BOOLEAN DEFAULT true NOT NULL,
    sms_notifications BOOLEAN DEFAULT false NOT NULL,
    is_active BOOLEAN DEFAULT true NOT NULL,
    routing_priority INTEGER DEFAULT 1 NOT NULL,
    exclusive BOOLEAN DEFAULT false NOT NULL,
    service_zips TEXT,
    service_cities TEXT,
    price_per_lead DECIMAL(10,2) DEFAULT 45.00 NOT NULL,
    balance DECIMAL(12,2) DEFAULT 0.00 NOT NULL,
    credit_limit DECIMAL(12,2),
    billing_cycle VARCHAR(20) DEFAULT 'weekly' NOT NULL,
    payment_method payment_method,
    payment_method_id VARCHAR(200),
    CONSTRAINT check_positive_price CHECK (price_per_lead > 0),
    CONSTRAINT check_non_negative_balance CHECK (balance >= 0),
    CONSTRAINT check_positive_priority CHECK (routing_priority >= 1)
);

CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ,
    source VARCHAR(100) DEFAULT 'landing_page' NOT NULL,
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    zip VARCHAR(10) NOT NULL,
    message TEXT,
    status lead_status DEFAULT 'received' NOT NULL,
    validation_reason VARCHAR(500),
    buyer_id INTEGER REFERENCES buyers(id) ON DELETE SET NULL,
    delivered_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    rejection_reason VARCHAR(500),
    billing_status billing_status DEFAULT 'pending' NOT NULL,
    price DECIMAL(10,2),
    billed_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    utm_source VARCHAR(100),
    utm_medium VARCHAR(100),
    utm_campaign VARCHAR(100),
    ip_address INET,
    user_agent TEXT,
    CONSTRAINT check_email_not_empty CHECK (length(email) > 0),
    CONSTRAINT check_phone_not_empty CHECK (length(phone) > 0)
);

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ,
    buyer_id INTEGER NOT NULL REFERENCES buyers(id) ON DELETE CASCADE,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    due_date TIMESTAMPTZ NOT NULL,
    invoice_number VARCHAR(50) NOT NULL UNIQUE,
    status invoice_status DEFAULT 'draft' NOT NULL,
    total_leads INTEGER DEFAULT 0 NOT NULL,
    amount_due DECIMAL(10,2) DEFAULT 0.00 NOT NULL,
    tax_amount DECIMAL(10,2) DEFAULT 0.00 NOT NULL,
    total_amount DECIMAL(10,2) DEFAULT 0.00 NOT NULL,
    payment_method payment_method,
    paid_at TIMESTAMPTZ,
    transaction_id VARCHAR(200),
    disputed_at TIMESTAMPTZ,
    dispute_reason TEXT,
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    CONSTRAINT check_valid_period CHECK (period_start < period_end),
    CONSTRAINT check_non_negative_leads CHECK (total_leads >= 0),
    CONSTRAINT check_non_negative_amount CHECK (amount_due >= 0)
);

CREATE INDEX IF NOT EXISTS idx_buyers_email ON buyers(email);
CREATE INDEX IF NOT EXISTS idx_buyers_is_active ON buyers(is_active);
CREATE INDEX IF NOT EXISTS idx_buyers_is_active_priority ON buyers(is_active, routing_priority);
CREATE INDEX IF NOT EXISTS idx_buyers_balance_active ON buyers(balance) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_billing_status ON leads(billing_status);
CREATE INDEX IF NOT EXISTS idx_leads_buyer_id ON leads(buyer_id);
CREATE INDEX IF NOT EXISTS idx_leads_phone_created ON leads(phone, created_at);
CREATE INDEX IF NOT EXISTS idx_leads_zip_created ON leads(zip, created_at);

CREATE INDEX IF NOT EXISTS idx_invoices_buyer_id ON invoices(buyer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_period ON invoices(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_invoices_status_due ON invoices(status, due_date);
CREATE INDEX IF NOT EXISTS idx_invoices_paid_at ON invoices(paid_at) WHERE paid_at IS NOT NULL;
