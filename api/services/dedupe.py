from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.lead import LeadIn

async def is_duplicate(session: AsyncSession, payload: LeadIn) -> bool:
    # Placeholder duplicate logic; soon compare email or phone for 24hr window
    return False
