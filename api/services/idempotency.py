# api/routes/leads.py
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api.db.session import get_session
from api.schemas.leads_ingest import LeadIngestRequest
from api.schemas.leads_ingest_response import LeadIngestResponse
from api.services.classification_resolver import ClassificationError, resolve_classification
from api.services.idempotency import IdempotencyError, canonicalize_idempotency_key, derive_idempotency_key, upsert_lead_stub_idempotent

router = APIRouter()


async def load_validation_policy(session: AsyncSession, offer_id: int) -> dict:
    """Load validation policy rules for an offer."""
    result = await session.execute(
        text("""
            SELECT vp.rules 
            FROM validation_policies vp
            JOIN offers o ON o.validation_policy_id = vp.id
            WHERE o.id = :offer_id AND vp.is_active = true
        """),
        {"offer_id": offer_id}
    )
    row = result.first()
    return row[0] if row else {}


async def load_routing_policy(session: AsyncSession, offer_id: int) -> dict:
    """Load routing policy config for an offer."""
    result = await session.execute(
        text("""
            SELECT rp.config 
            FROM routing_policies rp
            JOIN offers o ON o.routing_policy_id = rp.id
            WHERE o.id = :offer_id AND rp.is_active = true
        """),
        {"offer_id": offer_id}
    )
    row = result.first()
    return row[0] if row else {}


async def validate_lead(session: AsyncSession, lead_id: int, policy: dict, payload: dict) -> bool:
    """Apply validation rules from policy."""
    if not policy.get("enabled", True):
        return True

    # Basic required fields validation
    required = policy.get("required_fields", ["name", "email", "phone", "postal_code"])
    for field in required:
        if not payload.get(field):
            await session.execute(
                text("""
                    UPDATE leads 
                    SET status = 'rejected', 
                        validation_reason = 'missing_required_field',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :lead_id AND status = 'received'
                """),
                {"lead_id": lead_id, "field": field}
            )
            return False

    # Postal code validation
    allowed_postal_codes = policy.get("allowed_postal_codes", [])
    if allowed_postal_codes and payload.get("postal_code"):
        if payload["postal_code"] not in allowed_postal_codes:
            await session.execute(
                text("""
                    UPDATE leads 
                    SET status = 'rejected', 
                        validation_reason = 'invalid_postal_code',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :lead_id AND status = 'received'
                """),
                {"lead_id": lead_id}
            )
            return False

    # Phone validation
    phone = payload.get("phone", "")
    if policy.get("phone_validation", False):
        if not phone.replace("+", "").isdigit():
            await session.execute(
                text("""
                    UPDATE leads 
                    SET status = 'rejected', 
                        validation_reason = 'invalid_phone',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :lead_id AND status = 'received'
                """),
                {"lead_id": lead_id}
            )
            return False

    # Mark as validated
    await session.execute(
        text("""
            UPDATE leads 
            SET status = 'validated', 
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :lead_id AND status = 'received'
        """),
        {"lead_id": lead_id}
    )
    return True


async def select_buyer(session: AsyncSession, lead_id: int, offer_id: int, postal_code: str, city: str, policy: dict) -> int | None:
    """Select buyer based on routing policy."""
    # Check exclusive buyer first
    exclusive_result = await session.execute(
        text("""
            SELECT oe.buyer_id
            FROM offer_exclusivities oe
            WHERE oe.offer_id = :offer_id
            AND oe.is_active = true
            AND (
                (oe.scope_type = 'postal_code' AND oe.scope_value = :postal_code)
                OR (oe.scope_type = 'city' AND oe.scope_value = :city)
            )
        """),
        {"offer_id": offer_id, "postal_code": postal_code, "city": city or ""}
    )
    exclusive = exclusive_result.scalar()
    if exclusive:
        return exclusive

    # Get eligible buyers with service areas
    result = await session.execute(
        text("""
            SELECT DISTINCT bo.buyer_id, bo.routing_priority
            FROM buyer_offers bo
            JOIN buyer_service_areas bsa ON bsa.buyer_id = bo.buyer_id
            WHERE bo.offer_id = :offer_id
            AND bo.is_active = true
            AND bsa.is_active = true
            AND bsa.market_id = (SELECT market_id FROM offers WHERE id = :offer_id)
            AND (
                (bsa.scope_type = 'postal_code' AND bsa.scope_value = :postal_code)
                OR (bsa.scope_type = 'city' AND bsa.scope_value = :city)
            )
            ORDER BY bo.routing_priority DESC
            LIMIT 1
        """),
        {"offer_id": offer_id, "postal_code": postal_code, "city": city or ""}
    )
    return result.scalar()


