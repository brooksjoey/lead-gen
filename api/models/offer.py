# api/models/offer.py
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func, Index
from api.db.base import Base


class Offer(Base):
    __tablename__ = "offers"

    id = Column("id", primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    market_id = Column(Integer, ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False)
    vertical_id = Column(Integer, ForeignKey("verticals.id", ondelete="RESTRICT"), nullable=False)

    name = Column(String(200), nullable=False)
    offer_key = Column(String(128), nullable=False, unique=True)

    default_price_per_lead_cents = Column(Integer, nullable=False)

    is_active = Column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        Index("idx_offers_market_vertical", "market_id", "vertical_id"),
        Index("idx_offers_active_key", "is_active", "offer_key"),
    )
