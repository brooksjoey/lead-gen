import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.delivery_engine import (
    DeliveryError,
    execute_delivery,
    format_delivery_payload,
    generate_delivery_idempotency_key,
    generate_webhook_signature,
)


def test_generate_delivery_idempotency_key():
    key1 = generate_delivery_idempotency_key(lead_id=123, idempotency_key="abc123")
    assert key1 == "delivery:123:abc123"

    key2 = generate_delivery_idempotency_key(lead_id=123, idempotency_key=None)
    assert key2 == "delivery:123"


def test_generate_webhook_signature():
    payload = '{"lead_id": 123}'
    secret = "test_secret"
    signature = generate_webhook_signature(payload, secret)
    assert len(signature) == 64  # SHA-256 hex
    assert isinstance(signature, str)

    # Same payload + secret should produce same signature
    signature2 = generate_webhook_signature(payload, secret)
    assert signature == signature2


def test_format_delivery_payload():
    payload = format_delivery_payload(
        lead_id=123,
        name="John Doe",
        email="john@example.com",
        phone="+15125550123",
        country_code="US",
        postal_code="12345",
        city="Austin",
        region_code="TX",
        message="Test message",
        idempotency_key="abc123",
        source="landing_page",
        utm_source="google",
        utm_medium="cpc",
        utm_campaign="test",
    )

    assert payload["lead_id"] == 123
    assert payload["contact"]["name"] == "John Doe"
    assert payload["contact"]["email"] == "john@example.com"
    assert payload["location"]["postal_code"] == "12345"
    assert "idempotency_key" in payload
    assert payload["attribution"]["utm_source"] == "google"


@pytest.mark.asyncio
async def test_execute_delivery_lead_not_found(db_session: AsyncSession):
    with pytest.raises(DeliveryError) as exc_info:
        await execute_delivery(session=db_session, lead_id=999999)
    assert exc_info.value.code == "lead_not_found"


@pytest.mark.asyncio
async def test_execute_delivery_no_buyer(db_session: AsyncSession):
    # This test requires a lead without buyer_id
    # For now, test structure only
    pass


@pytest.mark.asyncio
async def test_execute_delivery_already_delivered(db_session: AsyncSession):
    # This test requires a lead with status='delivered'
    # For now, test structure only
    pass

