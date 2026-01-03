# C:\work-spaces\lead-gen\lead-gen\api\routes\leads.py
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

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
from api.db.models.lead import Lead, LeadDelivery, LeadNote
from api.db.session import get_session, transaction_session
from api.schemas.common import PaginatedResponse, PaginationParams
from api.services.auth import get_current_user, require_role
from api.services.delivery_queue import delivery_queue
from api.services.validation import (
    deduplicate_leads,
    validate_email,
    validate_lead_data,
    validate_phone_number,
    validate_zip_code,
)
from api.utils.csv_parser import parse_csv_leads
from api.utils.excel_parser import parse_excel_leads

logger = get_structlog_logger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])


# Pydantic Models
class LeadBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Lead name")
    email: EmailStr = Field(..., description="Lead email address")
    phone: str = Field(..., description="Lead phone number")
    postal_code: str = Field(..., min_length=3, max_length=10, description="Postal/ZIP code")
    city: Optional[str] = Field(None, max_length=100, description="City")
    state: Optional[str] = Field(None, max_length=2, description="State code")
    country: str = Field(default="US", max_length=2, description="Country code")
    message: Optional[str] = Field(None, max_length=2000, description="Lead message/notes")
    source: Optional[str] = Field(None, max_length=100, description="Lead source")
    ip_address: Optional[str] = Field(None, max_length=45, description="IP address")
    user_agent: Optional[str] = Field(None, max_length=500, description="User agent")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom metadata")
    
    @field_validator("phone")
    def validate_phone(cls, v):
        return validate_phone_number(v)
    
    @field_validator("postal_code")
    def validate_postal_code(cls, v):
        return validate_zip_code(v)
    
    @field_validator("email")
    def validate_email_format(cls, v):
        return validate_email(v)


class LeadCreate(LeadBase):
    buyer_id: int = Field(..., description="Buyer ID")
    offer_id: int = Field(..., description="Offer ID")
    market_id: int = Field(..., description="Market ID")
    vertical_id: int = Field(..., description="Vertical ID")
    
    @field_validator("metadata")
    def validate_metadata(cls, v):
        if v and len(json.dumps(v)) > 10000:
            raise ValueError("Metadata too large (max 10KB)")
        return v


class LeadUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    postal_code: Optional[str] = Field(None, min_length=3, max_length=10)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=2)
    country: Optional[str] = Field(None, max_length=2)
    message: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = Field(
        None,
        pattern="^(new|validated|processing|delivered|failed|duplicate|rejected)$"
    )
    metadata: Optional[Dict[str, Any]] = None
    
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


class LeadResponse(LeadBase):
    id: int
    buyer_id: int
    offer_id: int
    market_id: int
    vertical_id: int
    status: str
    hash: str
    validation_errors: Optional[List[str]] = None
    delivered_at: Optional[datetime] = None
    delivery_attempts: int = 0
    delivery_result: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class LeadDeliveryResponse(BaseModel):
    id: int
    lead_id: int
    buyer_id: int
    channel: str
    status: str
    attempt_number: int
    response_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any]
    created_at: datetime
    
    class Config:
        from_attributes = True


class LeadNoteCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000, description="Note content")
    is_internal: bool = Field(default=False, description="Internal note (not shown to buyer)")


class LeadNoteResponse(LeadNoteCreate):
    id: int
    lead_id: int
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class BulkLeadResponse(BaseModel):
    total: int
    successful: int
    failed: int
    duplicates: int
    leads: List[LeadResponse]
    errors: List[Dict[str, Any]]


class LeadFilterParams(BaseModel):
    buyer_id: Optional[int] = None
    offer_id: Optional[int] = None
    market_id: Optional[int] = None
    vertical_id: Optional[int] = None
    status: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None


# Utility Functions
def generate_lead_hash(lead_data: Dict[str, Any]) -> str:
    """Generate a unique hash for lead deduplication."""
    hash_fields = [
        str(lead_data.get("email", "")).lower().strip(),
        str(lead_data.get("phone", "")).strip(),
        str(lead_data.get("postal_code", "")).strip(),
        str(lead_data.get("buyer_id", "")),
        str(lead_data.get("offer_id", "")),
    ]
    
    hash_string = "|".join(hash_fields)
    return hashlib.sha256(hash_string.encode()).hexdigest()


