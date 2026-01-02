from typing import Optional

from pydantic import BaseModel, EmailStr, Field

class LeadIn(BaseModel):
    source: str = Field('landing_page')
    name: str
    email: EmailStr
    phone: str
    zip: str
    message: Optional[str] = None
    consent: bool
    gdpr_consent: Optional[bool] = Field(True)
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None

class LeadResponse(BaseModel):
    lead_id: int
    status: str
    message: str
    buyer_id: Optional[int]
    price: float
