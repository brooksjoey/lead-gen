# logging.py
# C:\work-spaces\lead-gen\lead-gen\api\middleware\logging.py
from __future__ import annotations

import time
from typing import Dict, Optional

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from api.core.config import settings
from api.core.logging import get_structlog_logger, set_request_id

logger = get_structlog_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request/response logging."""
    
    async def dispatch(self, request: Request, call_next):
        # Start timer
        start_time = time.time()
        
        # Get request ID from headers or generate one
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = request.headers.get("X-Correlation-ID")
        
        # Set request ID in context
        set_request_id(request_id)
        
        # Log request
        await self._log_request(request, request_id)
        
        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log exception
            await self._log_exception(request, e, start_time, request_id)
            raise
        
        # Calculate response time
        response_time = time.time() - start_time
        
        # Add response headers
        response.headers["X-Request-ID"] = request_id or "N/A"
        response.headers["X-Response-Time"] = f"{response_time:.3f}"
        
        # Log response
        await self._log_response(request, response, response_time, request_id)
        
        return response
    
    async def _log_request(self, request: Request, request_id: Optional[str]):
        """Log incoming request."""
        try:
            # Skip logging for certain paths
            if request.url.path in ["/health", "/metrics"]:
                return
            
            # Get client IP
            client_ip = request.client.host if request.client else "unknown"
            
            # Get user agent
            user_agent = request.headers.get("user-agent", "unknown")
            
            # Get content length
            content_length = request.headers.get("content-length", "0")
            
            logger.info(
                "request.received",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                query_params=dict(request.query_params) if request.query_params else None,
                client_ip=client_ip,
                user_agent=user_agent,
                content_length=content_length,
                headers=self._filter_headers(request.headers),
            )
            
        except Exception as e:
            logger.error("request.logging_error", error=str(e))
    
    async def _log_response(
        self,
        request: Request,
        response: Response,
        response_time: float,
        request_id: Optional[str],
    ):
        """Log outgoing response."""
        try:
            # Skip logging for certain paths
            if request.url.path in ["/health", "/metrics"]:
                return
            
            # Get response size
            response_size = response.headers.get("content-length", "0")
            
            # Determine log level based on status code
            status_code = response.status_code
            log_level = "warning" if status_code >= 400 else "info"
            
            log_data = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "response_time_ms": response_time * 1000,
                "response_size": response_size,
            }
            
            # Add error details for client errors
            if 400 <= status_code < 500:
                log_data["error_type"] = "client_error"
            # Add error details for server errors
            elif status_code >= 500:
                log_data["error_type"] = "server_error"
            
            # Log at appropriate level
            if log_level == "warning":
                logger.warning("response.sent", **log_data)
            else:
                logger.info("response.sent", **log_data)
            
        except Exception as e:
            logger.error("response.logging_error", error=str(e))
    
    async def _log_exception(
        self,
        request: Request,
        exception: Exception,
        start_time: float,
        request_id: Optional[str],
    ):
        """Log unhandled exception."""
        try:
            response_time = time.time() - start_time
            
            logger.error(
                "request.exception",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                response_time_ms=response_time * 1000,
                exception_type=type(exception).__name__,
                exception_message=str(exception),
                traceback=True,
            )
            
        except Exception as e:
            logger.error("exception.logging_error", error=str(e))
    
    def _filter_headers(self, headers: Dict) -> Dict:
        """Filter sensitive headers from logs."""
        sensitive_headers = [
            "authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
            "x-secret",
            "password",
            "token",
            "secret",
        ]
        
        filtered = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in sensitive_headers):
                filtered[key] = "[REDACTED]"
            else:
                filtered[key] = value
        
        return filtered

