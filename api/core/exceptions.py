# C:\work-spaces\lead-gen\lead-gen\api\core\exceptions.py
from __future__ import annotations

from typing import Any, Dict, Optional


class BaseAPIException(Exception):
    """Base exception for all API errors."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code or self.__class__.__name__
        self.details = details or {}
        super().__init__(self.message)


class APIError(BaseAPIException):
    """Generic API error."""
    def __init__(self, message: str = "An error occurred", **kwargs):
        super().__init__(message, status_code=500, **kwargs)


class AuthenticationError(BaseAPIException):
    """Authentication failed."""
    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, status_code=401, **kwargs)


class AuthorizationError(BaseAPIException):
    """Authorization failed."""
    def __init__(self, message: str = "Authorization failed", **kwargs):
        super().__init__(message, status_code=403, **kwargs)


class NotFoundError(BaseAPIException):
    """Resource not found."""
    def __init__(self, message: str = "Resource not found", **kwargs):
        super().__init__(message, status_code=404, **kwargs)


class ValidationError(BaseAPIException):
    """Validation error."""
    def __init__(self, message: str = "Validation error", **kwargs):
        super().__init__(message, status_code=422, **kwargs)


class ConflictError(BaseAPIException):
    """Resource conflict."""
    def __init__(self, message: str = "Resource conflict", **kwargs):
        super().__init__(message, status_code=409, **kwargs)


class BusinessRuleError(BaseAPIException):
    """Business rule violation."""
    def __init__(self, message: str = "Business rule violation", **kwargs):
        super().__init__(message, status_code=400, **kwargs)


class RateLimitError(BaseAPIException):
    """Rate limit exceeded."""
    def __init__(self, message: str = "Rate limit exceeded", retry_after: Optional[int] = None, **kwargs):
        super().__init__(message, status_code=429, **kwargs)
        self.retry_after = retry_after


class DatabaseError(BaseAPIException):
    """Database error."""
    def __init__(self, message: str = "Database error", **kwargs):
        super().__init__(message, status_code=500, **kwargs)


class DeliveryError(BaseAPIException):
    """Delivery error."""
    def __init__(self, message: str = "Delivery error", **kwargs):
        super().__init__(message, status_code=500, **kwargs)


class ExternalServiceError(BaseAPIException):
    """External service error."""
    def __init__(self, message: str = "External service error", **kwargs):
        super().__init__(message, status_code=502, **kwargs)


class ServiceUnavailableError(BaseAPIException):
    """Service unavailable."""
    def __init__(self, message: str = "Service unavailable", **kwargs):
        super().__init__(message, status_code=503, **kwargs)

