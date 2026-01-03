# api/services/classification.py
"""
Alias module for classification_resolver for backward compatibility with tests.
Re-exports all functions and classes from classification_resolver.
"""
from api.services.classification_resolver import (
    ClassificationError,
    ClassificationResult,
    canonicalize_hostname,
    canonicalize_path,
    canonicalize_source_key,
    resolve_classification,
)

# Alias for tests that expect SourceResolutionError
SourceResolutionError = ClassificationError

__all__ = [
    "SourceResolutionError",
    "ClassificationError",
    "ClassificationResult",
    "canonicalize_hostname",
    "canonicalize_path",
    "canonicalize_source_key",
    "resolve_classification",
]

