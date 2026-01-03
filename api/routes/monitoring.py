# C:\work-spaces\lead-gen\lead-gen\api\routes\monitoring.py
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis

from api.core.config import settings
from api.core.exceptions import AuthenticationError, AuthorizationError
from api.core.logging import get_structlog_logger
from api.services.auth import get_current_user, require_role
from api.services.delivery_queue import delivery_queue
from api.services.redis import get_redis_client

logger = get_structlog_logger()

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# Pydantic Models
class MetricDataPoint(BaseModel):
    timestamp: datetime
    value: float
    labels: Optional[Dict[str, str]] = None


class MetricSeries(BaseModel):
    name: str
    data: List[MetricDataPoint]
    labels: Optional[Dict[str, str]] = None


class DeliveryMetrics(BaseModel):
    total_deliveries: int
    successful_deliveries: int
    failed_deliveries: int
    fallback_deliveries: int
    avg_delivery_time_ms: float
    success_rate: float
    by_channel: Dict[str, int]
    by_hour: Dict[str, int]


class QueueStats(BaseModel):
    queued: int
    processing: int
    dead_letter: int
    next_jobs: List[Dict]
    throughput_last_hour: int
    avg_processing_time_ms: Optional[float] = None


class SystemStats(BaseModel):
    memory_usage_mb: float
    cpu_percent: float
    active_connections: int
    request_rate: float
    error_rate: float
    uptime_days: float


# Metrics Collection Functions
async def collect_delivery_metrics(
    redis_client: Redis,
    time_range_hours: int = 24
) -> DeliveryMetrics:
    """Collect delivery metrics from Redis."""
    try:
        pipeline = redis_client.pipeline()
        
        # Get today's metrics
        today_key = f"metrics:delivery:{datetime.utcnow().strftime('%Y%m%d')}"
        
        # Get metrics for specified time range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(hours=time_range_hours)
        
        metrics_keys = []
        current_date = start_date
        
        while current_date <= end_date:
            metrics_keys.append(f"metrics:delivery:{current_date.strftime('%Y%m%d')}")
            current_date += timedelta(days=1)
        
        # Fetch all metrics
        for key in metrics_keys:
            pipeline.hgetall(key)
        
        results = await pipeline.execute()
        
        # Aggregate metrics
        total_deliveries = 0
        successful_deliveries = 0
        failed_deliveries = 0
        fallback_deliveries = 0
        total_delivery_time_ms = 0
        delivery_time_count = 0
        by_channel = {}
        by_hour = {}
        
        for result in results:
            if not result:
                continue
            
            total_deliveries += int(result.get(b"total_deliveries", 0))
            successful_deliveries += int(result.get(b"successful_deliveries", 0))
            failed_deliveries += int(result.get(b"failed_deliveries", 0))
            fallback_deliveries += int(result.get(b"fallback_deliveries", 0))
            
            delivery_time = result.get(b"total_delivery_time_ms")
            if delivery_time:
                total_delivery_time_ms += float(delivery_time)
                delivery_time_count += 1
            
            # Aggregate by channel
            for key, value in result.items():
                key_str = key.decode()
                if key_str.startswith("channel_"):
                    channel = key_str[8:]  # Remove "channel_" prefix
                    by_channel[channel] = by_channel.get(channel, 0) + int(value)
                
                # Aggregate by hour
                if key_str.startswith("hour_"):
                    hour = key_str[5:]  # Remove "hour_" prefix
                    by_hour[hour] = by_hour.get(hour, 0) + int(value)
        
        # Calculate averages
        avg_delivery_time_ms = (
            total_delivery_time_ms / delivery_time_count
            if delivery_time_count > 0 else 0
        )
        
        success_rate = (
            (successful_deliveries / total_deliveries * 100)
            if total_deliveries > 0 else 0
        )
        
        return DeliveryMetrics(
            total_deliveries=total_deliveries,
            successful_deliveries=successful_deliveries,
            failed_deliveries=failed_deliveries,
            fallback_deliveries=fallback_deliveries,
            avg_delivery_time_ms=avg_delivery_time_ms,
            success_rate=success_rate,
            by_channel=by_channel,
            by_hour=by_hour,
        )
        
    except Exception as e:
        logger.error("metrics.collection_error", error=str(e))
        return DeliveryMetrics(
            total_deliveries=0,
            successful_deliveries=0,
            failed_deliveries=0,
            fallback_deliveries=0,
            avg_delivery_time_ms=0,
            success_rate=0,
            by_channel={},
            by_hour={},
        )


