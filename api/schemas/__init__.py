# api/schemas/__init__.py
"""
Pydantic schemas for request/response validation and serialization.
"""

from api.schemas.leads_ingest import LeadIngestRequest
from api.schemas.leads_ingest_response import LeadIngestResponse

__all__ = [
    "LeadIngestRequest",
    "LeadIngestResponse",
]
