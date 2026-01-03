from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.services.routing_engine import RoutingError, execute_routing


async def route_lead(
    *, session: AsyncSession, lead_id: int
) -> None:
    """
    Route a validated lead to a buyer.
    This function executes the routing pipeline and updates the lead status.
    """
    result = await execute_routing(lead_id=lead_id, session=session)
    
    if result.buyer_id is None:
        raise RoutingError(
            code="routing_failed",
            message=f"Failed to route lead_id={lead_id}: {result.no_route_reason}",
        )