async def get_system_stats() -> SystemStats:
    """Get system statistics."""
    try:
        import psutil
        
        process = psutil.Process()
        memory_usage = process.memory_info().rss / 1024 / 1024  # MB
        cpu_percent = process.cpu_percent(interval=0.1)
        
        # Get database connections (estimate)
        active_connections = len(psutil.net_connections())
        
        # Calculate request rate (simplified - in production use metrics)
        request_rate = 0.0
        error_rate = 0.0
        
        # Calculate uptime
        uptime_seconds = time.time() - process.create_time()
        uptime_days = uptime_seconds / 86400
        
        return SystemStats(
            memory_usage_mb=memory_usage,
            cpu_percent=cpu_percent,
            active_connections=active_connections,
            request_rate=request_rate,
            error_rate=error_rate,
            uptime_days=uptime_days,
        )
        
    except Exception as e:
        logger.error("system.stats_error", error=str(e))
        return SystemStats(
            memory_usage_mb=0,
            cpu_percent=0,
            active_connections=0,
            request_rate=0,
            error_rate=0,
            uptime_days=0,
        )


# Routes
@router.get("/metrics/delivery", response_model=DeliveryMetrics)
async def get_delivery_metrics(
    time_range_hours: int = Query(24, ge=1, le=168),  # 1 hour to 7 days
    redis_client: Redis = Depends(get_redis_client),
    current_user: Dict = Depends(get_current_user),
):
    """Get delivery performance metrics."""
    await require_role(current_user, ["admin", "manager"])
    
    metrics = await collect_delivery_metrics(redis_client, time_range_hours)
    
    logger.info(
        "metrics.delivery.retrieved",
        user_id=current_user.get("id"),
        time_range_hours=time_range_hours,
        total_deliveries=metrics.total_deliveries,
    )
    
    return metrics


async def get_queue_stats_internal(redis_client: Redis) -> QueueStats:
    """Internal function to get queue stats (extracted from route handler)."""
    try:
        if delivery_queue is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Delivery queue not initialized",
            )
        
        # Get queue stats
        stats = await delivery_queue.get_queue_stats()
        
        # Calculate throughput for last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        throughput_key = f"queue:throughput:{one_hour_ago.strftime('%Y%m%d%H')}"
        throughput = await redis_client.get(throughput_key)
        
        # Calculate average processing time (simplified)
        processing_times_key = "queue:processing_times"
        processing_times = await redis_client.lrange(processing_times_key, 0, 99)
        
        avg_processing_time = None
        if processing_times:
            times = [float(t) for t in processing_times if t]
            if times:
                avg_processing_time = sum(times) / len(times)
        
        return QueueStats(
            queued=stats.get("queued", 0),
            processing=stats.get("processing", 0),
            dead_letter=stats.get("dead_letter", 0),
            next_jobs=stats.get("next_jobs", []),
            throughput_last_hour=int(throughput) if throughput else 0,
            avg_processing_time_ms=avg_processing_time,
        )
        
    except Exception as e:
        logger.error("metrics.queue.error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get queue metrics: {str(e)}",
        )


@router.get("/metrics/queue", response_model=QueueStats)
async def get_queue_metrics(
    redis_client: Redis = Depends(get_redis_client),
    current_user: Dict = Depends(get_current_user),
):
    """Get delivery queue statistics."""
    await require_role(current_user, ["admin", "manager"])
    
    return await get_queue_stats_internal(redis_client)