async def get_lead_or_404(
    lead_id: int,
    session: AsyncSession,
    current_user: Dict,
) -> Lead:
    """Get lead by ID with authorization check."""
    from sqlalchemy import select
    
    stmt = select(Lead).where(
        Lead.id == lead_id,
        Lead.deleted_at.is_(None),
    )
    
    result = await session.execute(stmt)
    lead = result.scalar_one_or_none()
    
    if not lead:
        raise NotFoundError(
            message="Lead not found",
            details={"lead_id": lead_id},
        )
    
    # Authorization check
    user_role = current_user.get("role")
    user_buyer_id = current_user.get("buyer_id")
    
    if user_role == "buyer" and lead.buyer_id != user_buyer_id:
        raise AuthorizationError(
            message="Cannot access lead from other buyer",
            details={"lead_id": lead_id, "buyer_id": lead.buyer_id},
        )
    
    return lead


async def check_duplicate_lead(
    session: AsyncSession,
    lead_data: Dict[str, Any],
    hash_value: str,
    window_hours: int = None,
) -> Optional[Lead]:
    """Check for duplicate leads within time window."""
    from sqlalchemy import select
    
    window_hours = window_hours or settings.duplicate_window_hours
    cutoff_time = datetime.utcnow() - timedelta(hours=window_hours)
    
    stmt = select(Lead).where(
        and_(
            Lead.hash == hash_value,
            Lead.created_at >= cutoff_time,
            Lead.deleted_at.is_(None),
        )
    )
    
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def validate_business_rules(
    session: AsyncSession,
    lead_data: Dict[str, Any],
) -> List[str]:
    """Validate business rules for lead."""
    errors = []
    
    # Check buyer exists and is active
    from sqlalchemy import select
    from api.db.models.buyer import Buyer
    
    buyer_stmt = select(Buyer).where(
        Buyer.id == lead_data["buyer_id"],
        Buyer.deleted_at.is_(None),
        Buyer.status == "active",
    )
    buyer_result = await session.execute(buyer_stmt)
    buyer = buyer_result.scalar_one_or_none()
    
    if not buyer:
        errors.append("Buyer not found or inactive")
    
    # Check buyer has access to offer
    if "offer_id" in lead_data:
        from api.db.models.buyer import BuyerOffer
        
        offer_stmt = select(BuyerOffer).where(
            BuyerOffer.buyer_id == lead_data["buyer_id"],
            BuyerOffer.offer_id == lead_data["offer_id"],
            BuyerOffer.status == "active",
            BuyerOffer.deleted_at.is_(None),
        )
        offer_result = await session.execute(offer_stmt)
        buyer_offer = offer_result.scalar_one_or_none()
        
        if not buyer_offer:
            errors.append("Buyer does not have access to this offer")
    
    # Check zip code restrictions
    if buyer and buyer.zip_restrictions:
        allowed_prefixes = [p.strip() for p in buyer.zip_restrictions.split(",") if p.strip()]
        if allowed_prefixes:
            lead_zip = str(lead_data.get("postal_code", "")).strip()
            if not any(lead_zip.startswith(prefix) for prefix in allowed_prefixes):
                errors.append(f"Postal code not allowed for this buyer")
    
    return errors


async def create_lead_delivery(
    session: AsyncSession,
    lead_id: int,
    delivery_data: Dict[str, Any],
) -> LeadDelivery:
    """Create lead delivery record."""
    delivery = LeadDelivery(
        lead_id=lead_id,
        **delivery_data,
    )
    
    session.add(delivery)
    await session.commit()
    await session.refresh(delivery)
    
    return delivery


