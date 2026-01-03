# api/schemas/leads_ingest.py
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LeadIngestRequest(BaseModel):
    # Attribution (classification)
    source_id: Optional[int] = Field(default=None, ge=1)
    source_key: Optional[str] = Field(default=None, min_length=2, max_length=128)

    # Idempotency
    idempotency_key: Optional[str] = Field(default=None, min_length=16, max_length=128)

    # Lead fields
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=32)
    zip: str = Field(min_length=1, max_length=10)
    message: Optional[str] = Field(default=None, max_length=5000)

    # Compliance / attribution fields already used in repo
    consent: bool
    gdpr_consent: Optional[bool] = Field(default=True)

    utm_source: Optional[str] = Field(default=None, max_length=100)
    utm_medium: Optional[str] = Field(default=None, max_length=100)
    utm_campaign: Optional[str] = Field(default=None, max_length=100)

