-- Lead Status and Billing Status Enums

CREATE TYPE lead_status AS ENUM (
  'received', 'validated', 'delivered', 'accepted', 'rejected'
);

CREATE TYPE billing_status AS ENUM (
  'pending', 'billed', 'paid', 'disputed', 'refunded'
);

-- Invoice Status and Payment Method Enums

CREATE TYPE invoice_status AS ENUM (
  'draft', 'sent', 'paid', 'overdue', 'cancelled', 'disputed'
);

CREATE TYPE payment_method AS ENUM (
  'stripe', 'manual', 'bank_transfer', 'check'
);

