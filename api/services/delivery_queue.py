# C:\work-spaces\lead-gen\lead-gen\api\services\delivery_queue.py
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import aiohttp
from redis.asyncio import Redis

from api.core.config import settings
from api.core.exceptions import DeliveryError
from api.core.logging import get_structlog_logger

logger = get_structlog_logger()


class DeliveryStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"


class DeliveryChannel(Enum):
    WEBHOOK = "webhook"
    EMAIL = "email"
    SMS = "sms"
    API_PUSH = "api_push"


@dataclass
class DeliveryAttempt:
    attempt_number: int
    timestamp: datetime
    channel: DeliveryChannel
    status: str
    response_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data["channel"] = self.channel.value
        return data


@dataclass
class DeliveryResult:
    lead_id: int
    buyer_id: int
    success: bool
    final_status: DeliveryStatus
    total_attempts: int
    attempts: List[DeliveryAttempt]
    first_attempt: Optional[datetime] = None
    last_attempt: Optional[datetime] = None
    delivery_time_ms: Optional[float] = None
    used_fallback: bool = False
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        
        if self.attempts:
            self.first_attempt = self.attempts[0].timestamp
            self.last_attempt = self.attempts[-1].timestamp
            if self.success and self.first_attempt and self.last_attempt:
                self.delivery_time_ms = (
                    self.last_attempt - self.first_attempt
                ).total_seconds() * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data["final_status"] = self.final_status.value
        data["attempts"] = [attempt.to_dict() for attempt in self.attempts]
        return data


