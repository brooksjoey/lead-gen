# api/schemas/leads_ingest_response.py
from __future__ import annotations

from pydantic import BaseModel, Field


class LeadIngestResponse(BaseModel):
    lead_id: int = Field(ge=1)
    status: str

    source_id: int = Field(ge=1)
    offer_id: int = Field(ge=1)
    market_id: int = Field(ge=1)
    vertical_id: int = Field(ge=1)

    idempotency_key: str

