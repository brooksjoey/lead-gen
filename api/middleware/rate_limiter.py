# C:\work-spaces\lead-gen\lead-gen\api\middleware\rate_limiter.py
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.core.config import settings
from api.core.exceptions import RateLimitError
from api.core.logging import get_structlog_logger
from api.services.redis import get_redis_client

logger = get_structlog_logger()


class RateLimitingMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Redis."""
    
    def __init__(self, app):
        super().__init__(app)
        self.redis = None
        self.rate_limit_requests = settings.rate_limit_requests
        self.rate_limit_period = settings.rate_limit_period
        
        # Exempt paths from rate limiting
        self.exempt_paths = [
            "/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
    
    async def dispatch(self, request: Request, call_next):
        # Check if path is exempt
        if request.url.path in self.exempt_paths:
            return await call_next(request)
        
        # Get client identifier
        client_id = self._get_client_id(request)
        
        # Check rate limit
        allowed, remaining, reset_time = await self._check_rate_limit(client_id, request)
        
        if not allowed:
            retry_after = reset_time - int(time.time())
            logger.warning(
                "rate_limit.exceeded",
                client_id=client_id,
                path=request.url.path,
                method=request.method,
                retry_after=retry_after,
            )
            
            raise RateLimitError(
                message="Rate limit exceeded",
                retry_after=retry_after,
                details={
                    "limit": self.rate_limit_requests,
                    "period": self.rate_limit_period,
                    "retry_after": retry_after,
                }
            )
        
        # Add rate limit headers
        response = await call_next(request)
        
        response.headers["X-RateLimit-Limit"] = str(self.rate_limit_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_time)
        response.headers["X-RateLimit-Reset-After"] = str(reset_time - int(time.time()))
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        """Get unique client identifier."""
        # Try API key first
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"apikey:{api_key}"
        
        # Try user token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Remove "Bearer " prefix
            return f"token:{token}"
        
        # Fall back to IP address
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        
        if forwarded_for:
            # Use the first IP in X-Forwarded-For
            client_ip = forwarded_for.split(",")[0].strip()
        
        return f"ip:{client_ip}"
    
    async def _check_rate_limit(
        self,
        client_id: str,
        request: Request
    ) -> Tuple[bool, int, int]:
        """Check if client has exceeded rate limit."""
        if not self.redis:
            self.redis = await get_redis_client()
        
        # Create Redis key
        key = f"ratelimit:{client_id}:{int(time.time() // self.rate_limit_period)}"
        
        try:
            # Use Redis pipeline for atomic operations
            async with self.redis.pipeline(transaction=True) as pipe:
                # Increment counter and set expiry
                pipe.incr(key)
                pipe.expire(key, self.rate_limit_period)
                
                results = await pipe.execute()
                current_count = results[0]
            
            # Calculate remaining requests and reset time
            remaining = max(0, self.rate_limit_requests - current_count)
            reset_time = int((time.time() // self.rate_limit_period + 1) * self.rate_limit_period)
            
            # Check if limit exceeded
            allowed = current_count <= self.rate_limit_requests
            
            # Log rate limit usage for monitoring
            if current_count % 10 == 0:  # Log every 10 requests
                logger.debug(
                    "rate_limit.usage",
                    client_id=client_id[:50],  # Truncate for logging
                    current_count=current_count,
                    remaining=remaining,
                    path=request.url.path,
                )
            
            return allowed, remaining, reset_time
            
        except Exception as e:
            logger.error("rate_limit.error", error=str(e), client_id=client_id[:50])
            # Allow requests if Redis fails (fail-open)
            return True, self.rate_limit_requests, int(time.time() + self.rate_limit_period)
    
    async def get_rate_limit_stats(self, client_id: str) -> Dict:
        """Get rate limit statistics for a client."""
        if not self.redis:
            self.redis = await get_redis_client()
        
        current_time = int(time.time())
        current_window = current_time // self.rate_limit_period
        key = f"ratelimit:{client_id}:{current_window}"
        
        try:
            count = await self.redis.get(key)
            current_count = int(count) if count else 0
            
            return {
                "client_id": client_id,
                "current_count": current_count,
                "limit": self.rate_limit_requests,
                "remaining": max(0, self.rate_limit_requests - current_count),
                "window_start": current_window * self.rate_limit_period,
                "window_end": (current_window + 1) * self.rate_limit_period,
                "reset_in": ((current_window + 1) * self.rate_limit_period) - current_time,
            }
            
        except Exception as e:
            logger.error("rate_limit.stats_error", error=str(e))
            return {"error": str(e)}