async def deliver_lead(session: AsyncSession, lead_id: int, buyer_id: int) -> bool:
    """Deliver lead to buyer."""
    await session.execute(
        text("""
            UPDATE leads 
            SET status = 'delivered', 
                buyer_id = :buyer_id,
                delivered_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :lead_id AND status = 'validated'
        """),
        {"lead_id": lead_id, "buyer_id": buyer_id}
    )
    return True


async def bill_lead(session: AsyncSession, lead_id: int, buyer_id: int, offer_id: int) -> float:
    """Bill lead and update buyer balance."""
    # Get price
    result = await session.execute(
        text("""
            SELECT COALESCE(bo.price_per_lead, o.default_price_per_lead) as price
            FROM offers o
            LEFT JOIN buyer_offers bo ON bo.offer_id = o.id AND bo.buyer_id = :buyer_id
            WHERE o.id = :offer_id
        """),
        {"offer_id": offer_id, "buyer_id": buyer_id}
    )
    price = result.scalar() or 0.0

    # Atomic billing transaction
    await session.execute(
        text("""
            WITH lead_update AS (
                UPDATE leads 
                SET billing_status = 'billed', 
                    price = :price,
                    billed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :lead_id 
                AND billing_status = 'pending'
                RETURNING id
            ),
            buyer_update AS (
                UPDATE buyers 
                SET balance = balance + :price
                WHERE id = :buyer_id
                AND EXISTS (SELECT 1 FROM lead_update)
                RETURNING id
            )
            SELECT 1 FROM buyer_update
        """),
        {"lead_id": lead_id, "buyer_id": buyer_id, "price": price}
    )
    
    return price


async def detect_duplicate(session: AsyncSession, lead_id: int, offer_id: int, phone: str, email: str) -> bool:
    """Check for duplicate lead within 24 hours."""
    result = await session.execute(
        text("""
            SELECT id 
            FROM leads 
            WHERE offer_id = :offer_id
            AND (
                phone = :phone OR email = :email
            )
            AND created_at >= NOW() - INTERVAL '24 hours'
            AND status NOT IN ('rejected')
            AND id != :lead_id
            LIMIT 1
        """),
        {"offer_id": offer_id, "phone": phone, "email": email, "lead_id": lead_id}
    )
    return result.scalar() is not None


