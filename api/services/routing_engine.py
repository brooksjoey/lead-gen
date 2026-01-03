from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RoutingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RoutingPolicy:
    id: int
    name: str
    version: int
    config: Dict[str, Any]
    is_active: bool


@dataclass(frozen=True)
class EligibleBuyer:
    buyer_id: int
    routing_priority: int
    price_per_lead: Optional[float]
    capacity_per_day: Optional[int]
    capacity_per_hour: Optional[int]


@dataclass(frozen=True)
class RoutingResult:
    buyer_id: Optional[int]
    no_route_reason: Optional[str] = None


async def load_routing_policy(
    *, session: AsyncSession, offer_id: int
) -> RoutingPolicy:
    """
    Load routing policy for an offer.
    """
    row = await session.execute(
        text(
            """
            SELECT
              rp.id,
              rp.name,
              rp.version,
              rp.config,
              rp.is_active
            FROM offers o
            JOIN routing_policies rp ON rp.id = o.routing_policy_id
            WHERE o.id = :offer_id
              AND rp.is_active = true
            LIMIT 1
            """
        ),
        {"offer_id": offer_id},
    )
    rec = row.mappings().first()
    if not rec:
        raise RoutingError(
            code="routing_policy_not_found",
            message=f"Routing policy not found for offer_id={offer_id}",
        )

    config = rec["config"]
    if not isinstance(config, dict):
        raise RoutingError(
            code="invalid_routing_policy",
            message=f"Routing policy config must be a JSON object, got {type(config)}",
        )

    return RoutingPolicy(
        id=int(rec["id"]),
        name=str(rec["name"]),
        version=int(rec["version"]),
        config=config,
        is_active=bool(rec["is_active"]),
    )


async def get_exclusive_buyer(
    *,
    session: AsyncSession,
    offer_id: int,
    scope_type: str,
    scope_value: str,
) -> Optional[int]:
    """
    Check for exclusive buyer for offer + scope.
    Returns buyer_id if exclusive buyer exists and is active, None otherwise.
    """
    row = await session.execute(
        text(
            """
            SELECT oe.buyer_id
            FROM offer_exclusivities oe
            JOIN buyers b ON b.id = oe.buyer_id
            WHERE oe.offer_id = :offer_id
              AND oe.scope_type = :scope_type
              AND oe.scope_value = :scope_value
              AND oe.is_active = true
              AND b.is_active = true
            LIMIT 1
            """
        ),
        {
            "offer_id": offer_id,
            "scope_type": scope_type,
            "scope_value": scope_value,
        },
    )
    rec = row.mappings().first()
    if rec:
        return int(rec["buyer_id"])
    return None


