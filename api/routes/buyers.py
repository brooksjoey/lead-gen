# C:\work-spaces\lead-gen\lead-gen\api\routes\buyers.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator
from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from api.core.config import settings
from api.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from api.core.logging import get_structlog_logger
# Buyer models not yet implemented - using raw SQL
from api.models.offer import Offer
from api.db.session import get_session
from api.schemas.common import PaginatedResponse, PaginationParams
from api.services.auth import get_current_user, require_role
from api.services.validation import validate_phone_number, validate_zip_code

logger = get_structlog_logger()

router = APIRouter(prefix="/buyers", tags=["buyers"])


# Pydantic Models
class BuyerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Buyer company name")
    contact_name: Optional[str] = Field(None, max_length=255, description="Primary contact name")
    email: EmailStr = Field(..., description="Primary contact email")
    phone: Optional[str] = Field(None, description="Primary contact phone")
    address: Optional[str] = Field(None, max_length=500, description="Company address")
    city: Optional[str] = Field(None, max_length=100, description="City")
    state: Optional[str] = Field(None, max_length=2, description="State code (2 letters)")
    postal_code: Optional[str] = Field(None, max_length=10, description="Postal/ZIP code")
    country: str = Field(default="US", max_length=2, description="Country code (ISO 3166-1 alpha-2)")
    website: Optional[HttpUrl] = Field(None, description="Company website")
    
    @field_validator("phone")
    def validate_phone(cls, v):
        if v is not None:
            return validate_phone_number(v)
        return v
    
    @field_validator("postal_code")
    def validate_postal_code(cls, v):
        if v is not None:
            return validate_zip_code(v)
        return v


class BuyerCreate(BuyerBase):
    webhook_url: Optional[HttpUrl] = Field(None, description="Default webhook URL for lead delivery")
    webhook_secret: Optional[str] = Field(None, min_length=16, max_length=255, description="Webhook signature secret")
    email_notifications: bool = Field(default=True, description="Enable email notifications")
    sms_notifications: bool = Field(default=False, description="Enable SMS notifications")
    status: str = Field(default="active", pattern="^(active|inactive|suspended)$")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom metadata")


class BuyerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    contact_name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=2)
    postal_code: Optional[str] = Field(None, max_length=10)
    country: Optional[str] = Field(None, max_length=2)
    website: Optional[HttpUrl] = None
    webhook_url: Optional[HttpUrl] = None
    webhook_secret: Optional[str] = Field(None, min_length=16, max_length=255)
    email_notifications: Optional[bool] = None
    sms_notifications: Optional[bool] = None
    status: Optional[str] = Field(None, pattern="^(active|inactive|suspended)$")
    metadata: Optional[Dict[str, Any]] = None
    
    @field_validator("phone")
    def validate_phone(cls, v):
        if v is not None:
            return validate_phone_number(v)
        return v


class BuyerResponse(BuyerBase):
    id: int
    webhook_url: Optional[str] = None
    email_notifications: bool
    sms_notifications: bool
    status: str
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    total_leads: int = 0
    delivered_leads: int = 0
    conversion_rate: float = 0.0
    
    class Config:
        from_attributes = True


class BuyerOfferCreate(BaseModel):
    offer_id: int = Field(..., description="Offer ID")
    webhook_url_override: Optional[HttpUrl] = Field(None, description="Offer-specific webhook URL")
    webhook_secret_override: Optional[str] = Field(None, min_length=16, max_length=255)
    email_override: Optional[EmailStr] = Field(None, description="Offer-specific email")
    sms_override: Optional[str] = Field(None, description="Offer-specific phone")
    priority: int = Field(default=1, ge=1, le=10, description="Priority for this offer (1-10)")
    status: str = Field(default="active", pattern="^(active|inactive)$")
    
    @field_validator("sms_override")
    def validate_sms_override(cls, v):
        if v is not None:
            return validate_phone_number(v)
        return v


class BuyerOfferResponse(BuyerOfferCreate):
    id: int
    buyer_id: int
    offer_name: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class BuyerWebhookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Webhook name for reference")
    url: HttpUrl = Field(..., description="Webhook URL")
    secret: Optional[str] = Field(None, min_length=16, max_length=255, description="Signature secret")
    events: List[str] = Field(
        default_factory=lambda: ["lead.delivered"],
        description="Events to trigger webhook"
    )
    active: bool = Field(default=True, description="Webhook status")
    retry_policy: Dict[str, Any] = Field(
        default_factory=lambda: {
            "max_attempts": 3,
            "retry_delays": [1, 5, 15],
        }
    )