@router.post(
    "/leads",
    response_model=LeadIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_lead(
    req: Request,
    body: LeadIngestRequest,
    session: AsyncSession = Depends(get_session),
) -> LeadIngestResponse:
    # 1. Classification
    try:
        classification = await resolve_classification(
            session,
            source_id=body.source_id,
            source_key=body.source_key,
            request_host=req.headers.get("host"),
            request_path=req.url.path,
        )
    except ClassificationError as e:
        raise HTTPException(status_code=e.http_status, detail={"code": e.code, **(e.details or {})})

    # 2. Idempotency
    idempotency_key = body.idempotency_key
    if not idempotency_key:
        # Derive from lead data
        try:
            idempotency_key = derive_idempotency_key(
                source_id=classification.source_id,
                name=body.name,
                email=body.email,
                phone=body.phone,
                country_code=body.country_code,
                postal_code=body.postal_code,
                message=body.message,
            )
        except IdempotencyError as e:
            raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message})
    else:
        try:
            idempotency_key = canonicalize_idempotency_key(idempotency_key)
        except IdempotencyError as e:
            raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message})

    # 3. Create/retrieve lead row
    try:
        lead_result = await upsert_lead_stub_idempotent(
            session=session,
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
            source=body.source or "landing_page",
            name=body.name,
            email=body.email,
            phone=body.phone,
            country_code=body.country_code,
            postal_code=body.postal_code,
            city=body.city,
            region_code=body.region_code,
            message=body.message,
            utm_source=body.utm_source,
            utm_medium=body.utm_medium,
            utm_campaign=body.utm_campaign,
            ip_address=req.client.host if req.client else None,
            user_agent=req.headers.get("user-agent"),
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        await session.rollback()
        # Retry to get existing lead
        result = await session.execute(
            text("""
                SELECT id, status, buyer_id, price
                FROM leads 
                WHERE source_id = :source_id AND idempotency_key = :idempotency_key
            """),
            {"source_id": classification.source_id, "idempotency_key": idempotency_key}
        )
        existing = result.mappings().first()
        if existing:
            return LeadIngestResponse(
                lead_id=existing["id"],
                status=existing["status"],
                source_id=classification.source_id,
                offer_id=classification.offer_id,
                market_id=classification.market_id,
                vertical_id=classification.vertical_id,
                idempotency_key=idempotency_key,
                buyer_id=existing.get("buyer_id"),
                price=existing.get("price"),
            )
        raise HTTPException(status_code=500, detail="idempotency_insert_failed")
    except IdempotencyError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message})

    # If this is a replay of existing lead, return early
    if not lead_result.created_new:
        result = await session.execute(
            text("SELECT status, buyer_id, price FROM leads WHERE id = :lead_id"),
            {"lead_id": lead_result.lead_id}
        )
        existing = result.mappings().first()
        return LeadIngestResponse(
            lead_id=lead_result.lead_id,
            status=existing["status"],
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
            idempotency_key=idempotency_key,
            buyer_id=existing.get("buyer_id"),
            price=existing.get("price"),
        )

    # 4. Duplicate detection
    if await detect_duplicate(session, lead_result.lead_id, classification.offer_id, body.phone, body.email):
        await session.execute(
            text("""
                UPDATE leads 
                SET is_duplicate = true, 
                    status = 'rejected',
                    validation_reason = 'duplicate',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :lead_id
            """),
            {"lead_id": lead_result.lead_id}
        )
        await session.commit()
        return LeadIngestResponse(
            lead_id=lead_result.lead_id,
            status="rejected",
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
            idempotency_key=idempotency_key,
        )

    # 5. Load policies
    validation_policy = await load_validation_policy(session, classification.offer_id)
    routing_policy = await load_routing_policy(session, classification.offer_id)

    # 6. Validation
    payload_dict = body.model_dump()
    if not await validate_lead(session, lead_result.lead_id, validation_policy, payload_dict):
        await session.commit()
        return LeadIngestResponse(
            lead_id=lead_result.lead_id,
            status="rejected",
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
            idempotency_key=idempotency_key,
        )

    # 7. Routing
    buyer_id = await select_buyer(
        session, 
        lead_result.lead_id, 
        classification.offer_id, 
        body.postal_code, 
        body.city, 
        routing_policy
    )
    
    if not buyer_id:
        await session.execute(
            text("""
                UPDATE leads 
                SET status = 'rejected', 
                    validation_reason = 'no_buyer_available',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :lead_id
            """),
            {"lead_id": lead_result.lead_id}
        )
        await session.commit()
        return LeadIngestResponse(
            lead_id=lead_result.lead_id,
            status="rejected",
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
            idempotency_key=idempotency_key,
        )

    # 8. Delivery
    await deliver_lead(session, lead_result.lead_id, buyer_id)

    # 9. Billing
    price = await bill_lead(session, lead_result.lead_id, buyer_id, classification.offer_id)

    await session.commit()

    return LeadIngestResponse(
        lead_id=lead_result.lead_id,
        status="delivered",
        source_id=classification.source_id,
        offer_id=classification.offer_id,
        market_id=classification.market_id,
        vertical_id=classification.vertical_id,
        idempotency_key=idempotency_key,
        buyer_id=buyer_id,
        price=price,
    )