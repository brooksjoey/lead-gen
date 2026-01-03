# api/models/lead.py
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    Index,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import relationship

from api.db.base import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Legacy string source retained for compatibility; classification system-of-record is source_id/offer_id/market_id/vertical_id.
    source = Column(String(100), nullable=False, server_default="landing_page")

    # System-of-record attribution (must be non-null for new ingested leads).
    # Note: Currently nullable=True to support legacy data; new leads should have these set.
    # Application logic should enforce non-null for new leads (status='received').
    source_id = Column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=True, index=True)
    offer_id = Column(ForeignKey("offers.id", ondelete="RESTRICT"), nullable=True, index=True)
    market_id = Column(ForeignKey("markets.id", ondelete="RESTRICT"), nullable=True, index=True)
    vertical_id = Column(ForeignKey("verticals.id", ondelete="RESTRICT"), nullable=True, index=True)
    
    # Idempotency key for preventing duplicates across retries/reposts
    idempotency_key = Column(String(128), nullable=True)

    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=False)
    zip = Column(String(10), nullable=False)  # Legacy field name, maps to postal_code in API
    postal_code = Column(String(16), nullable=True)  # New field from spec schema
    city = Column(String(128), nullable=True)
    country_code = Column(String(2), nullable=True, server_default="US")
    region_code = Column(String(20), nullable=True)
    message = Column(Text)

    status = Column(Enum("received", "validated", "delivered", "accepted", "rejected", name="lead_status"), nullable=False, server_default="received")
    validation_reason = Column(String(500))

    buyer_id = Column(ForeignKey("buyers.id", ondelete="SET NULL"), nullable=True)
    buyer = relationship("Buyer", back_populates="leads")

    delivered_at = Column(DateTime(timezone=True))
    accepted_at = Column(DateTime(timezone=True))
    rejected_at = Column(DateTime(timezone=True))
    rejection_reason = Column(String(500))

    billing_status = Column(Enum("pending", "billed", "paid", "disputed", "refunded", name="billing_status"), nullable=False, server_default="pending")
    price = Column(Numeric(10, 2))
    billed_at = Column(DateTime(timezone=True))
    paid_at = Column(DateTime(timezone=True))

    utm_source = Column(String(100))
    utm_medium = Column(String(100))
    utm_campaign = Column(String(100))

    ip_address = Column(INET)
    user_agent = Column(Text)
    
    # Delivery tracking
    delivery_attempts = Column(Integer, nullable=True, server_default="0")
    delivery_result = Column(JSONB, nullable=True)  # Stores DeliveryResult as JSON
    
    # Duplicate detection
    normalized_email = Column(String(320), nullable=True)
    normalized_phone = Column(String(32), nullable=True)
    duplicate_of_lead_id = Column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True)
    is_duplicate = Column(Boolean, nullable=False, server_default="false")
    hash = Column(String(64), nullable=True, index=True)  # For deduplication - should be unique per (email, phone, postal_code, buyer_id, offer_id)
    duplicate_count = Column(Integer, nullable=True, server_default="0")
    
    # Audit fields
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(Integer, nullable=True)

    __table_args__ = (
        # Basic indexes
        Index("idx_leads_email", "email"),
        Index("idx_leads_phone", "phone"),
        Index("idx_leads_created_at", "created_at"),
        Index("idx_leads_status", "status"),
        Index("idx_leads_billing_status", "billing_status"),
        Index("idx_leads_buyer_id", "buyer_id"),
        Index("idx_leads_phone_created", "phone", "created_at"),
        Index("idx_leads_zip_created", "zip", "created_at"),
        Index("idx_leads_source_created_at", "source_id", "created_at"),
        Index("idx_leads_offer_created_at", "offer_id", "created_at"),
        Index("idx_leads_market_created_at", "market_id", "created_at"),
        Index("idx_leads_vertical_created_at", "vertical_id", "created_at"),
        
        # Idempotency constraint (enforced in migration 004_leads_idempotency.sql)
        # Unique constraint on (source_id, idempotency_key) prevents duplicate ingestion
        
        # Duplicate detection indexes
        Index("idx_leads_hash", "hash"),  # For hash-based deduplication lookups
        Index("idx_leads_duplicate_of", "duplicate_of_lead_id"),
        Index("idx_leads_normalized_phone", "normalized_phone"),
        Index("idx_leads_normalized_email", "normalized_email"),
        Index("idx_leads_offer_norm_phone_created", "offer_id", "normalized_phone", "created_at"),
        Index("idx_leads_offer_norm_email_created", "offer_id", "normalized_email", "created_at"),
        
        # Constraints
        CheckConstraint("length(phone) > 0", name="check_phone_not_empty"),
        CheckConstraint("length(email) > 0", name="check_email_not_empty"),
        CheckConstraint(
            "normalized_phone IS NULL OR LENGTH(normalized_phone) BETWEEN 7 AND 32",
            name="leads_normalized_phone_len"
        ),
        CheckConstraint(
            "normalized_email IS NULL OR LENGTH(normalized_email) BETWEEN 3 AND 320",
            name="leads_normalized_email_len"
        ),
        # Enforce attribution fields for new leads (status='received')
        # Note: This allows legacy data but enforces new leads have attribution
        CheckConstraint(
            "(status != 'received') OR (source_id IS NOT NULL AND offer_id IS NOT NULL AND market_id IS NOT NULL AND vertical_id IS NOT NULL)",
            name="check_new_leads_have_attribution"
        ),
    )
