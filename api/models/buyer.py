from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    Boolean,
    func,
    Index,
    text
)
from sqlalchemy.orm import relationship

from api.db.base import Base

class Buyer(Base):
    __tablename__ = 'buyers'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    phone = Column(String(20), nullable=False)
    company = Column(String(200))
    webhook_url = Column(String(500))
    webhook_secret = Column(String(200))
    email_notifications = Column(Boolean, nullable=False, server_default='true')
    sms_notifications = Column(Boolean, nullable=False, server_default='false')
    is_active = Column(Boolean, nullable=False, server_default='true')
    routing_priority = Column(Integer, nullable=False, server_default='1')
    exclusive = Column(Boolean, nullable=False, server_default='false')
    service_zips = Column(Text)
    service_cities = Column(Text)
    price_per_lead = Column(Numeric(10, 2), nullable=False, server_default='45.00')
    balance = Column(Numeric(12, 2), nullable=False, server_default='0.00')
    credit_limit = Column(Numeric(12, 2))
    billing_cycle = Column(String(20), nullable=False, server_default='weekly')
    payment_method = Column(String(50))
    payment_method_id = Column(String(200))

    leads = relationship('Lead', back_populates='buyer')
    invoices = relationship('Invoice', back_populates='buyer')

    __table_args__ = (
        Index('idx_buyers_email', 'email'),
        Index('idx_buyers_is_active', 'is_active'),
        Index('idx_buyers_is_active_priority', 'is_active', 'routing_priority'),
        Index('idx_buyers_balance_active', 'balance', postgresql_where=text('is_active = true')),
        CheckConstraint('price_per_lead > 0', name='check_positive_price'),
        CheckConstraint('balance >= 0', name='check_non_negative_balance'),
        CheckConstraint('routing_priority >= 1', name='check_positive_priority')
    )
