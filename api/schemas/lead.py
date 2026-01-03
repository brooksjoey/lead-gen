from typing import Optional

from pydantic import BaseModel, EmailStr, Field

class LeadIn(BaseModel):
    source: str = Field(default='landing_page')
    source_key: Optional[str] = None
    source_id: Optional[int] = None  # For admin/internal use
    idempotency_key: Optional[str] = None
    name: str
    email: EmailStr
    phone: str
    country_code: str = Field(default='US')
    postal_code: str
    city: Optional[str] = None
    region_code: Optional[str] = None
    message: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    consent: Optional[bool] = None
    gdpr_consent: Optional[bool] = None

class LeadResponse(BaseModel):
    lead_id: int
    status: str
    buyer_id: Optional[int] = None
    source_id: Optional[int] = None
    offer_id: Optional[int] = None
    market_id: Optional[int] = None
    vertical_id: Optional[int] = None
    price: Optional[float] = None
