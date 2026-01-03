# C:\work-spaces\lead-gen\lead-gen\api\routes\webhooks.py
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from api.core.config import settings
from api.core.exceptions import AuthenticationError, ValidationError
from api.core.logging import get_structlog_logger
from api.services.auth import get_current_user, require_role

logger = get_structlog_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# Pydantic Models
class WebhookEvent(BaseModel):
    event: str = Field(..., description="Event type")
    data: Dict = Field(..., description="Event data")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_id: Optional[str] = Field(None, description="Unique event identifier")
    metadata: Optional[Dict] = Field(default_factory=dict)


class WebhookDelivery(BaseModel):
    id: str
    event: str
    url: str
    status: str
    status_code: Optional[int]
    response_time_ms: Optional[float]
    error_message: Optional[str]
    attempt: int
    delivered_at: datetime
    payload: Optional[Dict] = None


class WebhookResponse(BaseModel):
    success: bool
    message: str
    event_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Webhook Handlers
class WebhookManager:
    """Manager for webhook operations."""
    
    @staticmethod
    def verify_signature(
        payload: bytes,
        signature: str,
        secret: str
    ) -> bool:
        """Verify webhook signature."""
        if not signature or not secret:
            return False
        
        # Handle different signature formats
        if signature.startswith("sha256="):
            signature = signature[7:]
        
        # Calculate expected signature
        expected_signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    @staticmethod
    def generate_signature(payload: bytes, secret: str) -> str:
        """Generate webhook signature."""
        signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return f"sha256={signature}"
    
    @staticmethod
    async def validate_payload(payload: Dict) -> List[str]:
        """Validate webhook payload structure."""
        errors = []
        
        if "event" not in payload:
            errors.append("Missing required field: event")
        
        if "data" not in payload:
            errors.append("Missing required field: data")
        
        # Validate event type
        if "event" in payload:
            valid_events = [
                "lead.delivered",
                "lead.failed",
                "lead.duplicate",
                "buyer.created",
                "buyer.updated",
                "offer.assigned",
                "system.alert",
            ]
            
            if payload["event"] not in valid_events:
                errors.append(f"Invalid event type: {payload['event']}")
        
        return errors


# Background Tasks
async def process_webhook_delivery(
    event: WebhookEvent,
    url: str,
    secret: Optional[str] = None,
    retry_count: int = 0
):
    """Process webhook delivery in background."""
    import aiohttp
    
    logger = get_structlog_logger(__name__)
    
    try:
        # Prepare payload
        payload = event.dict()
        payload_str = json.dumps(payload, separators=(",", ":"))
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LeadGen-Webhooks/1.0",
            "X-Webhook-Event": event.event,
            "X-Webhook-Timestamp": event.timestamp.isoformat(),
            "X-Webhook-ID": event.event_id or "",
        }
        
        # Add signature if secret is provided
        if secret:
            signature = WebhookManager.generate_signature(
                payload_str.encode(),
                secret
            )
            headers["X-Webhook-Signature"] = signature
        
        # Make request
        timeout = aiohttp.ClientTimeout(total=settings.webhook_timeout_seconds)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                data=payload_str,
                headers=headers
            ) as response:
                
                response_text = await response.text()
                
                # Log delivery
                logger.info(
                    "webhook.delivered",
                    event=event.event,
                    url=url,
                    status_code=response.status,
                    response_time=response.elapsed.total_seconds() * 1000,
                    success=200 <= response.status < 300,
                )
                
                return {
                    "success": 200 <= response.status < 300,
                    "status_code": response.status,
                    "response": response_text[:500],
                }
                
    except Exception as e:
        logger.error(
            "webhook.delivery_failed",
            event=event.event,
            url=url,
            error=str(e),
            retry_count=retry_count,
        )
        
        # Schedule retry if not exceeded max retries
        if retry_count < settings.webhook_max_retries:
            import asyncio
            await asyncio.sleep(settings.webhook_retry_delay_seconds * (retry_count + 1))
            
            return await process_webhook_delivery(
                event, url, secret, retry_count + 1
            )
        
        return {
            "success": False,
            "error": str(e),
            "retries_exhausted": True,
        }


