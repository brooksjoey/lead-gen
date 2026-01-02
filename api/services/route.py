from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.lead import LeadIn

async def select_buyer(session: AsyncSession, lead: LeadIn) -> Optional[int]:
    # Placeholder routing strategy
    return None