class DeliveryQueue:
    """Enhanced delivery queue with Redis backend and monitoring."""
    
    def __init__(
        self,
        redis_client: Redis,
        queue_name: str = "delivery_queue",
        max_concurrent: int = None,
        max_retries: int = None,
        retry_delays: List[int] = None,
    ):
        self.redis = redis_client
        self.queue_name = queue_name
        self.processing_set = f"{queue_name}:processing"
        self.dead_letter_queue = f"{queue_name}:dead_letter"
        self.metrics_prefix = f"metrics:{queue_name}"
        
        # Configuration
        self.max_concurrent = max_concurrent or settings.delivery_queue_max_concurrent
        self.max_retries = max_retries or settings.delivery_queue_max_retries
        self.retry_delays = retry_delays or settings.retry_delays()
        
        # Semaphore for concurrency control
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Delivery channel configurations
        self.channel_configs = {
            DeliveryChannel.WEBHOOK: {
                "priority": 1,
                "timeout": settings.webhook_timeout_seconds,
                "max_attempts": settings.webhook_max_retries,
            },
            DeliveryChannel.EMAIL: {
                "priority": 2,
                "timeout": 30,
                "max_attempts": 3,
            },
            DeliveryChannel.SMS: {
                "priority": 3,
                "timeout": 10,
                "max_attempts": 2,
            },
            DeliveryChannel.API_PUSH: {
                "priority": 1,
                "timeout": 5,
                "max_attempts": 3,
            },
        }
        
        # Monitoring
        self.processing_times_key = f"{self.metrics_prefix}:processing_times"
        
        logger.info(
            "delivery_queue.initialized",
            queue_name=queue_name,
            max_concurrent=self.max_concurrent,
            max_retries=self.max_retries,
        )
    
    async def enqueue_delivery(
        self,
        lead_id: int,
        priority: int = 1,
        delay_seconds: int = 0,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """Add a lead delivery job to the queue."""
        job_id = f"delivery:{lead_id}:{uuid4().hex[:8]}"
        
        job_data = {
            "job_id": job_id,
            "lead_id": lead_id,
            "enqueued_at": datetime.utcnow().isoformat(),
            "priority": priority,
            "attempts": 0,
            "last_attempt": None,
            "next_retry": None,
            "status": DeliveryStatus.QUEUED.value,
            "metadata": metadata or {},
        }
        
        try:
            # Calculate score for sorted set (priority + delay)
            base_score = float(priority)
            if delay_seconds > 0:
                score = time.time() + delay_seconds
            else:
                score = base_score
            
            # Add to Redis sorted set
            added = await self.redis.zadd(
                self.queue_name,
                {json.dumps(job_data): score},
                nx=True,
            )
            
            if added > 0:
                # Record metrics
                await self._record_enqueue_metrics()
                
                logger.info(
                    "delivery.enqueued",
                    job_id=job_id,
                    lead_id=lead_id,
                    priority=priority,
                    delay_seconds=delay_seconds,
                )
                
                # Start processing if not already running
                asyncio.create_task(self._process_queue())
                
                return True
            else:
                logger.warning(
                    "delivery.already_queued",
                    lead_id=lead_id,
                )
                return False
                
        except Exception as e:
            logger.error(
                "delivery.enqueue_error",
                lead_id=lead_id,
                error=str(e),
            )
            return False
    
    async def _process_queue(self):
        """Process delivery jobs from the queue."""
        logger.info("delivery_queue.processor_started")
        
        while True:
            try:
                # Get next job with highest priority (lowest score)
                jobs = await self.redis.zrange(
                    self.queue_name,
                    0,
                    0,
                    withscores=True,
                )
                
                if not jobs:
                    await asyncio.sleep(1)
                    continue
                
                job_json, score = jobs[0]
                job_data = json.loads(job_json)
                
                # Check if job is scheduled for future
                if score > time.time():
                    await asyncio.sleep(min(1, score - time.time()))
                    continue
                
                # Move to processing set
                moved = await self._move_to_processing(job_data)
                if not moved:
                    await asyncio.sleep(0.1)
                    continue
                
                # Process job with concurrency control
                async with self.semaphore:
                    await self._process_job(job_data)
                    
            except asyncio.CancelledError:
                logger.info("delivery_queue.processor_stopped")
                break
            except Exception as e:
                logger.error(
                    "delivery_queue.processor_error",
                    error=str(e),
                    traceback=True,
                )
                await asyncio.sleep(5)
    
    async def _move_to_processing(self, job_data: Dict) -> bool:
        """Move job from main queue to processing set atomically."""
        job_json = json.dumps(job_data)
        
        async with self.redis.pipeline(transaction=True) as pipe:
            # Watch the job
            pipe.zrem(self.queue_name, job_json)
            pipe.zadd(self.processing_set, {job_json: time.time()})
            pipe.expire(self.processing_set, 300)  # 5 minute TTL
            
            results = await pipe.execute()
            
            return bool(results[0])  # True if removed from main queue
    
    async def _process_job(self, job_data: Dict):
        """Process a single delivery job."""
        job_id = job_data["job_id"]
        lead_id = job_data["lead_id"]
        attempts = job_data.get("attempts", 0)
        
        try:
            logger.info(
                "delivery.processing_started",
                job_id=job_id,
                lead_id=lead_id,
                attempt=attempts + 1,
            )
            
            start_time = time.time()
            
            # Get database session
            from api.db.session import get_session
            
            async with get_session() as session:
                # Load lead and buyer details
                lead_info = await self._load_delivery_data(session, lead_id)
                
                if not lead_info:
                    logger.error(
                        "delivery.data_not_found",
                        lead_id=lead_id,
                    )
                    await self._mark_job_failed(job_id, "lead_data_not_found")
                    return
                
                # Determine delivery channel
                channel = self._select_delivery_channel(lead_info)
                
                # Execute delivery
                result = await self._execute_delivery(
                    session, lead_info, channel, attempts + 1
                )
                
                # Update lead status based on result
                await self._update_lead_delivery(session, lead_id, result)
                
                # Handle job completion
                if result.success:
                    await self._complete_job(job_id, result)
                elif attempts + 1 < self.max_retries:
                    # Schedule retry
                    delay = self.retry_delays[min(attempts, len(self.retry_delays) - 1)]
                    await self._schedule_retry(job_id, job_data, delay, result)
                else:
                    # Move to dead letter queue
                    await self._move_to_dead_letter(job_id, job_data, result)
                
            # Record processing time
            processing_time = time.time() - start_time
            await self._record_processing_time(processing_time)
            
            # Remove from processing set
            await self.redis.zrem(self.processing_set, json.dumps(job_data))
            
            logger.info(
                "delivery.processing_completed",
                job_id=job_id,
                lead_id=lead_id,
                success=result.success,
                processing_time_ms=processing_time * 1000,
            )
            
        except Exception as e:
            logger.error(
                "delivery.job_processing_error",
                job_id=job_id,
                lead_id=lead_id,
                error=str(e),
                traceback=True,
            )
            
            # Clean up processing set on error
            await self.redis.zrem(self.processing_set, json.dumps(job_data))
            
            # Schedule retry if not exceeded max attempts
            if attempts + 1 < self.max_retries:
                delay = self.retry_delays[min(attempts, len(self.retry_delays) - 1)]
                await self._enqueue_retry(job_id, job_data, delay)
            else:
                await self._move_to_dead_letter(job_id, job_data, None)
    
    async def _load_delivery_data(self, session, lead_id: int) -> Optional[Dict]:
        """Load all data needed for delivery."""
        from sqlalchemy import text
        
        query = text("""
            SELECT 
                l.id as lead_id,
                l.name, l.email, l.phone, l.postal_code, l.city,
                l.message, l.created_at, l.source, l.status,
                l.buyer_id, l.offer_id, l.market_id, l.vertical_id,
                b.name as buyer_name,
                b.email as buyer_email,
                b.phone as buyer_phone,
                b.webhook_url,
                b.webhook_secret,
                b.email_notifications,
                b.sms_notifications,
                bo.webhook_url_override,
                bo.webhook_secret_override,
                bo.email_override,
                bo.sms_override,
                o.name as offer_name,
                m.name as market_name,
                v.name as vertical_name
            FROM leads l
            JOIN buyers b ON b.id = l.buyer_id
            LEFT JOIN buyer_offers bo ON bo.buyer_id = b.id AND bo.offer_id = l.offer_id
            JOIN offers o ON o.id = l.offer_id
            JOIN markets m ON m.id = l.market_id
            JOIN verticals v ON v.id = l.vertical_id
            WHERE l.id = :lead_id
            AND l.deleted_at IS NULL
        """)
        
        result = await session.execute(query, {"lead_id": lead_id})
        row = result.mappings().first()
        
        return dict(row) if row else None
    
    def _select_delivery_channel(self, lead_info: Dict) -> DeliveryChannel:
        """Select the best delivery channel for this lead."""
        # Check for webhook URL (override first, then default)
        webhook_url = (
            lead_info.get("webhook_url_override") or 
            lead_info.get("webhook_url")
        )
        
        if webhook_url:
            return DeliveryChannel.WEBHOOK
        
        # Check email preferences
        if lead_info.get("email_notifications"):
            buyer_email = lead_info.get("email_override") or lead_info.get("buyer_email")
            if buyer_email:
                return DeliveryChannel.EMAIL
        
        # Check SMS preferences
        if lead_info.get("sms_notifications"):
            buyer_phone = lead_info.get("sms_override") or lead_info.get("buyer_phone")
            if buyer_phone:
                return DeliveryChannel.SMS
        
        # Default to webhook if URL exists, otherwise email
        if lead_info.get("webhook_url"):
            return DeliveryChannel.WEBHOOK
        
        return DeliveryChannel.EMAIL
    
    async def _execute_delivery(
        self,
        session,
        lead_info: Dict,
        channel: DeliveryChannel,
        attempt_number: int
    ) -> DeliveryResult:
        """Execute delivery through the selected channel."""
        attempts = []
        
        # Try primary channel first
        primary_result = await self._deliver_via_channel(
            lead_info, channel, attempt_number
        )
        attempts.append(primary_result)
        
        if primary_result.status == "success":
            return DeliveryResult(
                lead_id=lead_info["lead_id"],
                buyer_id=lead_info["buyer_id"],
                success=True,
                final_status=DeliveryStatus.DELIVERED,
                total_attempts=1,
                attempts=attempts,
            )
        
        # If primary fails, try fallback channels
        fallback_channels = self._get_fallback_channels(channel)
        used_fallback = False
        
        for fallback_channel in fallback_channels:
            if attempt_number <= self.max_retries:
                fallback_result = await self._deliver_via_channel(
                    lead_info, fallback_channel, attempt_number
                )
                attempts.append(fallback_result)
                
                if fallback_result.status == "success":
                    used_fallback = True
                    break
        
        success = any(attempt.status == "success" for attempt in attempts)
        final_status = DeliveryStatus.DELIVERED if success else DeliveryStatus.FAILED
        
        return DeliveryResult(
            lead_id=lead_info["lead_id"],
            buyer_id=lead_info["buyer_id"],
            success=success,
            final_status=final_status,
            total_attempts=len(attempts),
            attempts=attempts,
            used_fallback=used_fallback,
        )
    
    async def _deliver_via_channel(
        self,
        lead_info: Dict,
        channel: DeliveryChannel,
        attempt_number: int
    ) -> DeliveryAttempt:
        """Deliver lead via specific channel."""
        start_time = datetime.utcnow()
        config = self.channel_configs.get(channel, {})
        
        try:
            if channel == DeliveryChannel.WEBHOOK:
                result = await self._deliver_webhook(lead_info, config)
            elif channel == DeliveryChannel.EMAIL:
                result = await self._deliver_email(lead_info, config)
            elif channel == DeliveryChannel.SMS:
                result = await self._deliver_sms(lead_info, config)
            elif channel == DeliveryChannel.API_PUSH:
                result = await self._deliver_api_push(lead_info, config)
            else:
                raise DeliveryError(
                    message=f"Unsupported delivery channel: {channel}",
                    details={"channel": channel.value},
                )
            
            response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return DeliveryAttempt(
                attempt_number=attempt_number,
                timestamp=start_time,
                channel=channel,
                status="success" if result.get("success") else "failed",
                response_code=result.get("status_code"),
                response_time_ms=response_time,
                error_message=result.get("error"),
                metadata=result.get("metadata", {}),
            )
            
        except Exception as e:
            response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return DeliveryAttempt(
                attempt_number=attempt_number,
                timestamp=start_time,
                channel=channel,
                status="error",
                response_time_ms=response_time,
                error_message=str(e)[:200],
            )
    
    async def _deliver_webhook(self, lead_info: Dict, config: Dict) -> Dict:
        """Deliver lead via webhook."""
        webhook_url = (
            lead_info.get("webhook_url_override") or 
            lead_info.get("webhook_url")
        )
        
        if not webhook_url:
            return {"success": False, "error": "No webhook URL configured"}
        
        # Prepare payload
        payload = {
            "event": "lead.delivered",
            "data": {
                "lead_id": lead_info["lead_id"],
                "received_at": lead_info["created_at"].isoformat() if lead_info.get("created_at") else None,
                "delivered_at": datetime.utcnow().isoformat(),
                "contact": {
                    "name": lead_info["name"],
                    "phone": lead_info["phone"],
                    "email": lead_info["email"],
                    "postal_code": lead_info["postal_code"],
                    "city": lead_info.get("city"),
                },
                "details": {
                    "message": lead_info.get("message"),
                    "source": lead_info.get("source"),
                    "status": lead_info.get("status"),
                },
                "metadata": {
                    "offer_id": lead_info["offer_id"],
                    "market_id": lead_info["market_id"],
                    "vertical_id": lead_info["vertical_id"],
                    "offer_name": lead_info.get("offer_name"),
                    "market_name": lead_info.get("market_name"),
                    "vertical_name": lead_info.get("vertical_name"),
                },
            },
        }
        
        # Generate signature if secret is available
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LeadGen-Delivery/2.0",
            "X-LeadGen-Delivery-Id": str(uuid4()),
            "X-LeadGen-Event": "lead.delivered",
            "X-LeadGen-Timestamp": datetime.utcnow().isoformat(),
        }
        
        webhook_secret = (
            lead_info.get("webhook_secret_override") or 
            lead_info.get("webhook_secret")
        )
        
        if webhook_secret:
            import hmac
            import hashlib
            
            payload_str = json.dumps(payload, sort_keys=True)
            signature = hmac.new(
                webhook_secret.encode(),
                payload_str.encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"
        
        timeout = aiohttp.ClientTimeout(total=config.get("timeout", 5))
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    headers=headers
                ) as response:
                    
                    response_data = await response.text()
                    
                    # Consider 2xx status codes as success
                    success = 200 <= response.status < 300
                    
                    return {
                        "success": success,
                        "status_code": response.status,
                        "response": response_data[:500] if response_data else None,
                        "metadata": {
                            "webhook_url": webhook_url,
                            "payload_size": len(json.dumps(payload)),
                            "channel": "webhook",
                        },
                    }
                    
        except asyncio.TimeoutError:
            return {"success": False, "error": "Webhook timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _deliver_email(self, lead_info: Dict, config: Dict) -> Dict:
        """Deliver lead via email."""
        buyer_email = lead_info.get("email_override") or lead_info.get("buyer_email")
        
        if not buyer_email:
            return {"success": False, "error": "No buyer email available"}
        
        # In production, integrate with email service (SendGrid, AWS SES, etc.)
        # For now, simulate successful delivery
        await asyncio.sleep(0.1)  # Simulate network delay
        
        return {
            "success": True,
            "status_code": 200,
            "metadata": {
                "to_email": buyer_email,
                "channel": "email",
                "simulated": True,
            },
        }
    
    async def _deliver_sms(self, lead_info: Dict, config: Dict) -> Dict:
        """Deliver lead via SMS."""
        buyer_phone = lead_info.get("sms_override") or lead_info.get("buyer_phone")
        
        if not buyer_phone:
            return {"success": False, "error": "No buyer phone available"}
        
        # In production, integrate with SMS service (Twilio, etc.)
        # For now, simulate successful delivery
        await asyncio.sleep(0.1)
        
        return {
            "success": True,
            "status_code": 200,
            "metadata": {
                "to_phone": buyer_phone,
                "channel": "sms",
                "simulated": True,
            },
        }
    
    async def _deliver_api_push(self, lead_info: Dict, config: Dict) -> Dict:
        """Deliver lead via API push (for internal systems)."""
        # This would push to internal APIs or message queues
        await asyncio.sleep(0.05)
        
        return {
            "success": True,
            "status_code": 200,
            "metadata": {
                "channel": "api_push",
                "simulated": True,
            },
        }
    
    def _get_fallback_channels(self, primary: DeliveryChannel) -> List[DeliveryChannel]:
        """Get fallback channels for a failed primary channel."""
        fallback_map = {
            DeliveryChannel.WEBHOOK: [DeliveryChannel.EMAIL, DeliveryChannel.SMS],
            DeliveryChannel.EMAIL: [DeliveryChannel.SMS, DeliveryChannel.WEBHOOK],
            DeliveryChannel.SMS: [DeliveryChannel.EMAIL, DeliveryChannel.WEBHOOK],
            DeliveryChannel.API_PUSH: [DeliveryChannel.WEBHOOK, DeliveryChannel.EMAIL],
        }
        
        return fallback_map.get(primary, [])
    
    async def _update_lead_delivery(self, session, lead_id: int, result: DeliveryResult):
        """Update lead with delivery result and trigger billing if successful."""
        from sqlalchemy import text
        
        if result.success:
            status = "delivered"
            delivered_at = result.last_attempt or datetime.utcnow()
        else:
            status = "rejected"  # Use "rejected" instead of "delivery_failed" to match enum
            delivered_at = None
        
        # Use idempotency guard: only update if status is 'validated' (prevents double-delivery)
        query = text("""
            UPDATE leads 
            SET 
                status = :status,
                delivered_at = :delivered_at,
                updated_at = NOW(),
                delivery_attempts = :attempts,
                delivery_result = :result_json
            WHERE id = :lead_id
              AND status = 'validated'
            RETURNING buyer_id
        """)
        
        result_exec = await session.execute(query, {
            "lead_id": lead_id,
            "status": status,
            "delivered_at": delivered_at,
            "attempts": result.total_attempts,
            "result_json": json.dumps(result.to_dict()),
        })
        
        row = result_exec.fetchone()
        await session.commit()
        
        # If delivery succeeded and lead was updated, bill the buyer
        # Use a new session for billing to ensure transaction isolation
        if result.success and row and row[0]:
            buyer_id = row[0]
            try:
                from api.services.billing import bill_lead
                from api.db.session import get_session
                
                # Get a new session for billing
                async with get_session() as billing_session:
                    billing_success = await bill_lead(billing_session, lead_id, buyer_id)
                    if not billing_success:
                        logger.warning(
                            "delivery.billing_failed",
                            lead_id=lead_id,
                            buyer_id=buyer_id,
                        )
            except Exception as e:
                # Don't fail delivery if billing fails - log and continue
                logger.error(
                    "delivery.billing_error",
                    lead_id=lead_id,
                    buyer_id=buyer_id,
                    error=str(e),
                )
    
    async def _complete_job(self, job_id: str, result: DeliveryResult):
        """Mark job as completed successfully."""
        # Record delivery metrics
        await self._record_delivery_metrics(result)
        
        logger.info(
            "delivery.completed",
            job_id=job_id,
            lead_id=result.lead_id,
            attempts=result.total_attempts,
            delivery_time_ms=result.delivery_time_ms,
        )
    
    async def _schedule_retry(
        self,
        job_id: str,
        job_data: Dict,
        delay_seconds: int,
        result: DeliveryResult
    ):
        """Schedule a retry for failed delivery."""
        job_data["attempts"] = job_data.get("attempts", 0) + 1
        job_data["last_attempt"] = datetime.utcnow().isoformat()
        job_data["next_retry"] = (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat()
        job_data["status"] = DeliveryStatus.RETRYING.value
        
        # Add back to queue with delay
        score = time.time() + delay_seconds
        
        await self.redis.zadd(
            self.queue_name,
            {json.dumps(job_data): score}
        )
        
        logger.info(
            "delivery.scheduled_retry",
            job_id=job_id,
            lead_id=result.lead_id,
            attempt=job_data["attempts"],
            delay_seconds=delay_seconds,
        )
    
    async def _enqueue_retry(self, job_id: str, job_data: Dict, delay_seconds: int):
        """Enqueue a retry without result data."""
        job_data["attempts"] = job_data.get("attempts", 0) + 1
        job_data["last_attempt"] = datetime.utcnow().isoformat()
        job_data["next_retry"] = (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat()
        job_data["status"] = DeliveryStatus.RETRYING.value
        
        score = time.time() + delay_seconds
        
        await self.redis.zadd(
            self.queue_name,
            {json.dumps(job_data): score}
        )
    
    async def _move_to_dead_letter(
        self,
        job_id: str,
        job_data: Dict,
        result: Optional[DeliveryResult]
    ):
        """Move failed job to dead letter queue."""
        job_data["status"] = DeliveryStatus.DEAD_LETTER.value
        job_data["failed_at"] = datetime.utcnow().isoformat()
        
        if result:
            job_data["result"] = {
                "success": result.success,
                "final_status": result.final_status.value,
                "total_attempts": result.total_attempts,
            }
        
        # Add to dead letter queue with expiration
        retention_days = settings.delivery_queue_dead_letter_retention_days
        
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.lpush(self.dead_letter_queue, json.dumps(job_data))
            pipe.expire(self.dead_letter_queue, retention_days * 24 * 3600)
            await pipe.execute()
        
        logger.error(
            "delivery.dead_letter",
            job_id=job_id,
            lead_id=job_data.get("lead_id"),
            attempts=job_data.get("attempts", 0),
        )
    
    async def _mark_job_failed(self, job_id: str, reason: str):
        """Mark job as failed without retry."""
        await self.redis.zrem(self.processing_set, job_id)
        
        logger.error(
            "delivery.job_failed",
            job_id=job_id,
            reason=reason,
        )
    
    async def _record_enqueue_metrics(self):
        """Record metrics for enqueued jobs."""
        hour_key = f"{self.metrics_prefix}:enqueued:{datetime.utcnow().strftime('%Y%m%d%H')}"
        
        pipeline = self.redis.pipeline()
        pipeline.incr(hour_key)
        pipeline.expire(hour_key, 3600 * 24)  # Keep for 24 hours
        
        await pipeline.execute()
    
    async def _record_processing_time(self, processing_time: float):
        """Record processing time for monitoring."""
        await self.redis.lpush(self.processing_times_key, processing_time)
        await self.redis.ltrim(self.processing_times_key, 0, 99)  # Keep last 100
    
    async def _record_delivery_metrics(self, result: DeliveryResult):
        """Record delivery performance metrics."""
        try:
            date_key = f"metrics:delivery:{datetime.utcnow().strftime('%Y%m%d')}"
            hour_key = f"metrics:delivery:{datetime.utcnow().strftime('%Y%m%d%H')}"
            
            pipeline = self.redis.pipeline()
            
            # Increment daily counters
            pipeline.hincrby(date_key, "total_deliveries", 1)
            
            if result.success:
                pipeline.hincrby(date_key, "successful_deliveries", 1)
                if result.delivery_time_ms:
                    pipeline.hincrbyfloat(date_key, "total_delivery_time_ms", result.delivery_time_ms)
            else:
                pipeline.hincrby(date_key, "failed_deliveries", 1)
            
            if result.used_fallback:
                pipeline.hincrby(date_key, "fallback_deliveries", 1)
            
            # Record channel usage
            if result.attempts:
                primary_channel = result.attempts[0].channel.value
                pipeline.hincrby(date_key, f"channel_{primary_channel}", 1)
                pipeline.hincrby(hour_key, f"channel_{primary_channel}", 1)
            
            # Record attempts distribution
            pipeline.hincrby(date_key, f"attempts_{result.total_attempts}", 1)
            
            # Set expiry (30 days for daily, 7 days for hourly)
            pipeline.expire(date_key, 30 * 24 * 3600)
            pipeline.expire(hour_key, 7 * 24 * 3600)
            
            await pipeline.execute()
            
        except Exception as e:
            logger.warning("delivery.metrics_error", error=str(e))
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get delivery queue statistics."""
        try:
            pipeline = self.redis.pipeline()
            
            # Queue sizes
            pipeline.zcard(self.queue_name)
            pipeline.zcard(self.processing_set)
            pipeline.llen(self.dead_letter_queue)
            
            # Next jobs
            pipeline.zrange(self.queue_name, 0, 9, withscores=True)
            
            results = await pipeline.execute()
            
            return {
                "queued": results[0] or 0,
                "processing": results[1] or 0,
                "dead_letter": results[2] or 0,
                "next_jobs": [
                    {"data": json.loads(job), "score": score}
                    for job, score in results[3]
                ] if results[3] else [],
            }
            
        except Exception as e:
            logger.error("delivery.stats_error", error=str(e))
            return {}
    
    async def retry_dead_letter(self, limit: int = 100) -> int:
        """Retry jobs from dead letter queue."""
        retried = 0
        
        for _ in range(limit):
            job_json = await self.redis.rpop(self.dead_letter_queue)
            
            if not job_json:
                break
            
            try:
                job_data = json.loads(job_json)
                job_data["attempts"] = 0
                job_data["status"] = DeliveryStatus.QUEUED.value
                job_data.pop("failed_at", None)
                job_data.pop("result", None)
                
                # Add back to main queue with high priority
                await self.redis.zadd(
                    self.queue_name,
                    {json.dumps(job_data): 0.5}  # Higher priority
                )
                
                retried += 1
                logger.info(
                    "delivery.dead_letter_retry",
                    job_id=job_data.get("job_id"),
                    lead_id=job_data.get("lead_id"),
                )
                
            except Exception as e:
                logger.error(
                    "delivery.dead_letter_retry_error",
                    error=str(e),
                )
                # Put back in dead letter queue
                await self.redis.rpush(self.dead_letter_queue, job_json)
        
        return retried
    
    async def purge_queue(self, older_than_hours: int = 24) -> int:
        """Purge old jobs from queue."""
        cutoff_score = time.time() - (older_than_hours * 3600)
        
        # Find jobs older than cutoff
        old_jobs = await self.redis.zrangebyscore(
            self.queue_name,
            min=0,
            max=cutoff_score,
        )
        
        if not old_jobs:
            return 0
        
        # Remove old jobs
        removed = await self.redis.zrem(
            self.queue_name,
            *old_jobs
        )
        
        logger.warning(
            "delivery.queue_purged",
            count=removed,
            older_than_hours=older_than_hours,
        )
        
        return removed


# Global delivery queue instance
delivery_queue: Optional[DeliveryQueue] = None


def init_delivery_queue(redis_client: Redis, **kwargs) -> DeliveryQueue:
    """Initialize global delivery queue instance."""
    global delivery_queue
    
    if delivery_queue is None:
        delivery_queue = DeliveryQueue(redis_client, **kwargs)
    
    return delivery_queue


async def get_delivery_queue() -> DeliveryQueue:
    """Get global delivery queue instance."""
    global delivery_queue
    
    if delivery_queue is None:
        from api.services.redis import get_redis_client
        redis_client = await get_redis_client()
        delivery_queue = DeliveryQueue(redis_client)
    
    return delivery_queue