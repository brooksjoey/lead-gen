# C:\work-spaces\lead-gen\lead-gen\api\main.py
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Dict, Any

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from api.core.config import settings
from api.core.exceptions import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    BaseAPIException,
    BusinessRuleError,
    ConflictError,
    DatabaseError,
    DeliveryError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from api.core.logging import configure_structlog, get_structlog_logger, set_request_id
from api.db.session import engine
from api.middleware.auth import AuthMiddleware
from api.middleware.logging import LoggingMiddleware
from api.middleware.rate_limiter import RateLimitingMiddleware
from api.middleware.request_id import RequestIdMiddleware
from api.routes import buyers, leads, health, monitoring, webhooks
from api.services.delivery_queue import init_delivery_queue
from api.services.redis import init_redis_pool, get_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    logger = get_structlog_logger(__name__)
    
    # Startup
    logger.info("application.starting", environment=settings.environment)
    
    # Initialize Redis
    try:
        await init_redis_pool()
        logger.info("redis.connected", url=settings.redis_url)
    except Exception as e:
        logger.error("redis.connection_failed", error=str(e))
        if settings.is_production:
            raise
    
    # Initialize delivery queue
    try:
        redis_client = await get_redis_client()
        init_delivery_queue(redis_client)
        logger.info("delivery_queue.initialized")
    except Exception as e:
        logger.error("delivery_queue.init_failed", error=str(e))
    
    # Initialize Sentry if DSN is provided
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            integrations=[
                AsyncioIntegration(),
                FastApiIntegration(),
                StarletteIntegration(),
            ],
            traces_sample_rate=1.0 if settings.is_development else 0.1,
            send_default_pii=False,
        )
        logger.info("sentry.initialized")
    
    logger.info("application.started")
    yield
    
    # Shutdown
    logger.info("application.shutting_down")
    
    # Close Redis connection
    from api.services.redis import close_redis_pool
    await close_redis_pool()
    logger.info("redis.connection_closed")
    
    # Close database engine
    await engine.dispose()
    logger.info("database.connection_closed")
    
    logger.info("application.shutdown_complete")


# Configure logging before creating app
configure_structlog()
logger = get_structlog_logger(__name__)

# Create FastAPI application
app = FastAPI(
    title="LeadGen API",
    version="2.0.0",
    description="High-performance lead generation and delivery API",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    openapi_url="/openapi.json" if settings.is_development else None,
    lifespan=lifespan,
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins(),
    allow_credentials=True,
    allow_methods=settings.methods(),
    allow_headers=settings.allowed_headers.split(","),
    expose_headers=["X-Request-ID", "X-Response-Time"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"] if settings.is_development else ["api.leadgen.com", "*.leadgen.com"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthMiddleware)

if not settings.is_development:
    app.add_middleware(RateLimitingMiddleware)

# Exception handlers
@app.exception_handler(BaseAPIException)
async def api_exception_handler(request: Request, exc: BaseAPIException):
    """Handle custom API exceptions."""
    logger.warning(
        "api.exception",
        status_code=exc.status_code,
        code=exc.detail.get("code", "unknown"),
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors."""
    errors = []
    for error in exc.errors():
        errors.append({
            "loc": error.get("loc", []),
            "msg": error.get("msg", "Validation error"),
            "type": error.get("type", "value_error"),
        })
    
    logger.warning(
        "validation.error",
        path=request.url.path,
        method=request.method,
        errors=errors,
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=APIError(
            code="validation_error",
            message="Request validation failed",
            details={"errors": errors},
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    error_id = f"err_{int(time.time())}_{hash(str(exc)) % 10000:04d}"
    set_request_id(error_id)
    
    logger.error(
        "unhandled.exception",
        error_id=error_id,
        error_type=type(exc).__name__,
        error=str(exc),
        path=request.url.path,
        method=request.method,
        traceback=True,
    )
    
    # In development, show full error details
    if settings.is_development:
        detail = APIError(
            code="internal_error",
            message=f"Internal server error: {str(exc)}",
            details={"error_id": error_id, "traceback": str(exc.__traceback__)},
        ).model_dump()
    else:
        detail = APIError(
            code="internal_error",
            message="Internal server error",
            details={"error_id": error_id},
        ).model_dump()
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=detail,
        headers={"X-Error-ID": error_id},
    )


# Include routers
app.include_router(health.router, prefix=settings.api_prefix, tags=["health"])
app.include_router(leads.router, prefix=settings.api_prefix, tags=["leads"])
app.include_router(buyers.router, prefix=settings.api_prefix, tags=["buyers"])
app.include_router(webhooks.router, prefix=settings.api_prefix, tags=["webhooks"])
app.include_router(monitoring.router, prefix=settings.api_prefix, tags=["monitoring"])

# Add Prometheus metrics
if not settings.is_testing:
    instrumentator = Instrumentator().instrument(app)
    
    @app.on_event("startup")
    async def startup_event():
        instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "LeadGen API",
        "version": app.version,
        "environment": settings.environment,
        "docs": "/docs" if settings.is_development else None,
        "health": "/api/health",
        "openapi": "/openapi.json" if settings.is_development else None,
    }


logger.info("application.configured", environment=settings.environment)