# Routes
@router.post("/receive", response_model=WebhookResponse)
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_signature: Optional[str] = Header(None),
    x_webhook_secret: Optional[str] = Header(None),
):
    """Receive inbound webhook from external services."""
    try:
        # Read request body
        body = await request.body()
        
        # Parse payload
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValidationError(
                message="Invalid JSON payload",
                details={"error": str(e)},
            )
        
        # Validate payload
        errors = await WebhookManager.validate_payload(payload)
        if errors:
            raise ValidationError(
                message="Webhook payload validation failed",
                details={"errors": errors},
            )
        
        # Verify signature if provided
        if x_webhook_signature and x_webhook_secret:
            if not WebhookManager.verify_signature(
                body,
                x_webhook_signature,
                x_webhook_secret
            ):
                raise AuthenticationError(
                    message="Invalid webhook signature",
                    details={"signature": x_webhook_signature[:50] + "..."},
                )
        
        # Create event object
        event = WebhookEvent(**payload)
        if not event.event_id:
            import uuid
            event.event_id = str(uuid.uuid4())
        
        # Log received webhook
        logger.info(
            "webhook.received",
            event=event.event,
            event_id=event.event_id,
            source_ip=request.client.host if request.client else "unknown",
            has_signature=bool(x_webhook_signature),
        )
        
        # Process webhook based on event type
        background_tasks.add_task(
            process_webhook_event,
            event,
            request.headers,
        )
        
        return WebhookResponse(
            success=True,
            message="Webhook received and queued for processing",
            event_id=event.event_id,
        )
        
    except Exception as e:
        logger.error(
            "webhook.receive_error",
            error=str(e),
            headers=dict(request.headers),
        )
        raise


@router.post("/send", response_model=WebhookResponse)
async def send_webhook(
    webhook_event: WebhookEvent,
    background_tasks: BackgroundTasks,
    url: HttpUrl,
    secret: Optional[str] = None,
    current_user: Dict = Depends(get_current_user),
):
    """Send an outbound webhook."""
    await require_role(current_user, ["admin", "manager"])
    
    try:
        # Generate event ID if not provided
        if not webhook_event.event_id:
            import uuid
            webhook_event.event_id = str(uuid.uuid4())
        
        # Queue webhook delivery
        background_tasks.add_task(
            process_webhook_delivery,
            webhook_event,
            str(url),
            secret,
        )
        
        logger.info(
            "webhook.sent",
            event=webhook_event.event,
            event_id=webhook_event.event_id,
            url=str(url),
            user_id=current_user.get("id"),
        )
        
        return WebhookResponse(
            success=True,
            message="Webhook queued for delivery",
            event_id=webhook_event.event_id,
        )
        
    except Exception as e:
        logger.error(
            "webhook.send_error",
            event=webhook_event.event,
            error=str(e),
            user_id=current_user.get("id"),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send webhook: {str(e)}",
        )