# Routes
@router.get("/", response_model=PaginatedResponse[LeadResponse])
async def list_leads(
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
    pagination: PaginationParams = Depends(),
    buyer_id: Optional[int] = Query(None),
    offer_id: Optional[int] = Query(None),
    status: Optional[str] = Query(
        None,
        pattern="^(new|validated|processing|delivered|failed|duplicate|rejected)$"
    ),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    search: Optional[str] = Query(None, min_length=1, max_length=100),
):
    """List leads with pagination and filtering."""
    await require_role(current_user, ["admin", "manager", "buyer"])
    
    from sqlalchemy import select
    
    # Build query
    stmt = select(Lead).where(Lead.deleted_at.is_(None))
    
    # Apply authorization filter for buyers
    if current_user.get("role") == "buyer":
        stmt = stmt.where(Lead.buyer_id == current_user.get("buyer_id"))
    
    # Apply filters
    if buyer_id:
        stmt = stmt.where(Lead.buyer_id == buyer_id)
    
    if offer_id:
        stmt = stmt.where(Lead.offer_id == offer_id)
    
    if status:
        stmt = stmt.where(Lead.status == status)
    
    if date_from:
        stmt = stmt.where(Lead.created_at >= date_from)
    
    if date_to:
        stmt = stmt.where(Lead.created_at <= date_to)
    
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Lead.name.ilike(search_term),
                Lead.email.ilike(search_term),
                Lead.phone.ilike(search_term),
                Lead.postal_code.ilike(search_term),
            )
        )
    
    # Apply ordering
    stmt = stmt.order_by(Lead.created_at.desc())
    
    # Get total count
    total_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(total_stmt)
    total = total_result.scalar()
    
    # Apply pagination
    stmt = stmt.offset(pagination.skip).limit(pagination.limit)
    
    # Execute query
    result = await session.execute(stmt)
    leads = result.scalars().all()
    
    logger.info(
        "leads.list",
        user_id=current_user.get("id"),
        role=current_user.get("role"),
        total=total,
        page=pagination.page,
        page_size=pagination.limit,
        filters={
            "buyer_id": buyer_id,
            "offer_id": offer_id,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
        }
    )
    
    return PaginatedResponse(
        items=leads,
        total=total,
        page=pagination.page,
        page_size=pagination.limit,
        total_pages=(total + pagination.limit - 1) // pagination.limit,
    )


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    lead_data: LeadCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Create a new lead."""
    await require_role(current_user, ["admin", "manager", "buyer", "api"])
    
    # Authorization check for buyers
    if current_user.get("role") == "buyer":
        if lead_data.buyer_id != current_user.get("buyer_id"):
            raise AuthorizationError(
                message="Cannot create leads for other buyers",
                details={"buyer_id": lead_data.buyer_id},
            )
    
    # Validate lead data
    validation_errors = await validate_lead_data(session, lead_data.model_dump())
    
    if validation_errors:
        logger.warning(
            "lead.validation_failed",
            errors=validation_errors,
            lead_data=lead_data.model_dump(exclude={"metadata"}),
        )
        raise ValidationError(
            message="Lead validation failed",
            details={"errors": validation_errors},
        )
    
    # Generate hash for deduplication
    lead_dict = lead_data.model_dump()
    hash_value = generate_lead_hash(lead_dict)
    
    # Check for duplicates
    duplicate = await check_duplicate_lead(session, lead_dict, hash_value)
    if duplicate:
        logger.info(
            "lead.duplicate_found",
            original_lead_id=duplicate.id,
            new_lead_data=lead_dict,
        )
        
        # Update duplicate count
        duplicate.duplicate_count = (duplicate.duplicate_count or 0) + 1
        await session.commit()
        
        raise ConflictError(
            message="Duplicate lead detected",
            details={
                "original_lead_id": duplicate.id,
                "created_at": duplicate.created_at.isoformat(),
                "hash": hash_value,
            },
        )
    
    # Validate business rules
    business_errors = await validate_business_rules(session, lead_dict)
    if business_errors:
        raise BusinessRuleError(
            message="Business rule validation failed",
            details={"errors": business_errors},
        )
    
    # Create lead
    lead = Lead(
        **lead_dict,
        hash=hash_value,
        status="new",
        created_by=current_user.get("id"),
        ip_address=current_user.get("ip_address"),
        user_agent=current_user.get("user_agent"),
    )
    
    session.add(lead)
    
    try:
        await session.commit()
        await session.refresh(lead)
        
        logger.info(
            "lead.created",
            lead_id=lead.id,
            buyer_id=lead.buyer_id,
            offer_id=lead.offer_id,
            user_id=current_user.get("id"),
            hash=hash_value,
        )
        
        # Queue for validation and delivery (in background)
        background_tasks.add_task(
            process_lead_delivery,
            lead.id,
            current_user.get("id"),
        )
        
        return lead
        
    except Exception as e:
        await session.rollback()
        logger.error("lead.creation_failed", error=str(e), traceback=True)
        raise


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Get lead details by ID."""
    lead = await get_lead_or_404(lead_id, session, current_user)
    
    logger.info(
        "lead.retrieved",
        lead_id=lead_id,
        user_id=current_user.get("id"),
        role=current_user.get("role"),
    )
    
    return lead