class BuyerWebhookResponse(BuyerWebhookCreate):
    id: int
    buyer_id: int
    last_triggered_at: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# Utility Functions
async def get_buyer_or_404(
    buyer_id: int,
    session: AsyncSession,
    include_stats: bool = False,
) -> Buyer:
    """Get buyer by ID or raise 404."""
    from sqlalchemy import select
    
    stmt = select(Buyer).where(
        Buyer.id == buyer_id,
        Buyer.deleted_at.is_(None),
    )
    
    result = await session.execute(stmt)
    buyer = result.scalar_one_or_none()
    
    if not buyer:
        raise NotFoundError(
            message="Buyer not found",
            details={"buyer_id": buyer_id},
        )
    
    if include_stats:
        # Add lead statistics
        from sqlalchemy import func
        from api.db.models.lead import Lead
        
        stats_stmt = select(
            func.count(Lead.id).label("total_leads"),
            func.count(Lead.id).filter(Lead.status == "delivered").label("delivered_leads"),
        ).where(
            Lead.buyer_id == buyer_id,
            Lead.deleted_at.is_(None),
        )
        
        stats_result = await session.execute(stats_stmt)
        stats = stats_result.first()
        
        if stats:
            buyer.total_leads = stats.total_leads or 0
            buyer.delivered_leads = stats.delivered_leads or 0
            buyer.conversion_rate = (
                (buyer.delivered_leads / buyer.total_leads * 100)
                if buyer.total_leads > 0 else 0.0
            )
    
    return buyer


async def check_buyer_conflicts(
    session: AsyncSession,
    buyer_data: Dict[str, Any],
    exclude_id: Optional[int] = None,
) -> None:
    """Check for duplicate buyer records."""
    from sqlalchemy import or_, select
    
    conditions = []
    
    # Check for duplicate email
    if "email" in buyer_data:
        conditions.append(Buyer.email == buyer_data["email"])
    
    # Check for duplicate name (case-insensitive)
    if "name" in buyer_data:
        conditions.append(func.lower(Buyer.name) == func.lower(buyer_data["name"]))
    
    if conditions:
        stmt = select(Buyer.id).where(
            or_(*conditions),
            Buyer.deleted_at.is_(None),
        )
        
        if exclude_id:
            stmt = stmt.where(Buyer.id != exclude_id)
        
        result = await session.execute(stmt)
        existing = result.scalars().first()
        
        if existing:
            raise ConflictError(
                message="Buyer with this email or name already exists",
                details={"existing_id": existing},
            )


# Routes
@router.get("/", response_model=PaginatedResponse[BuyerResponse])
async def list_buyers(
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
    pagination: PaginationParams = Depends(),
    status: Optional[str] = Query(None, pattern="^(active|inactive|suspended)$"),
    search: Optional[str] = Query(None, min_length=1, max_length=100),
):
    """List buyers with pagination and filtering."""
    await require_role(current_user, ["admin", "manager"])
    
    from sqlalchemy import select
    from api.db.models.lead import Lead
    
    # Build query
    stmt = select(Buyer).where(Buyer.deleted_at.is_(None))
    
    # Apply filters
    if status:
        stmt = stmt.where(Buyer.status == status)
    
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Buyer.name.ilike(search_term),
                Buyer.email.ilike(search_term),
                Buyer.contact_name.ilike(search_term),
            )
        )
    
    # Apply pagination
    total_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(total_stmt)
    total = total_result.scalar()
    
    stmt = stmt.offset(pagination.skip).limit(pagination.limit)
    
    # Execute query
    result = await session.execute(stmt)
    buyers = result.scalars().all()
    
    # Add statistics for each buyer
    for buyer in buyers:
        stats_stmt = select(
            func.count().label("total_leads"),
            func.count().filter(Lead.status == "delivered").label("delivered_leads"),
        ).where(Lead.buyer_id == buyer.id)
        
        stats_result = await session.execute(stats_stmt)
        stats = stats_result.first()
        
        if stats:
            buyer.total_leads = stats.total_leads or 0
            buyer.delivered_leads = stats.delivered_leads or 0
            buyer.conversion_rate = (
                (buyer.delivered_leads / buyer.total_leads * 100)
                if buyer.total_leads > 0 else 0.0
            )
    
    logger.info(
        "buyers.list",
        user_id=current_user.get("id"),
        total=total,
        page=pagination.page,
        page_size=pagination.limit,
    )
    
    return PaginatedResponse(
        items=buyers,
        total=total,
        page=pagination.page,
        page_size=pagination.limit,
        total_pages=(total + pagination.limit - 1) // pagination.limit,
    )


