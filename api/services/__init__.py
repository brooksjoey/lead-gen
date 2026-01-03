# api/services/__init__.py
"""
Business logic services organized by domain functionality.
"""

# Import key service functions and classes for convenient access
from api.services.classification_resolver import (
    ClassificationError,
    ClassificationResult,
    resolve_classification,
)
from api.services.idempotency import (
    IdempotencyError,
    LeadInsertResult,
    derive_idempotency_key,
    resolve_idempotency_key,
)
from api.services.lead_ingest import ingest_lead

__all__ = [
    # Classification
    "ClassificationError",
    "ClassificationResult",
    "resolve_classification",
    # Idempotency
    "IdempotencyError",
    "LeadInsertResult",
    "derive_idempotency_key",
    "resolve_idempotency_key",
    # Lead ingestion
    "ingest_lead",
]