async def get_active_alerts_internal(redis_client: Redis) -> Dict:
    """Internal function to get active alerts (extracted from route handler)."""
    try:
        alerts_key = "monitoring:alerts:active"
        alerts = await redis_client.lrange(alerts_key, 0, 49)  # Last 50 alerts
        
        parsed_alerts = []
        for alert_json in alerts:
            try:
                alert = json.loads(alert_json)
                parsed_alerts.append(alert)
            except json.JSONDecodeError:
                continue
        
        # Sort by severity and timestamp
        parsed_alerts.sort(key=lambda x: (
            {"critical": 0, "warning": 1, "info": 2}.get(x.get("severity", "info"), 3),
            -x.get("timestamp", 0)
        ))
        
        return {
            "total": len(parsed_alerts),
            "critical": sum(1 for a in parsed_alerts if a.get("severity") == "critical"),
            "warning": sum(1 for a in parsed_alerts if a.get("severity") == "warning"),
            "alerts": parsed_alerts,
        }
        
    except Exception as e:
        logger.error("alerts.retrieval_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get alerts: {str(e)}",
        )


@router.get("/alerts")
async def get_active_alerts(
    redis_client: Redis = Depends(get_redis_client),
    current_user: Dict = Depends(get_current_user),
):
    """Get active system alerts."""
    await require_role(current_user, ["admin", "manager"])
    
    return await get_active_alerts_internal(redis_client)


@router.get("/metrics/system", response_model=SystemStats)
async def get_system_metrics(current_user: Dict = Depends(get_current_user)):
    """Get system performance metrics."""
    await require_role(current_user, ["admin"])
    
    stats = await get_system_stats()
    
    logger.info(
        "metrics.system.retrieved",
        user_id=current_user.get("id"),
        memory_usage=stats.memory_usage_mb,
        cpu_percent=stats.cpu_percent,
    )
    
    return stats


@router.get("/metrics/custom/{metric_name}")
async def get_custom_metric(
    metric_name: str,
    start_time: datetime = Query(None, description="Start time for metric range"),
    end_time: datetime = Query(None, description="End time for metric range"),
    resolution: str = Query("1h", regex="^(1m|5m|15m|1h|6h|1d)$"),
    redis_client: Redis = Depends(get_redis_client),
    current_user: Dict = Depends(get_current_user),
):
    """Get custom metrics with time range and resolution."""
    await require_role(current_user, ["admin"])
    
    try:
        if not start_time:
            start_time = datetime.utcnow() - timedelta(hours=24)
        if not end_time:
            end_time = datetime.utcnow()
        
        # Determine time buckets based on resolution
        resolution_seconds = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "6h": 21600,
            "1d": 86400,
        }[resolution]
        
        # Generate bucket keys
        bucket_keys = []
        current = start_time.replace(second=0, microsecond=0)
        
        while current <= end_time:
            bucket_key = f"metrics:{metric_name}:{current.strftime('%Y%m%d%H%M')}"
            bucket_keys.append(bucket_key)
            current += timedelta(seconds=resolution_seconds)
        
        # Fetch metrics from Redis
        pipeline = redis_client.pipeline()
        for key in bucket_keys:
            pipeline.get(key)
        
        results = await pipeline.execute()
        
        # Format response
        data_points = []
        for key, value in zip(bucket_keys, results):
            if value:
                timestamp_str = key.split(":")[-1]
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d%H%M")
                
                data_points.append(MetricDataPoint(
                    timestamp=timestamp,
                    value=float(value),
                ))
        
        return MetricSeries(
            name=metric_name,
            data=data_points,
            labels={"resolution": resolution},
        )
        
    except Exception as e:
        logger.error("metrics.custom.error", metric_name=metric_name, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metric {metric_name}: {str(e)}",
        )