@router.post("/", response_model=BuyerResponse, status_code=status.HTTP_201_CREATED)
async def create_buyer(
    buyer_data: BuyerCreate,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Create a new buyer."""
    await require_role(current_user, ["admin", "manager"])
    
    # Check for conflicts
    await check_buyer_conflicts(session, buyer_data.model_dump())
    
    # Create buyer
    buyer = Buyer(
        **buyer_data.model_dump(exclude_unset=True),
        created_by=current_user.get("id"),
    )
    
    session.add(buyer)
    
    try:
        await session.commit()
        await session.refresh(buyer)
        
        logger.info(
            "buyer.created",
            buyer_id=buyer.id,
            user_id=current_user.get("id"),
            buyer_name=buyer.name,
        )
        
        return buyer
        
    except Exception as e:
        await session.rollback()
        logger.error("buyer.creation_failed", error=str(e))
        raise


@router.get("/{buyer_id}", response_model=BuyerResponse)
async def get_buyer(
    buyer_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Get buyer details by ID."""
    await require_role(current_user, ["admin", "manager", "buyer"])
    
    # Check if user is this buyer or has admin role
    if current_user.get("role") == "buyer" and current_user.get("buyer_id") != buyer_id:
        raise AuthorizationError(
            message="Cannot access other buyer's details",
            details={"requested_buyer_id": buyer_id},
        )
    
    buyer = await get_buyer_or_404(buyer_id, session, include_stats=True)
    
    logger.info(
        "buyer.retrieved",
        buyer_id=buyer_id,
        user_id=current_user.get("id"),
    )
    
    return buyer


@router.put("/{buyer_id}", response_model=BuyerResponse)
async def update_buyer(
    buyer_id: int,
    buyer_data: BuyerUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Update buyer details."""
    await require_role(current_user, ["admin", "manager"])
    
    buyer = await get_buyer_or_404(buyer_id, session)
    
    # Check for conflicts if email or name is being updated
    update_data = buyer_data.model_dump(exclude_unset=True)
    if "email" in update_data or "name" in update_data:
        await check_buyer_conflicts(session, update_data, exclude_id=buyer_id)
    
    # Update buyer
    for field, value in update_data.items():
        setattr(buyer, field, value)
    
    buyer.updated_by = current_user.get("id")
    
    try:
        await session.commit()
        await session.refresh(buyer)
        
        logger.info(
            "buyer.updated",
            buyer_id=buyer_id,
            user_id=current_user.get("id"),
            updated_fields=list(update_data.keys()),
        )
        
        return buyer
        
    except Exception as e:
        await session.rollback()
        logger.error("buyer.update_failed", error=str(e))
        raise


@router.delete("/{buyer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_buyer(
    buyer_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Soft delete a buyer."""
    await require_role(current_user, ["admin"])
    
    buyer = await get_buyer_or_404(buyer_id, session)
    
    # Check if buyer has active leads
    from sqlalchemy import select
    from api.db.models.lead import Lead
    
    active_leads_stmt = select(func.count()).where(
        Lead.buyer_id == buyer_id,
        Lead.status.in_(["new", "validated", "processing"]),
        Lead.deleted_at.is_(None),
    )
    
    result = await session.execute(active_leads_stmt)
    active_leads = result.scalar()
    
    if active_leads > 0:
        raise BusinessRuleError(
            message="Cannot delete buyer with active leads",
            details={"active_leads": active_leads},
        )
    
    # Soft delete
    buyer.deleted_at = datetime.utcnow()
    buyer.deleted_by = current_user.get("id")
    
    try:
        await session.commit()
        
        logger.info(
            "buyer.deleted",
            buyer_id=buyer_id,
            user_id=current_user.get("id"),
        )
        
    except Exception as e:
        await session.rollback()
        logger.error("buyer.deletion_failed", error=str(e))
        raise


# Buyer Offers Routes
@router.get("/{buyer_id}/offers", response_model=List[BuyerOfferResponse])
async def list_buyer_offers(
    buyer_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
    status: Optional[str] = Query(None, pattern="^(active|inactive)$"),
):
    """List offers for a specific buyer."""
    await require_role(current_user, ["admin", "manager", "buyer"])
    
    # Verify buyer exists and user has access
    await get_buyer_or_404(buyer_id, session)
    
    if current_user.get("role") == "buyer" and current_user.get("buyer_id") != buyer_id:
        raise AuthorizationError(
            message="Cannot access other buyer's offers",
            details={"requested_buyer_id": buyer_id},
        )
    
    from sqlalchemy import select
    
    stmt = select(BuyerOffer, Offer.name.label("offer_name")).join(
        Offer, BuyerOffer.offer_id == Offer.id
    ).where(
        BuyerOffer.buyer_id == buyer_id,
        BuyerOffer.deleted_at.is_(None),
    )
    
    if status:
        stmt = stmt.where(BuyerOffer.status == status)
    
    result = await session.execute(stmt)
    rows = result.all()
    
    # Format response
    offers = []
    for row in rows:
        offer_data = row.BuyerOffer.to_dict()
        offer_data["offer_name"] = row.offer_name
        offers.append(offer_data)
    
    logger.info(
        "buyer.offers.list",
        buyer_id=buyer_id,
        user_id=current_user.get("id"),
        count=len(offers),
    )
    
    return offers


@router.post("/{buyer_id}/offers", response_model=BuyerOfferResponse, status_code=status.HTTP_201_CREATED)
async def add_buyer_offer(
    buyer_id: int,
    offer_data: BuyerOfferCreate,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Add an offer to a buyer."""
    await require_role(current_user, ["admin", "manager"])
    
    # Verify buyer exists
    await get_buyer_or_404(buyer_id, session)
    
    # Verify offer exists
    from sqlalchemy import select
    from api.models.offer import Offer
    
    offer_stmt = select(Offer).where(
        Offer.id == offer_data.offer_id,
        Offer.deleted_at.is_(None),
    )
    offer_result = await session.execute(offer_stmt)
    offer = offer_result.scalar_one_or_none()
    
    if not offer:
        raise NotFoundError(
            message="Offer not found",
            details={"offer_id": offer_data.offer_id},
        )
    
    # Check if offer already assigned to buyer
    existing_stmt = select(BuyerOffer).where(
        BuyerOffer.buyer_id == buyer_id,
        BuyerOffer.offer_id == offer_data.offer_id,
        BuyerOffer.deleted_at.is_(None),
    )
    existing_result = await session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    
    if existing:
        raise ConflictError(
            message="Offer already assigned to buyer",
            details={
                "buyer_id": buyer_id,
                "offer_id": offer_data.offer_id,
            },
        )
    
    # Create buyer offer
    buyer_offer = BuyerOffer(
        buyer_id=buyer_id,
        **offer_data.model_dump(),
        created_by=current_user.get("id"),
    )
    
    session.add(buyer_offer)
    
    try:
        await session.commit()
        await session.refresh(buyer_offer)
        
        # Add offer name to response
        response = buyer_offer.to_dict()
        response["offer_name"] = offer.name
        
        logger.info(
            "buyer.offer.added",
            buyer_id=buyer_id,
            offer_id=offer_data.offer_id,
            user_id=current_user.get("id"),
        )
        
        return response
        
    except Exception as e:
        await session.rollback()
        logger.error("buyer.offer.creation_failed", error=str(e))
        raise


@router.delete("/{buyer_id}/offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_buyer_offer(
    buyer_id: int,
    offer_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Remove an offer from a buyer."""
    await require_role(current_user, ["admin", "manager"])
    
    # Verify buyer exists
    await get_buyer_or_404(buyer_id, session)
    
    # Find buyer offer
    from sqlalchemy import select
    
    stmt = select(BuyerOffer).where(
        BuyerOffer.buyer_id == buyer_id,
        BuyerOffer.offer_id == offer_id,
        BuyerOffer.deleted_at.is_(None),
    )
    
    result = await session.execute(stmt)
    buyer_offer = result.scalar_one_or_none()
    
    if not buyer_offer:
        raise NotFoundError(
            message="Buyer offer not found",
            details={"buyer_id": buyer_id, "offer_id": offer_id},
        )
    
    # Check if there are active leads for this buyer/offer
    from api.db.models.lead import Lead
    
    active_leads_stmt = select(func.count()).where(
        Lead.buyer_id == buyer_id,
        Lead.offer_id == offer_id,
        Lead.status.in_(["new", "validated", "processing"]),
        Lead.deleted_at.is_(None),
    )
    
    result = await session.execute(active_leads_stmt)
    active_leads = result.scalar()
    
    if active_leads > 0:
        raise BusinessRuleError(
            message="Cannot remove offer with active leads",
            details={"active_leads": active_leads},
        )
    
    # Soft delete buyer offer
    buyer_offer.deleted_at = datetime.utcnow()
    buyer_offer.deleted_by = current_user.get("id")
    
    try:
        await session.commit()
        
        logger.info(
            "buyer.offer.removed",
            buyer_id=buyer_id,
            offer_id=offer_id,
            user_id=current_user.get("id"),
        )
        
    except Exception as e:
        await session.rollback()
        logger.error("buyer.offer.removal_failed", error=str(e))
        raise


# Webhooks Routes
@router.get("/{buyer_id}/webhooks", response_model=List[BuyerWebhookResponse])
async def list_buyer_webhooks(
    buyer_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
    active_only: bool = Query(False, description="Show only active webhooks"),
):
    """List webhooks for a buyer."""
    await require_role(current_user, ["admin", "manager", "buyer"])
    
    # Verify buyer exists and user has access
    await get_buyer_or_404(buyer_id, session)
    
    if current_user.get("role") == "buyer" and current_user.get("buyer_id") != buyer_id:
        raise AuthorizationError(
            message="Cannot access other buyer's webhooks",
            details={"requested_buyer_id": buyer_id},
        )
    
    from sqlalchemy import select
    
    stmt = select(BuyerWebhook).where(
        BuyerWebhook.buyer_id == buyer_id,
        BuyerWebhook.deleted_at.is_(None),
    )
    
    if active_only:
        stmt = stmt.where(BuyerWebhook.active == True)
    
    result = await session.execute(stmt)
    webhooks = result.scalars().all()
    
    logger.info(
        "buyer.webhooks.list",
        buyer_id=buyer_id,
        user_id=current_user.get("id"),
        count=len(webhooks),
    )
    
    return webhooks


@router.post("/{buyer_id}/webhooks", response_model=BuyerWebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_buyer_webhook(
    buyer_id: int,
    webhook_data: BuyerWebhookCreate,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Create a new webhook for a buyer."""
    await require_role(current_user, ["admin", "manager"])
    
    # Verify buyer exists
    await get_buyer_or_404(buyer_id, session)
    
    # Validate webhook URL (basic check)
    if not webhook_data.url.startswith(("https://", "http://")):
        raise ValidationError(
            message="Webhook URL must start with http:// or https://",
            details={"url": str(webhook_data.url)},
        )
    
    # Create webhook
    webhook = BuyerWebhook(
        buyer_id=buyer_id,
        **webhook_data.model_dump(),
        created_by=current_user.get("id"),
    )
    
    session.add(webhook)
    
    try:
        await session.commit()
        await session.refresh(webhook)
        
        logger.info(
            "buyer.webhook.created",
            buyer_id=buyer_id,
            webhook_id=webhook.id,
            user_id=current_user.get("id"),
            url=str(webhook.url),
        )
        
        return webhook
        
    except Exception as e:
        await session.rollback()
        logger.error("buyer.webhook.creation_failed", error=str(e))
        raise


@router.delete("/{buyer_id}/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_buyer_webhook(
    buyer_id: int,
    webhook_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Delete a buyer webhook."""
    await require_role(current_user, ["admin", "manager"])
    
    # Verify buyer exists
    await get_buyer_or_404(buyer_id, session)
    
    # Find webhook
    from sqlalchemy import select
    
    stmt = select(BuyerWebhook).where(
        BuyerWebhook.id == webhook_id,
        BuyerWebhook.buyer_id == buyer_id,
        BuyerWebhook.deleted_at.is_(None),
    )
    
    result = await session.execute(stmt)
    webhook = result.scalar_one_or_none()
    
    if not webhook:
        raise NotFoundError(
            message="Webhook not found",
            details={"webhook_id": webhook_id, "buyer_id": buyer_id},
        )
    
    # Soft delete webhook
    webhook.deleted_at = datetime.utcnow()
    webhook.deleted_by = current_user.get("id")
    
    try:
        await session.commit()
        
        logger.info(
            "buyer.webhook.deleted",
            buyer_id=buyer_id,
            webhook_id=webhook_id,
            user_id=current_user.get("id"),
        )
        
    except Exception as e:
        await session.rollback()
        logger.error("buyer.webhook.deletion_failed", error=str(e))
        raise