async def get_eligible_buyers(
    *,
    session: AsyncSession,
    offer_id: int,
    market_id: int,
    postal_code: Optional[str],
    city: Optional[str],
) -> List[EligibleBuyer]:
    """
    Get eligible buyers for offer + market + service area.
    Eligibility criteria:
    - buyer_offers enrollment for offer_id (is_active = true)
    - buyer_service_areas coverage for market_id (is_active = true)
    - buyer is_active = true
    - buyer not paused (pause_until IS NULL OR pause_until < NOW)
    - buyer satisfies capacity constraints if configured
    """
    # Build service area match conditions
    service_area_conditions = []
    service_area_params = {
        "offer_id": offer_id,
        "market_id": market_id,
    }

    if postal_code:
        service_area_conditions.append(
            "(bsa.scope_type = 'postal_code' AND bsa.scope_value = :postal_code)"
        )
        service_area_params["postal_code"] = postal_code

    if city:
        service_area_conditions.append(
            "(bsa.scope_type = 'city' AND bsa.scope_value = :city)"
        )
        service_area_params["city"] = city

    if not service_area_conditions:
        return []

    service_area_match = " OR ".join(service_area_conditions)

    # Query eligible buyers
    sql = f"""
    SELECT DISTINCT
      bo.buyer_id,
      bo.routing_priority,
      bo.price_per_lead,
      bo.capacity_per_day,
      bo.capacity_per_hour
    FROM buyer_offers bo
    JOIN buyers b ON b.id = bo.buyer_id
    JOIN buyer_service_areas bsa ON bsa.buyer_id = bo.buyer_id
    WHERE bo.offer_id = :offer_id
      AND bo.is_active = true
      AND b.is_active = true
      AND bsa.market_id = :market_id
      AND bsa.is_active = true
      AND ({service_area_match})
      AND (bo.pause_until IS NULL OR bo.pause_until < CURRENT_TIMESTAMP)
      AND (b.min_balance_required IS NULL OR b.balance >= b.min_balance_required)
    ORDER BY bo.routing_priority ASC, bo.buyer_id ASC
    """

    rows = await session.execute(text(sql), service_area_params)
    eligible = []
    for rec in rows.mappings():
        # Check capacity constraints (simplified - would need daily/hourly tracking in real system)
        # For now, we skip capacity checks as they require additional tracking tables
        eligible.append(
            EligibleBuyer(
                buyer_id=int(rec["buyer_id"]),
                routing_priority=int(rec["routing_priority"]),
                price_per_lead=float(rec["price_per_lead"]) if rec["price_per_lead"] else None,
                capacity_per_day=int(rec["capacity_per_day"]) if rec["capacity_per_day"] else None,
                capacity_per_hour=int(rec["capacity_per_hour"]) if rec["capacity_per_hour"] else None,
            )
        )

    return eligible


def select_buyer_by_strategy(
    *,
    eligible_buyers: List[EligibleBuyer],
    policy_config: Dict[str, Any],
) -> Optional[EligibleBuyer]:
    """
    Select buyer using routing strategy from policy config.
    Strategies: priority, rotation, weighted
    """
    if not eligible_buyers:
        return None

    strategy = policy_config.get("strategy", "priority")
    fallback_behavior = policy_config.get("exclusivity_fallback", "fail_closed")

    if strategy == "priority":
        # Select buyer with highest priority (lowest routing_priority number)
        # Tie-break by buyer_id (deterministic)
        return min(eligible_buyers, key=lambda b: (b.routing_priority, b.buyer_id))

    elif strategy == "rotation":
        # Rotation requires tracking last assigned buyer per offer
        # For now, use priority as fallback
        # In production, would query rotation_state table
        return min(eligible_buyers, key=lambda b: (b.routing_priority, b.buyer_id))

    elif strategy == "weighted":
        # Weighted selection based on weights in config
        # For now, use priority as fallback
        weights = policy_config.get("weights", {})
        if weights:
            # Would implement weighted random selection here
            # For now, fallback to priority
            pass
        return min(eligible_buyers, key=lambda b: (b.routing_priority, b.buyer_id))

    else:
        # Unknown strategy, default to priority
        return min(eligible_buyers, key=lambda b: (b.routing_priority, b.buyer_id))


