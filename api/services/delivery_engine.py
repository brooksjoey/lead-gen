from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DeliveryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DeliveryAttempt:
    attempt_number: int
    timestamp: datetime
    http_status: Optional[int]
    success: bool
    error_message: Optional[str]


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    attempts: list[DeliveryAttempt]
    final_status: str


# Retry schedule: Attempt 1 immediate, Attempt 2: 5s, Attempt 3: 15s
RETRY_DELAYS = [0, 5, 15]
MAX_RETRIES = 3


def generate_delivery_idempotency_key(lead_id: int, idempotency_key: Optional[str]) -> str:
    """
    Generate deterministic idempotency key for delivery.
    """
    if idempotency_key:
        return f"delivery:{lead_id}:{idempotency_key}"
    return f"delivery:{lead_id}"


def generate_webhook_signature(
    payload: str, secret: str
) -> str:
    """
    Generate HMAC-SHA256 signature for webhook payload.
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def format_delivery_payload(
    *,
    lead_id: int,
    name: str,
    email: str,
    phone: str,
    country_code: str,
    postal_code: str,
    city: Optional[str],
    region_code: Optional[str],
    message: Optional[str],
    idempotency_key: Optional[str],
    source: str,
    utm_source: Optional[str],
    utm_medium: Optional[str],
    utm_campaign: Optional[str],
) -> Dict[str, Any]:
    """
    Format lead data into delivery payload.
    """
    payload = {
        "lead_id": lead_id,
        "idempotency_key": generate_delivery_idempotency_key(lead_id, idempotency_key),
        "source": source,
        "contact": {
            "name": name,
            "email": email,
            "phone": phone,
        },
        "location": {
            "country_code": country_code,
            "postal_code": postal_code,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    if city:
        payload["location"]["city"] = city
    if region_code:
        payload["location"]["region_code"] = region_code
    if message:
        payload["message"] = message
    if utm_source:
        payload["attribution"] = {
            "utm_source": utm_source,
        }
        if utm_medium:
            payload["attribution"]["utm_medium"] = utm_medium
        if utm_campaign:
            payload["attribution"]["utm_campaign"] = utm_campaign

    return payload


async def deliver_via_webhook(
    *,
    url: str,
    secret: Optional[str],
    payload: Dict[str, Any],
    timeout: int = 10,
) -> tuple[bool, Optional[int], Optional[str]]:
    """
    Deliver lead via webhook POST.
    Returns (success, http_status, error_message).
    """
    payload_json = json.dumps(payload, sort_keys=True)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "LeadGen-Delivery/1.0",
    }

    if secret:
        signature = generate_webhook_signature(payload_json, secret)
        headers["X-Webhook-Signature"] = f"sha256={signature}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                status = response.status
                if 200 <= status < 300:
                    return (True, status, None)
                else:
                    error_text = await response.text()
                    return (False, status, f"HTTP {status}: {error_text[:200]}")
    except asyncio.TimeoutError:
        return (False, None, "Request timeout")
    except aiohttp.ClientError as e:
        return (False, None, f"Client error: {str(e)[:200]}")
    except Exception as e:
        return (False, None, f"Unexpected error: {str(e)[:200]}")


async def deliver_via_email(
    *,
    email: str,
    lead_data: Dict[str, Any],
) -> tuple[bool, Optional[str]]:
    """
    Deliver lead via email (fallback).
    Returns (success, error_message).
    """
    # Email delivery would use SMTP - for now, return success as placeholder
    # In production, would use configured SMTP settings
    return (True, None)


async def execute_delivery(
    *,
    session: AsyncSession,
    lead_id: int,
) -> DeliveryResult:
    """
    Execute delivery pipeline for a lead:
    1. Load lead and buyer delivery configuration
    2. Attempt webhook delivery with retries
    3. Fallback to email if webhook fails
    4. Record delivery attempts
    5. Update lead status on success (guarded)
    """
    # Load lead and buyer data
    lead_row = await session.execute(
        text(
            """
            SELECT
              l.id,
              l.buyer_id,
              l.status,
              l.name,
              l.email,
              l.phone,
              l.country_code,
              l.postal_code,
              l.city,
              l.region_code,
              l.message,
              l.idempotency_key,
              l.source,
              l.utm_source,
              l.utm_medium,
              l.utm_campaign,
              b.webhook_url,
              b.webhook_secret,
              b.email_notifications,
              b.email AS buyer_email,
              bo.webhook_url_override,
              bo.email_override
            FROM leads l
            JOIN buyers b ON b.id = l.buyer_id
            LEFT JOIN buyer_offers bo ON bo.buyer_id = l.buyer_id
              AND bo.offer_id = (SELECT offer_id FROM leads WHERE id = :lead_id)
            WHERE l.id = :lead_id
            """
        ),
        {"lead_id": lead_id},
    )
    lead_rec = lead_row.mappings().first()
    if not lead_rec:
        raise DeliveryError(
            code="lead_not_found",
            message=f"Lead with id={lead_id} not found",
        )

    if lead_rec["status"] == "delivered":
        # Already delivered, return success
        return DeliveryResult(
            success=True,
            attempts=[],
            final_status="delivered",
        )

    if not lead_rec["buyer_id"]:
        raise DeliveryError(
            code="no_buyer_assigned",
            message=f"Lead {lead_id} has no buyer_id assigned",
        )

    # Determine delivery channel
    webhook_url = lead_rec.get("webhook_url_override") or lead_rec.get("webhook_url")
    webhook_secret = lead_rec.get("webhook_secret")
    email_enabled = lead_rec.get("email_notifications", True)
    email_address = lead_rec.get("email_override") or lead_rec.get("buyer_email")

    # Format payload
    payload = format_delivery_payload(
        lead_id=int(lead_rec["id"]),
        name=str(lead_rec["name"]),
        email=str(lead_rec["email"]),
        phone=str(lead_rec["phone"]),
        country_code=str(lead_rec["country_code"]),
        postal_code=str(lead_rec["postal_code"]),
        city=lead_rec.get("city"),
        region_code=lead_rec.get("region_code"),
        message=lead_rec.get("message"),
        idempotency_key=lead_rec.get("idempotency_key"),
        source=str(lead_rec["source"]),
        utm_source=lead_rec.get("utm_source"),
        utm_medium=lead_rec.get("utm_medium"),
        utm_campaign=lead_rec.get("utm_campaign"),
    )

    attempts: list[DeliveryAttempt] = []

    # Attempt webhook delivery with retries
    if webhook_url:
        for attempt_num in range(1, MAX_RETRIES + 1):
            if attempt_num > 1:
                delay = RETRY_DELAYS[attempt_num - 1]
                await asyncio.sleep(delay)

            success, http_status, error_msg = await deliver_via_webhook(
                url=webhook_url,
                secret=webhook_secret,
                payload=payload,
                timeout=10,
            )

            attempts.append(
                DeliveryAttempt(
                    attempt_number=attempt_num,
                    timestamp=datetime.utcnow(),
                    http_status=http_status,
                    success=success,
                    error_message=error_msg,
                )
            )

            if success:
                # Webhook delivery succeeded
                # Update lead status (guarded)
                update_result = await session.execute(
                    text(
                        """
                        UPDATE leads
                        SET
                          status = 'delivered',
                          delivered_at = CURRENT_TIMESTAMP,
                          updated_at = CURRENT_TIMESTAMP
                        WHERE id = :lead_id
                          AND status != 'delivered'
                        RETURNING id
                        """
                    ),
                    {"lead_id": lead_id},
                )
                if update_result.mappings().first():
                    await session.commit()

                return DeliveryResult(
                    success=True,
                    attempts=attempts,
                    final_status="delivered",
                )

    # Webhook failed or not configured, try email fallback
    if email_enabled and email_address:
        email_success, email_error = await deliver_via_email(
            email=email_address,
            lead_data=payload,
        )

        attempts.append(
            DeliveryAttempt(
                attempt_number=len(attempts) + 1,
                timestamp=datetime.utcnow(),
                http_status=None,
                success=email_success,
                error_message=email_error,
            )
        )

        if email_success:
            # Email delivery succeeded
            update_result = await session.execute(
                text(
                    """
                    UPDATE leads
                    SET
                      status = 'delivered',
                      delivered_at = CURRENT_TIMESTAMP,
                      updated_at = CURRENT_TIMESTAMP
                    WHERE id = :lead_id
                      AND status != 'delivered'
                    RETURNING id
                    """
                ),
                {"lead_id": lead_id},
            )
            if update_result.mappings().first():
                await session.commit()

            return DeliveryResult(
                success=True,
                attempts=attempts,
                final_status="delivered",
            )

    # All delivery attempts failed
    return DeliveryResult(
        success=False,
        attempts=attempts,
        final_status="delivery_failed",
    )

