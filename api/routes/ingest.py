from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_structlog_logger
from api.db.session import get_session
from api.schemas.lead import LeadIn, LeadResponse
from api.services.classification import SourceResolutionError, resolve_classification
from api.services.idempotency import IdempotencyError, upsert_lead_stub_idempotent
from api.services.normalization import normalize_email, normalize_phone

router = APIRouter()


@router.post(
    "/leads",
    response_model=LeadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a new lead"
)
async def ingest_lead(
    lead: LeadIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LeadResponse:
    logger = get_structlog_logger().bind(route="/api/leads", action="ingest")

    try:
        # Step 1: Classification (resolve source_id → offer_id → market_id/vertical_id)
        classification = await resolve_classification(
            session=session,
            request=request,
            source_id=lead.source_id,
            source_key=lead.source_key,
        )
        logger.info(
            "classification.resolved",
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
        )

        # Step 2: Normalize fields for duplicate detection
        norm_email = normalize_email(lead.email)
        norm_phone = normalize_phone(lead.phone)

        # Step 3: Idempotent lead creation
        insert_result = await upsert_lead_stub_idempotent(
            session=session,
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
            source=lead.source,
            name=lead.name,
            email=lead.email,
            phone=lead.phone,
            country_code=lead.country_code,
            postal_code=lead.postal_code,
            city=lead.city,
            region_code=lead.region_code,
            message=lead.message,
            utm_source=lead.utm_source,
            utm_medium=lead.utm_medium,
            utm_campaign=lead.utm_campaign,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            idempotency_key=lead.idempotency_key,
            normalized_email=norm_email,
            normalized_phone=norm_phone,
        )

        logger.info(
            "lead.ingested",
            lead_id=insert_result.lead_id,
            created_new=insert_result.created_new,
            source_id=classification.source_id,
        )

        # Fetch current lead status for response
        from sqlalchemy import text
        status_row = await session.execute(
            text("SELECT status, buyer_id, price FROM leads WHERE id = :lead_id"),
            {"lead_id": insert_result.lead_id},
        )
        status_rec = status_row.mappings().first()
        current_status = status_rec["status"] if status_rec else "received"
        buyer_id = status_rec["buyer_id"] if status_rec else None
        price = float(status_rec["price"]) if status_rec and status_rec["price"] else None

        return LeadResponse(
            lead_id=insert_result.lead_id,
            status=current_status,
            buyer_id=buyer_id,
            source_id=classification.source_id,
            offer_id=classification.offer_id,
            market_id=classification.market_id,
            vertical_id=classification.vertical_id,
            price=price,
        )

    except SourceResolutionError as e:
        logger.warning("classification.failed", code=e.code, message=e.message)
        if e.code == "ambiguous_source_mapping":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": e.code, "message": e.message},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": e.code, "message": e.message},
        )

    except IdempotencyError as e:
        logger.warning("idempotency.failed", code=e.code, message=e.message)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": e.code, "message": e.message},
        )