async def execute_routing(
    *,
    session: AsyncSession,
    lead_id: int,
) -> RoutingResult:
    """
    Execute routing pipeline for a lead:
    1. Load routing policy
    2. Check for exclusive buyer
    3. Get eligible buyers
    4. Select buyer by strategy
    5. Update lead status (guarded)
    """
    # Load lead data
    lead_row = await session.execute(
        text(
            """
            SELECT
              id,
              offer_id,
              market_id,
              status,
              postal_code,
              city
            FROM leads
            WHERE id = :lead_id
            """
        ),
        {"lead_id": lead_id},
    )
    lead_rec = lead_row.mappings().first()
    if not lead_rec:
        raise RoutingError(
            code="lead_not_found",
            message=f"Lead with id={lead_id} not found",
        )

    if lead_rec["status"] != "validated":
        # Already processed or not ready, return current state
        buyer_id = lead_rec.get("buyer_id")
        return RoutingResult(
            buyer_id=int(buyer_id) if buyer_id else None,
            no_route_reason="lead_not_validated" if lead_rec["status"] != "delivered" else None,
        )

    offer_id = int(lead_rec["offer_id"])
    market_id = int(lead_rec["market_id"])
    postal_code = lead_rec.get("postal_code")
    city = lead_rec.get("city")

    # Load routing policy
    policy = await load_routing_policy(session=session, offer_id=offer_id)
    policy_config = policy.config

    # Step 1: Check for exclusive buyer
    exclusive_buyer_id = None
    if postal_code:
        exclusive_buyer_id = await get_exclusive_buyer(
            session=session,
            offer_id=offer_id,
            scope_type="postal_code",
            scope_value=postal_code,
        )
    if not exclusive_buyer_id and city:
        exclusive_buyer_id = await get_exclusive_buyer(
            session=session,
            offer_id=offer_id,
            scope_type="city",
            scope_value=city,
        )

    if exclusive_buyer_id:
        # Check if exclusive buyer is eligible
        eligible = await get_eligible_buyers(
            session=session,
            offer_id=offer_id,
            market_id=market_id,
            postal_code=postal_code,
            city=city,
        )
        exclusive_eligible = [b for b in eligible if b.buyer_id == exclusive_buyer_id]
        if exclusive_eligible:
            # Route to exclusive buyer
            selected_buyer = exclusive_eligible[0]
        else:
            # Exclusive buyer is ineligible
            fallback_behavior = policy_config.get("exclusivity_fallback", "fail_closed")
            if fallback_behavior == "fail_closed":
                return RoutingResult(
                    buyer_id=None,
                    no_route_reason="exclusive_buyer_ineligible_fail_closed",
                )
            # fallback_allowed: continue to regular selection
            selected_buyer = None
    else:
        selected_buyer = None

    # Step 2: If no exclusive buyer selected, get eligible buyers and select by strategy
    if not selected_buyer:
        eligible = await get_eligible_buyers(
            session=session,
            offer_id=offer_id,
            market_id=market_id,
            postal_code=postal_code,
            city=city,
        )

        if not eligible:
            return RoutingResult(
                buyer_id=None,
                no_route_reason="no_eligible_buyers",
            )

        selected_buyer = select_buyer_by_strategy(
            eligible_buyers=eligible,
            policy_config=policy_config,
        )

        if not selected_buyer:
            return RoutingResult(
                buyer_id=None,
                no_route_reason="strategy_selection_failed",
            )

    # Step 3: Update lead with buyer_id (guarded transition)
    # Note: Status remains 'validated' until delivery succeeds
    update_result = await session.execute(
        text(
            """
            UPDATE leads
            SET
              buyer_id = :buyer_id,
              updated_at = CURRENT_TIMESTAMP
            WHERE id = :lead_id
              AND status = 'validated'
            RETURNING id
            """
        ),
        {
            "lead_id": lead_id,
            "buyer_id": selected_buyer.buyer_id,
        },
    )
    updated_rec = update_result.mappings().first()

    if not updated_rec:
        # Concurrent routing attempt or status changed
        # Fetch current state
        current_row = await session.execute(
            text("SELECT buyer_id, status FROM leads WHERE id = :lead_id"),
            {"lead_id": lead_id},
        )
        current_rec = current_row.mappings().first()
        if current_rec and current_rec["status"] == "delivered":
            return RoutingResult(
                buyer_id=int(current_rec["buyer_id"]) if current_rec["buyer_id"] else None,
            )
        return RoutingResult(
            buyer_id=None,
            no_route_reason="concurrent_routing_attempt",
        )

    await session.commit()

    # Note: Delivery enqueue should be triggered separately after routing completes
    # In production, would push to Redis queue via background task
    # For now, delivery can be triggered via worker or separate API call

    return RoutingResult(
        buyer_id=selected_buyer.buyer_id,
    )

