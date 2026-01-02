from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_structlog_logger
from api.db.session import get_session
from api.schemas.lead import LeadIn, LeadResponse
from api.services import billing as billing_service
from api.services import dedupe as dedupe_service
from api.services import enrich as enrich_service
from api.services import route as route_service
from api.services import validate as validate_service

router = APIRouter()

@router.post(
    "/leads",
    response_model=LeadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a new lead"
)
async def ingest_lead(lead: LeadIn, session: AsyncSession = Depends(get_session)) -> LeadResponse:
    logger = get_structlog_logger().bind(route="/api/leads", action="ingest")

    try:
        await validate_service.validate_lead(lead)
    except ValueError as exc:
        logger.warning("validation.failure", error=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if await dedupe_service.is_duplicate(session, lead):
        logger.info("duplicate.lead", email=lead.email, phone=lead.phone)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead already exists")

    enriched = await enrich_service.enrich_lead(lead)
    buyer_id: Optional[int] = await route_service.select_buyer(session, enriched)
    await billing_service.bill(session, enriched, buyer_id)

    logger.info("lead.accepted", lead=lead.email, buyer_id=buyer_id)

    return LeadResponse(
        lead_id=0,
        status="accepted",
        message="Lead validated and queued",
        buyer_id=buyer_id,
        price=0.0
    )
