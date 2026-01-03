# C:\work-spaces\lead-gen\lead-gen\api\middleware\request_id.py
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from api.core.logging import set_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to generate and set request IDs."""
    
    async def dispatch(self, request: Request, call_next):
        # Get request ID from headers or generate one
        request_id = self._get_or_create_request_id(request)
        
        # Set request ID in context
        set_request_id(request_id)
        
        # Process request
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        
        return response
    
    def _get_or_create_request_id(self, request: Request) -> str:
        """Extract request ID from headers or generate new one."""
        # Check for existing request ID in headers
        request_id = request.headers.get("X-Request-ID")
        if request_id:
            return request_id
        
        # Check for correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        if correlation_id:
            return correlation_id
        
        # Check for trace ID (OpenTelemetry)
        trace_id = request.headers.get("traceparent")
        if trace_id:
            # Extract trace ID from W3C Trace Context format
            if trace_id.startswith("00-") and len(trace_id) >= 35:
                return trace_id[3:35]  # Extract 32-char trace ID
        
        # Generate new request ID
        return str(uuid.uuid4())