@router.put("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: int,
    lead_data: LeadUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Update lead details."""
    await require_role(current_user, ["admin", "manager"])
    
    lead = await get_lead_or_404(lead_id, session, current_user)
    
    # Cannot update delivered leads
    if lead.status == "delivered":
        raise BusinessRuleError(
            message="Cannot update delivered leads",
            details={"lead_id": lead_id, "status": lead.status},
        )
    
    # Update lead
    update_data = lead_data.model_dump(exclude_unset=True)
    
    # Regenerate hash if contact info changed
    if any(field in update_data for field in ["email", "phone", "postal_code"]):
        lead_dict = lead.to_dict()
        lead_dict.update(update_data)
        update_data["hash"] = generate_lead_hash(lead_dict)
    
    for field, value in update_data.items():
        setattr(lead, field, value)
    
    lead.updated_by = current_user.get("id")
    
    try:
        await session.commit()
        await session.refresh(lead)
        
        logger.info(
            "lead.updated",
            lead_id=lead_id,
            user_id=current_user.get("id"),
            updated_fields=list(update_data.keys()),
        )
        
        return lead
        
    except Exception as e:
        await session.rollback()
        logger.error("lead.update_failed", error=str(e))
        raise


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Soft delete a lead."""
    await require_role(current_user, ["admin"])
    
    lead = await get_lead_or_404(lead_id, session, current_user)
    
    # Cannot delete delivered leads
    if lead.status == "delivered":
        raise BusinessRuleError(
            message="Cannot delete delivered leads",
            details={"lead_id": lead_id, "status": lead.status},
        )
    
    # Soft delete
    lead.deleted_at = datetime.utcnow()
    lead.deleted_by = current_user.get("id")
    
    try:
        await session.commit()
        
        logger.info(
            "lead.deleted",
            lead_id=lead_id,
            user_id=current_user.get("id"),
        )
        
    except Exception as e:
        await session.rollback()
        logger.error("lead.deletion_failed", error=str(e))
        raise


@router.post("/{lead_id}/deliver", status_code=status.HTTP_202_ACCEPTED)
async def deliver_lead(
    lead_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Trigger manual delivery for a lead."""
    await require_role(current_user, ["admin", "manager"])
    
    lead = await get_lead_or_404(lead_id, session, current_user)
    
    # Check lead status
    if lead.status not in ["new", "validated", "failed"]:
        raise BusinessRuleError(
            message=f"Cannot deliver lead with status: {lead.status}",
            details={"lead_id": lead_id, "status": lead.status},
        )
    
    # Queue for delivery
    background_tasks.add_task(
        process_lead_delivery,
        lead.id,
        current_user.get("id"),
        manual=True,
    )
    
    logger.info(
        "lead.delivery_triggered",
        lead_id=lead_id,
        user_id=current_user.get("id"),
        manual=True,
    )
    
    return {
        "message": "Lead delivery queued",
        "lead_id": lead_id,
        "status": "queued",
    }


@router.get("/{lead_id}/deliveries", response_model=List[LeadDeliveryResponse])
async def get_lead_deliveries(
    lead_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Get delivery history for a lead."""
    lead = await get_lead_or_404(lead_id, session, current_user)
    
    from sqlalchemy import select
    
    stmt = select(LeadDelivery).where(
        LeadDelivery.lead_id == lead_id,
        LeadDelivery.deleted_at.is_(None),
    ).order_by(LeadDelivery.created_at.desc())
    
    result = await session.execute(stmt)
    deliveries = result.scalars().all()
    
    logger.info(
        "lead.deliveries.list",
        lead_id=lead_id,
        user_id=current_user.get("id"),
        count=len(deliveries),
    )
    
    return deliveries


# Notes Routes
@router.get("/{lead_id}/notes", response_model=List[LeadNoteResponse])
async def get_lead_notes(
    lead_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
    include_internal: bool = Query(False, description="Include internal notes"),
):
    """Get notes for a lead."""
    lead = await get_lead_or_404(lead_id, session, current_user)
    
    from sqlalchemy import select
    
    stmt = select(LeadNote).where(
        LeadNote.lead_id == lead_id,
        LeadNote.deleted_at.is_(None),
    )
    
    if not include_internal:
        stmt = stmt.where(LeadNote.is_internal == False)
    
    stmt = stmt.order_by(LeadNote.created_at.desc())
    
    result = await session.execute(stmt)
    notes = result.scalars().all()
    
    # Add creator names
    for note in notes:
        if note.created_by:
            # In production, you'd join with users table
            note.created_by_name = f"User {note.created_by}"
    
    logger.info(
        "lead.notes.list",
        lead_id=lead_id,
        user_id=current_user.get("id"),
        count=len(notes),
        include_internal=include_internal,
    )
    
    return notes


@router.post("/{lead_id}/notes", response_model=LeadNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_lead_note(
    lead_id: int,
    note_data: LeadNoteCreate,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
):
    """Add a note to a lead."""
    await require_role(current_user, ["admin", "manager", "buyer"])
    
    lead = await get_lead_or_404(lead_id, session, current_user)
    
    # Create note
    note = LeadNote(
        lead_id=lead_id,
        **note_data.model_dump(),
        created_by=current_user.get("id"),
    )
    
    session.add(note)
    
    try:
        await session.commit()
        await session.refresh(note)
        
        # Add creator name
        note.created_by_name = f"User {current_user.get('id')}"
        
        logger.info(
            "lead.note.created",
            lead_id=lead_id,
            note_id=note.id,
            user_id=current_user.get("id"),
            is_internal=note.is_internal,
        )
        
        return note
        
    except Exception as e:
        await session.rollback()
        logger.error("lead.note.creation_failed", error=str(e))
        raise


# Bulk Operations
@router.post("/bulk", response_model=BulkLeadResponse, status_code=status.HTTP_201_CREATED)
async def create_bulk_leads(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
    buyer_id: int = Form(...),
    offer_id: int = Form(...),
    market_id: int = Form(...),
    vertical_id: int = Form(...),
    file: UploadFile = File(...),
):
    """Create leads in bulk from CSV/Excel file."""
    await require_role(current_user, ["admin", "manager", "buyer"])
    
    # Authorization check for buyers
    if current_user.get("role") == "buyer" and buyer_id != current_user.get("buyer_id"):
        raise AuthorizationError(
            message="Cannot create leads for other buyers",
            details={"buyer_id": buyer_id},
        )
    
    # Validate file
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if file_ext not in ["csv", "xlsx", "xls"]:
        raise ValidationError(
            message="Invalid file format. Supported formats: CSV, Excel",
            details={"file_type": file_ext},
        )
    
    # Read and parse file
    file_content = await file.read()
    
    try:
        if file_ext == "csv":
            leads_data = await parse_csv_leads(file_content)
        else:  # Excel
            leads_data = await parse_excel_leads(file_content)
    except Exception as e:
        logger.error("bulk_leads.parse_failed", error=str(e))
        raise ValidationError(
            message="Failed to parse file",
            details={"error": str(e)},
        )
    
    if not leads_data:
        raise ValidationError(
            message="No valid leads found in file",
            details={"file": file.filename},
        )
    
    # Validate business rules
    business_errors = await validate_business_rules(session, {
        "buyer_id": buyer_id,
        "offer_id": offer_id,
        "market_id": market_id,
        "vertical_id": vertical_id,
    })
    
    if business_errors:
        raise BusinessRuleError(
            message="Business rule validation failed",
            details={"errors": business_errors},
        )
    
    # Process leads
    successful_leads = []
    errors = []
    duplicate_count = 0
    
    for idx, lead_row in enumerate(leads_data, 1):
        try:
            # Add required fields
            lead_row.update({
                "buyer_id": buyer_id,
                "offer_id": offer_id,
                "market_id": market_id,
                "vertical_id": vertical_id,
            })
            
            # Validate lead data
            validation_errors = await validate_lead_data(session, lead_row)
            if validation_errors:
                errors.append({
                    "row": idx,
                    "data": lead_row,
                    "errors": validation_errors,
                })
                continue
            
            # Generate hash
            hash_value = generate_lead_hash(lead_row)
            
            # Check for duplicates
            duplicate = await check_duplicate_lead(session, lead_row, hash_value)
            if duplicate:
                duplicate_count += 1
                duplicate.duplicate_count = (duplicate.duplicate_count or 0) + 1
                continue
            
            # Create lead
            lead = Lead(
                **lead_row,
                hash=hash_value,
                status="new",
                created_by=current_user.get("id"),
            )
            
            session.add(lead)
            await session.commit()
            await session.refresh(lead)
            
            successful_leads.append(lead)
            
            # Queue for delivery
            background_tasks.add_task(
                process_lead_delivery,
                lead.id,
                current_user.get("id"),
            )
            
        except Exception as e:
            errors.append({
                "row": idx,
                "data": lead_row,
                "error": str(e),
            })
            await session.rollback()
    
    # Update session with any duplicate count changes
    await session.commit()
    
    logger.info(
        "bulk_leads.created",
        user_id=current_user.get("id"),
        total=len(leads_data),
        successful=len(successful_leads),
        failed=len(errors),
        duplicates=duplicate_count,
        file=file.filename,
    )
    
    return BulkLeadResponse(
        total=len(leads_data),
        successful=len(successful_leads),
        failed=len(errors),
        duplicates=duplicate_count,
        leads=successful_leads,
        errors=errors,
    )


@router.get("/export/csv")
async def export_leads_csv(
    session: AsyncSession = Depends(get_session),
    current_user: Dict = Depends(get_current_user),
    buyer_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    """Export leads to CSV."""
    await require_role(current_user, ["admin", "manager"])
    
    from sqlalchemy import select
    
    # Build query
    stmt = select(Lead).where(Lead.deleted_at.is_(None))
    
    if current_user.get("role") == "buyer":
        stmt = stmt.where(Lead.buyer_id == current_user.get("buyer_id"))
    
    if buyer_id:
        stmt = stmt.where(Lead.buyer_id == buyer_id)
    
    if date_from:
        stmt = stmt.where(Lead.created_at >= date_from)
    
    if date_to:
        stmt = stmt.where(Lead.created_at <= date_to)
    
    stmt = stmt.order_by(Lead.created_at.desc())
    
    # Execute query
    result = await session.execute(stmt)
    leads = result.scalars().all()
    
    # Generate CSV
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        "ID", "Name", "Email", "Phone", "Postal Code", "City", "State", "Country",
        "Buyer ID", "Offer ID", "Market ID", "Vertical ID", "Status",
        "Created At", "Delivered At", "Source", "Message"
    ])
    
    # Write data
    for lead in leads:
        writer.writerow([
            lead.id,
            lead.name,
            lead.email,
            lead.phone,
            lead.postal_code,
            lead.city or "",
            lead.state or "",
            lead.country,
            lead.buyer_id,
            lead.offer_id,
            lead.market_id,
            lead.vertical_id,
            lead.status,
            lead.created_at.isoformat(),
            lead.delivered_at.isoformat() if lead.delivered_at else "",
            lead.source or "",
            (lead.message or "")[:100],
        ])
    
    logger.info(
        "leads.exported.csv",
        user_id=current_user.get("id"),
        count=len(leads),
        filters={"buyer_id": buyer_id, "date_from": date_from, "date_to": date_to},
    )
    
    # Return as streaming response
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=leads_export_{datetime.utcnow().date()}.csv"
        }
    )


