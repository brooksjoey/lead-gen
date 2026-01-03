# health.py
# C:\work-spaces\lead-gen\lead-gen\api\routes\health.py
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.logging import get_structlog_logger
from api.db.session import get_session

logger = get_structlog_logger()

router = APIRouter(tags=["health"])


class HealthCheckResponse(BaseModel):
    status: str
    service: str
    environment: str
    version: str
    timestamp: str
    uptime: float
    checks: Dict[str, Dict[str, str]]
    dependencies: List[str]


async def check_database(session: AsyncSession) -> Dict[str, str]:
    """Check database connectivity."""
    try:
        start_time = datetime.utcnow()
        # Simple database check
        from sqlalchemy import text
        result = await session.execute(text("SELECT version()"))
        row = result.fetchone()
        db_version = row[0] if row else "unknown"
        response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return {
            "status": "healthy",
            "response_time_ms": f"{response_time:.2f}",
            "database": "postgresql",
            "version": db_version.split()[0] if db_version != "unknown" else "unknown",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


async def check_redis() -> Dict[str, str]:
    """Check Redis connectivity."""
    try:
        start_time = datetime.utcnow()
        # Try to import and use redis if available
        try:
            from api.services.redis import get_redis_client, health_check as redis_health_check
            result = await redis_health_check()
            response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if result.get("status") == "healthy":
                return {
                    "status": "healthy",
                    "response_time_ms": f"{response_time:.2f}",
                    "version": result.get("version", "unknown"),
                    "used_memory": result.get("memory", {}).get("used_memory_human", "unknown"),
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": result.get("error", "Unknown error"),
                    "response_time_ms": f"{response_time:.2f}",
                }
        except ImportError:
            return {
                "status": "unavailable",
                "error": "Redis service not configured",
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


async def check_external_services() -> Dict[str, Dict[str, str]]:
    """Check external service dependencies."""
    checks = {}
    
    # Check Sentry (if configured)
    sentry_dsn = getattr(settings, "sentry_dsn", None)
    if sentry_dsn:
        try:
            import sentry_sdk
            checks["sentry"] = {
                "status": "healthy" if sentry_sdk.Hub.current.client else "unhealthy",
                "dsn_configured": "true",
            }
        except Exception as e:
            checks["sentry"] = {
                "status": "unhealthy",
                "error": str(e),
            }
    
    # Check webhook delivery service (simulated)
    checks["webhook_service"] = {
        "status": "healthy",  # In production, make actual HTTP request
        "timeout_seconds": str(settings.webhook_timeout_seconds),
        "max_retries": str(settings.webhook_max_retries),
    }
    
    return checks


@router.get("/health", response_model=HealthCheckResponse, status_code=status.HTTP_200_OK)
async def health_check(session: AsyncSession = Depends(get_session)):
    """Comprehensive health check endpoint."""
    start_time = datetime.utcnow()
    
    # Run all health checks concurrently
    db_check_task = asyncio.create_task(check_database(session))
    redis_check_task = asyncio.create_task(check_redis())
    external_check_task = asyncio.create_task(check_external_services())
    
    # Wait for all checks to complete
    db_result = await db_check_task
    redis_result = await redis_check_task
    external_results = await external_check_task
    
    # Determine overall status
    all_checks = {
        "database": db_result,
        "redis": redis_result,
        **external_results,
    }
    
    overall_status = "healthy"
    for service, result in all_checks.items():
        if result.get("status") != "healthy":
            overall_status = "degraded"
            if service in ["database", "redis"]:  # Critical services
                overall_status = "unhealthy"
                break
    
    # Get system information
    import psutil
    process = psutil.Process()
    uptime_seconds = time.time() - process.create_time()
    
    # Build dependencies list (filter out None values)
    dependencies_list = [
        "postgresql",
        "redis",
        "prometheus",
    ]
    sentry_dsn = getattr(settings, "sentry_dsn", None)
    if sentry_dsn:
        dependencies_list.append("sentry")
    
    response = HealthCheckResponse(
        status=overall_status,
        service="leadgen_api",
        environment=settings.environment,
        version="2.0.0",
        timestamp=datetime.utcnow().isoformat() + "Z",
        uptime=uptime_seconds,
        checks=all_checks,
        dependencies=dependencies_list,
    )
    
    # Log health check
    if overall_status == "healthy":
        logger.info(
            "health.check",
            status=overall_status,
            response_time_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
            checks=all_checks,
        )
    else:
        logger.warning(
            "health.check",
            status=overall_status,
            response_time_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
            checks=all_checks,
        )
    
    return response


@router.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness_probe():
    """Simple liveness probe for Kubernetes/containers."""
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/health/ready", status_code=status.HTTP_200_OK)
async def readiness_probe(session: AsyncSession = Depends(get_session)):
    """Readiness probe that checks critical dependencies."""
    checks = {}
    
    # Check database
    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
    
    # Check Redis
    try:
        from api.services.redis import health_check as redis_health_check
        redis_result = await redis_health_check()
        checks["redis"] = redis_result.get("status", "unknown")
    except (ImportError, Exception) as e:
        checks["redis"] = f"error: {str(e)}"
    
    # Determine if ready
    is_ready = all(
        status == "healthy"
        for service, status in checks.items()
        if isinstance(status, str) and "healthy" in status
    )
    
    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return {
        "status": "ready" if is_ready else "not_ready",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": checks,
    }


@router.get("/health/metrics")
async def health_metrics():
    """Return health metrics in Prometheus format."""
    import psutil
    
    process = psutil.Process()
    memory_info = process.memory_info()
    
    metrics = [
        "# HELP api_health_status API health status (1=healthy, 0=unhealthy)",
        "# TYPE api_health_status gauge",
        f"api_health_status{{service=\"leadgen_api\",environment=\"{settings.environment}\"}} 1",
        "",
        "# HELP api_memory_usage_bytes Memory usage in bytes",
        "# TYPE api_memory_usage_bytes gauge",
        f"api_memory_usage_bytes{{service=\"leadgen_api\"}} {memory_info.rss}",
        "",
        "# HELP api_cpu_percent CPU usage percentage",
        "# TYPE api_cpu_percent gauge",
        f"api_cpu_percent{{service=\"leadgen_api\"}} {process.cpu_percent()}",
        "",
        "# HELP api_thread_count Number of threads",
        "# TYPE api_thread_count gauge",
        f"api_thread_count{{service=\"leadgen_api\"}} {process.num_threads()}",
        "",
        "# HELP api_uptime_seconds Service uptime in seconds",
        "# TYPE api_uptime_seconds gauge",
        f"api_uptime_seconds{{service=\"leadgen_api\"}} {time.time() - process.create_time()}",
    ]
    
    return Response(content="\n".join(metrics), media_type="text/plain")