@router.get("/test/{buyer_id}")
async def test_webhook(
    buyer_id: int,
    current_user: Dict = Depends(get_current_user),
):
    """Test webhook configuration for a buyer."""
    await require_role(current_user, ["admin", "manager"])
    
    try:
        # Get buyer webhook configuration
        from sqlalchemy import select
        from api.db.session import get_session
        from api.db.models.buyer import Buyer
        
        async with get_session() as session:
            stmt = select(Buyer).where(
                Buyer.id == buyer_id,
                Buyer.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            buyer = result.scalar_one_or_none()
            
            if not buyer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Buyer {buyer_id} not found",
                )
            
            # Create test event
            test_event = WebhookEvent(
                event="lead.delivered",
                data={
                    "test": True,
                    "buyer_id": buyer_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "message": "Test webhook from LeadGen API",
                },
                metadata={
                    "test": True,
                    "initiated_by": current_user.get("id"),
                }
            )
            
            # Test webhook delivery
            if buyer.webhook_url:
                import aiohttp
                
                try:
                    timeout = aiohttp.ClientTimeout(total=5)
                    
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(
                            str(buyer.webhook_url),
                            json=test_event.dict(),
                            headers={
                                "Content-Type": "application/json",
                                "X-Test-Webhook": "true",
                            }
                        ) as response:
                            
                            return {
                                "success": 200 <= response.status < 300,
                                "buyer_id": buyer_id,
                                "webhook_url": str(buyer.webhook_url),
                                "status_code": response.status,
                                "response": await response.text()[:200],
                                "event": test_event.dict(),
                            }
                            
                except Exception as e:
                    return {
                        "success": False,
                        "buyer_id": buyer_id,
                        "webhook_url": str(buyer.webhook_url),
                        "error": str(e),
                    }
            else:
                return {
                    "success": False,
                    "buyer_id": buyer_id,
                    "message": "Buyer has no webhook URL configured",
                }
                
    except Exception as e:
        logger.error(
            "webhook.test_error",
            buyer_id=buyer_id,
            error=str(e),
            user_id=current_user.get("id"),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook test failed: {str(e)}",
        )


@router.get("/deliveries", response_model=List[WebhookDelivery])
async def get_webhook_deliveries(
    event: Optional[str] = None,
    status: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 100,
    current_user: Dict = Depends(get_current_user),
):
    """Get webhook delivery history."""
    await require_role(current_user, ["admin", "manager"])
    
    try:
        # In production, this would query a database
        # For now, return empty list
        return []
        
    except Exception as e:
        logger.error("webhook.deliveries_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get webhook deliveries: {str(e)}",
        )


# Event Processing
async def process_webhook_event(
    event: WebhookEvent,
    headers: Dict,
):
    """Process received webhook event."""
    logger = get_structlog_logger(__name__)
    
    try:
        # Store event for auditing
        await store_webhook_event(event, headers)
        
        # Process based on event type
        if event.event == "lead.delivered":
            await process_lead_delivered(event.data)
        elif event.event == "lead.failed":
            await process_lead_failed(event.data)
        elif event.event == "system.alert":
            await process_system_alert(event.data)
        # Add more event handlers as needed
        
        logger.info(
            "webhook.event_processed",
            event=event.event,
            event_id=event.event_id,
        )
        
    except Exception as e:
        logger.error(
            "webhook.event_processing_error",
            event=event.event,
            event_id=event.event_id,
            error=str(e),
        )


async def store_webhook_event(event: WebhookEvent, headers: Dict):
    """Store webhook event for auditing."""
    # In production, store in database
    # For now, just log
    logger = get_structlog_logger(__name__)
    
    logger.info(
        "webhook.event_stored",
        event=event.event,
        event_id=event.event_id,
        timestamp=event.timestamp.isoformat(),
        source_ip=headers.get("x-forwarded-for", headers.get("x-real-ip", "unknown")),
    )


async def process_lead_delivered(data: Dict):
    """Process lead delivered event."""
    # Update lead status, send notifications, etc.
    logger = get_structlog_logger(__name__)
    logger.info("webhook.lead_delivered_processed", lead_id=data.get("lead_id"))


async def process_lead_failed(data: Dict):
    """Process lead failed event."""
    # Trigger alerts, update dashboards, etc.
    logger = get_structlog_logger(__name__)
    logger.warning("webhook.lead_failed_processed", lead_id=data.get("lead_id"))


async def process_system_alert(data: Dict):
    """Process system alert event."""
    # Send notifications, update monitoring, etc.
    logger = get_structlog_logger(__name__)
    logger.error("webhook.system_alert_processed", alert=data.get("alert"))