# Background Tasks
async def process_lead_delivery(
    lead_id: int,
    user_id: Optional[int] = None,
    manual: bool = False,
):
    """Background task to process lead delivery."""
    from api.core.logging import get_structlog_logger
    
    logger = get_structlog_logger(__name__)
    
    try:
        # Get database session
        async with transaction_session() as session:
            # Load lead
            from sqlalchemy import select
            
            stmt = select(Lead).where(
                Lead.id == lead_id,
                Lead.deleted_at.is_(None),
            )
            
            result = await session.execute(stmt)
            lead = result.scalar_one_or_none()
            
            if not lead:
                logger.error("lead.delivery.lead_not_found", lead_id=lead_id)
                return
            
            # Update status to processing
            lead.status = "processing"
            lead.updated_by = user_id
            
            await session.commit()
            
            logger.info(
                "lead.delivery.started",
                lead_id=lead_id,
                buyer_id=lead.buyer_id,
                user_id=user_id,
                manual=manual,
            )
            
            # Queue for delivery via Redis
            from api.services.redis import get_redis_client
            from api.services.delivery_queue import delivery_queue
            
            redis_client = await get_redis_client()
            
            if delivery_queue is None:
                from api.services.delivery_queue import init_delivery_queue
                init_delivery_queue(redis_client)
            
            # Add to delivery queue
            success = await delivery_queue.enqueue_delivery(lead_id, priority=1)
            
            if not success:
                lead.status = "failed"
                lead.updated_by = user_id
                await session.commit()
                
                logger.error(
                    "lead.delivery.queue_failed",
                    lead_id=lead_id,
                )
    
    except Exception as e:
        logger.error(
            "lead.delivery.processing_error",
            lead_id=lead_id,
            error=str(e),
            traceback=True,
        )