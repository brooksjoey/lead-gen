# api/models/lead.py
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
    Index,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import relationship

from api.db.base import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column("id", primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Legacy string source retained for compatibility; classification system-of-record is source_id/offer_id/market_id/vertical_id.
    source = Column(String(100), nullable=False, server_default="landing_page")

    # System-of-record attribution (must be non-null for new ingested leads; DB enforces via NOT VALID check until backfilled).
    source_id = Column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=True, index=True)
    offer_id = Column(ForeignKey("offers.id", ondelete="RESTRICT"), nullable=True, index=True)
    market_id = Column(ForeignKey("markets.id", ondelete="RESTRICT"), nullable=True, index=True)
    vertical_id = Column(ForeignKey("verticals.id", ondelete="RESTRICT"), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=False)
    zip = Column(String(10), nullable=False)
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

    __table_args__ = (
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
        CheckConstraint("length(phone) > 0", name="check_phone_not_empty"),
        CheckConstraint("length(email) > 0", name="check_email_not_empty"),
    )
