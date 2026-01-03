import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.routing_engine import (
    RoutingError,
    execute_routing,
    get_eligible_buyers,
    get_exclusive_buyer,
    load_routing_policy,
    select_buyer_by_strategy,
    EligibleBuyer,
    BuyerCapacity,
)


def test_select_buyer_by_strategy_priority():
    eligible = [
        EligibleBuyer(
            buyer_id=1,
            routing_priority=2,
            price_per_lead=10.0,
            capacity=BuyerCapacity(daily_used=0, daily_limit=None, hourly_used=0, hourly_limit=None, is_capped=False)
        ),
        EligibleBuyer(
            buyer_id=2,
            routing_priority=1,
            price_per_lead=15.0,
            capacity=BuyerCapacity(daily_used=0, daily_limit=None, hourly_used=0, hourly_limit=None, is_capped=False)
        ),
        EligibleBuyer(
            buyer_id=3,
            routing_priority=1,
            price_per_lead=12.0,
            capacity=BuyerCapacity(daily_used=0, daily_limit=None, hourly_used=0, hourly_limit=None, is_capped=False)
        ),
    ]
    policy_config = {"strategy": "priority"}
    
    selected = select_buyer_by_strategy(
        eligible_buyers=eligible,
        policy_config=policy_config,
    )
    
    assert selected is not None
    # Should select buyer with priority 1, tie-break by buyer_id (lowest)
    assert selected.buyer_id == 2


def test_select_buyer_by_strategy_empty():
    eligible = []
    policy_config = {"strategy": "priority"}
    
    selected = select_buyer_by_strategy(
        eligible_buyers=eligible,
        policy_config=policy_config,
    )
    
    assert selected is None


@pytest.mark.asyncio
async def test_get_exclusive_buyer_not_found(db_session: AsyncSession):
    result = await get_exclusive_buyer(
        session=db_session,
        offer_id=999,
        scope_type="postal_code",
        scope_value="99999",
    )
    assert result is None


@pytest.mark.asyncio
async def test_get_eligible_buyers_empty(db_session: AsyncSession):
    result = await get_eligible_buyers(
        session=db_session,
        offer_id=999,
        market_id=999,
        postal_code="99999",
        city=None,
    )
    assert result == []


@pytest.mark.asyncio
async def test_execute_routing_lead_not_found(db_session: AsyncSession):
    with pytest.raises(RoutingError) as exc_info:
        await execute_routing(session=db_session, lead_id=999999)
    assert exc_info.value.code == "lead_not_found"


@pytest.mark.asyncio
async def test_execute_routing_already_processed(db_session: AsyncSession):
    # This test requires a lead with status != 'validated'
    # For now, test structure only
    pass