@router.post("/alerts/acknowledge/{alert_id}")
async def acknowledge_alert(
    alert_id: str,
    redis_client: Redis = Depends(get_redis_client),
    current_user: Dict = Depends(get_current_user),
):
    """Acknowledge an active alert."""
    await require_role(current_user, ["admin", "manager"])
    
    try:
        # Move alert from active to acknowledged
        active_key = "monitoring:alerts:active"
        ack_key = "monitoring:alerts:acknowledged"
        
        # Find and move the alert
        alerts = await redis_client.lrange(active_key, 0, -1)
        
        for alert_json in alerts:
            alert = json.loads(alert_json)
            if alert.get("id") == alert_id:
                # Update alert with acknowledgement info
                alert["acknowledged_at"] = datetime.utcnow().isoformat()
                alert["acknowledged_by"] = current_user.get("id")
                alert["acknowledged_by_name"] = current_user.get("email", "unknown")
                
                # Remove from active, add to acknowledged
                pipeline = redis_client.pipeline()
                pipeline.lrem(active_key, 1, alert_json)
                pipeline.lpush(ack_key, json.dumps(alert))
                pipeline.ltrim(ack_key, 0, 999)  # Keep last 1000
                
                await pipeline.execute()
                
                logger.info(
                    "alert.acknowledged",
                    alert_id=alert_id,
                    user_id=current_user.get("id"),
                    alert_type=alert.get("type"),
                )
                
                return {"status": "acknowledged", "alert_id": alert_id}
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found",
        )
        
    except Exception as e:
        logger.error("alert.acknowledge_error", alert_id=alert_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to acknowledge alert: {str(e)}",
        )


@router.get("/dashboard")
async def get_monitoring_dashboard(
    redis_client: Redis = Depends(get_redis_client),
    current_user: Dict = Depends(get_current_user),
):
    """Get comprehensive monitoring dashboard data."""
    await require_role(current_user, ["admin", "manager"])
    
    try:
        # Collect all metrics concurrently
        delivery_task = asyncio.create_task(collect_delivery_metrics(redis_client))
        queue_task = asyncio.create_task(get_queue_stats_internal(redis_client))
        system_task = asyncio.create_task(get_system_stats())
        alerts_task = asyncio.create_task(get_active_alerts_internal(redis_client))
        
        delivery_metrics = await delivery_task
        queue_stats = await queue_task
        system_stats = await system_task
        alerts = await alerts_task
        
        # Get recent leads activity
        leads_key = "monitoring:recent_leads"
        recent_leads = await redis_client.lrange(leads_key, 0, 9)
        
        parsed_leads = []
        for lead_json in recent_leads:
            try:
                parsed_leads.append(json.loads(lead_json))
            except json.JSONDecodeError:
                continue
        
        # Calculate KPIs
        success_rate = delivery_metrics.success_rate
        avg_delivery_time = delivery_metrics.avg_delivery_time_ms
        
        # Determine system health
        system_health = "healthy"
        if system_stats.cpu_percent > 80:
            system_health = "warning"
        if system_stats.cpu_percent > 95 or system_stats.memory_usage_mb > 1024:
            system_health = "critical"
        
        # Determine queue health
        queue_health = "healthy"
        if queue_stats.queued > 1000:
            queue_health = "warning"
        if queue_stats.queued > 5000 or queue_stats.dead_letter > 100:
            queue_health = "critical"
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "health": {
                "system": system_health,
                "queue": queue_health,
                "database": "healthy",  # Would check actual DB
                "redis": "healthy",  # Would check actual Redis
            },
            "kpis": {
                "success_rate": success_rate,
                "avg_delivery_time_ms": avg_delivery_time,
                "queue_size": queue_stats.queued,
                "throughput_last_hour": queue_stats.throughput_last_hour,
                "active_alerts": alerts.get("total", 0),
            },
            "metrics": {
                "delivery": delivery_metrics.dict(),
                "queue": queue_stats.dict(),
                "system": system_stats.dict(),
            },
            "recent_leads": parsed_leads,
            "alerts_summary": alerts,
        }
        
    except Exception as e:
        logger.error("dashboard.error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dashboard: {str(e)}",
        )

