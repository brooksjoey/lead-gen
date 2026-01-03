-- Lead Status and Billing Status Enums

DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'lead_status') THEN
        CREATE TYPE lead_status AS ENUM (
          'received', 'validated', 'delivered', 'accepted', 'rejected'
        );
    END IF;
END $$;

DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'billing_status') THEN
        CREATE TYPE billing_status AS ENUM (
          'pending', 'billed', 'paid', 'disputed', 'refunded'
        );
    END IF;
END $$;

-- Invoice Status and Payment Method Enums

DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'invoice_status') THEN
        CREATE TYPE invoice_status AS ENUM (
          'draft', 'sent', 'paid', 'overdue', 'cancelled', 'disputed'
        );
    END IF;
END $$;

DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_method') THEN
        CREATE TYPE payment_method AS ENUM (
          'stripe', 'manual', 'bank_transfer', 'check'
        );
    END IF;
END $$;

