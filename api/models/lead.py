from sqlalchemy import (
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
    Index
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import relationship

from api.db.base import Base

lead_status = Enum(
    'received',
    'validated',
    'delivered',
    'accepted',
    'rejected',
    name='lead_status',
    create_type=False
)

billing_status = Enum(
    'pending',
    'billed',
    'paid',
    'disputed',
    'refunded',
    name='billing_status',
    create_type=False
)

class Lead(Base):
    __tablename__ = 'leads'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    source = Column(String(100), nullable=False, server_default='landing_page')
    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=False)
    zip = Column(String(10), nullable=False)
    message = Column(Text)
    status = Column(lead_status, nullable=False, server_default='received')
    validation_reason = Column(String(500))
    buyer_id = Column(Integer, ForeignKey('buyers.id', ondelete='SET NULL'))
    delivered_at = Column(DateTime(timezone=True))
    accepted_at = Column(DateTime(timezone=True))
    rejected_at = Column(DateTime(timezone=True))
    rejection_reason = Column(String(500))
    billing_status = Column(billing_status, nullable=False, server_default='pending')
    price = Column(Numeric(10, 2))
    billed_at = Column(DateTime(timezone=True))
    paid_at = Column(DateTime(timezone=True))
    utm_source = Column(String(100))
    utm_medium = Column(String(100))
    utm_campaign = Column(String(100))
    ip_address = Column(INET)
    user_agent = Column(Text)

    buyer = relationship('Buyer', back_populates='leads')

    __table_args__ = (
        Index('idx_leads_email', 'email'),
        Index('idx_leads_phone', 'phone'),
        Index('idx_leads_created_at', 'created_at'),
        Index('idx_leads_status', 'status'),
        Index('idx_leads_billing_status', 'billing_status'),
        Index('idx_leads_buyer_id', 'buyer_id'),
        Index('idx_leads_phone_created', 'phone', 'created_at'),
        Index('idx_leads_zip_created', 'zip', 'created_at'),
        CheckConstraint("char_length(phone) > 0", name='check_phone_not_empty'),
        CheckConstraint("char_length(email) > 0", name='check_email_not_empty')
    )
