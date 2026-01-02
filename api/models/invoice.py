from sqlalchemy import (
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
    CheckConstraint
)
from sqlalchemy.orm import relationship

from api.db.base import Base

invoice_status = Enum(
    'draft',
    'sent',
    'paid',
    'overdue',
    'cancelled',
    'disputed',
    name='invoice_status',
    create_type=False
)
payment_method_enum = Enum(
    'stripe',
    'manual',
    'bank_transfer',
    'check',
    name='payment_method',
    create_type=False
)

class Invoice(Base):
    __tablename__ = 'invoices'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    buyer_id = Column(Integer, ForeignKey('buyers.id', ondelete='CASCADE'), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    invoice_number = Column(String(50), nullable=False, unique=True)
    status = Column(invoice_status, nullable=False, server_default='draft')
    total_leads = Column(Integer, nullable=False, server_default='0')
    amount_due = Column(Numeric(12, 2), nullable=False, server_default='0.00')
    tax_amount = Column(Numeric(12, 2), nullable=False, server_default='0.00')
    total_amount = Column(Numeric(12, 2), nullable=False, server_default='0.00')
    payment_method = Column(payment_method_enum)
    paid_at = Column(DateTime(timezone=True))
    transaction_id = Column(String(200))
    disputed_at = Column(DateTime(timezone=True))
    dispute_reason = Column(Text)
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)

    buyer = relationship('Buyer', back_populates='invoices')

    __table_args__ = (
        Index('idx_invoices_buyer_id', 'buyer_id'),
        Index('idx_invoices_period', 'period_start', 'period_end'),
        Index('idx_invoices_status_due', 'status', 'due_date'),
        Index('idx_invoices_paid_at', 'paid_at'),
        CheckConstraint('period_start < period_end', name='check_valid_period'),
        CheckConstraint('total_leads >= 0', name='check_non_negative_leads'),
        CheckConstraint('amount_due >= 0', name='check_non_negative_amount')
    )
