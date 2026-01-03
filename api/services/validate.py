from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.services.validation_engine import ValidationError, execute_validation


async def validate_lead(
    *, session: AsyncSession, lead_id: int
) -> None:
    """
    Validate a lead using policy-driven validation and duplicate detection.
    This function executes the validation pipeline and updates the lead status.
    """
    result = await execute_validation(session=session, lead_id=lead_id)
    
    if not result.is_valid:
        raise ValidationError(
            code="validation_failed",
            message="Lead did not pass validation",
            reason=result.reason,
        )
