# api/services/dedupe.py
from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def is_duplicate(
    session: AsyncSession, 
    offer_id: int, 
    phone: str, 
    email: str, 
    hours: int = 24
) -> tuple[bool, int | None]:
    """
    Check for duplicate lead within time window.
    Returns (is_duplicate, duplicate_lead_id)
    """
    result = await session.execute(
        text("""
            SELECT id, created_at
            FROM leads 
            WHERE offer_id = :offer_id
            AND (
                phone = :phone OR email = :email
            )
            AND created_at >= NOW() - INTERVAL ':hours hours'
            AND status NOT IN ('rejected')
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"offer_id": offer_id, "phone": phone, "email": email, "hours": hours}
    )
    
    duplicate = result.mappings().first()
    if duplicate:
        return True, duplicate["id"]
    return False, None


async def normalize_and_store_duplicate_fields(
    session: AsyncSession,
    lead_id: int,
    phone: str,
    email: str
) -> None:
    """Normalize phone/email and store for duplicate detection."""
    normalized_phone = ''.join(filter(str.isdigit, phone))[-10:] if phone else None
    normalized_email = email.strip().lower() if email else None
    
    await session.execute(
        text("""
            UPDATE leads 
            SET normalized_phone = :normalized_phone,
                normalized_email = :normalized_email,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :lead_id
        """),
        {
            "lead_id": lead_id,
            "normalized_phone": normalized_phone,
            "normalized_email": normalized_email
        }
    )