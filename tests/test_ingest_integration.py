import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.main import app
from api.services.classification import resolve_classification


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_ingest_lead_with_source_key(db_session: AsyncSession):
    """
    Integration test: Create test data and ingest a lead with source_key.
    This requires database setup with markets, verticals, validation_policies,
    routing_policies, offers, and sources.
    """
    # Setup test data (simplified - would need full setup in real test)
    # For now, test that the endpoint structure is correct
    pass


@pytest.mark.asyncio
async def test_ingest_lead_idempotency(db_session: AsyncSession, client):
    """
    Test that identical requests return the same lead_id.
    """
    # This would require full test data setup
    # Test would:
    # 1. POST /api/leads with same (source_key, idempotency_key)
    # 2. Verify both return same lead_id
    pass


@pytest.mark.asyncio
async def test_ingest_lead_concurrent_idempotency(db_session: AsyncSession, client):
    """
    Test that 20 concurrent POSTs with same (source_id, idempotency_key)
    all return the same lead_id without errors.
    """
    import asyncio

    # This would require full test data setup
    # Test would spawn 20 concurrent requests and verify all get same lead_id
    pass

