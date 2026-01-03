import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.validation_engine import (
    ValidationError,
    execute_validation,
    load_validation_policy,
    parse_duplicate_detection_policy,
    validate_lead_fields,
)


def test_parse_duplicate_detection_policy_enabled():
    rules = {
        "duplicate_detection": {
            "enabled": True,
            "window_hours": 24,
            "scope": "offer",
            "keys": ["phone", "email"],
            "match_mode": "any",
            "exclude_statuses": ["rejected"],
            "include_sources": "any",
            "action": "reject",
            "reason_code": "duplicate_recent",
            "min_fields": ["phone"],
            "normalize": {
                "email": "lower_trim",
                "phone": "e164_or_digits",
            },
        }
    }
    policy = parse_duplicate_detection_policy(rules)
    assert policy is not None
    assert policy.enabled is True
    assert policy.window_hours == 24
    assert policy.action == "reject"


def test_parse_duplicate_detection_policy_disabled():
    rules = {
        "duplicate_detection": {
            "enabled": False,
        }
    }
    policy = parse_duplicate_detection_policy(rules)
    assert policy is None


def test_parse_duplicate_detection_policy_missing():
    rules = {}
    policy = parse_duplicate_detection_policy(rules)
    assert policy is None


@pytest.mark.asyncio
async def test_validate_lead_fields_required_fields():
    from api.services.validation_engine import ValidationPolicy

    policy = ValidationPolicy(
        id=1,
        name="Test Policy",
        version=1,
        rules={"required_fields": ["name", "email", "phone"]},
        is_active=True,
    )

    # Missing required field
    result = await validate_lead_fields(
        policy=policy,
        lead_data={"name": "John", "email": "john@example.com"},
    )
    assert result == "Required field 'phone' is missing or empty"

    # All required fields present
    result = await validate_lead_fields(
        policy=policy,
        lead_data={"name": "John", "email": "john@example.com", "phone": "+15125550123"},
    )
    assert result is None


@pytest.mark.asyncio
async def test_validate_lead_fields_allowed_postal_codes():
    from api.services.validation_engine import ValidationPolicy

    policy = ValidationPolicy(
        id=1,
        name="Test Policy",
        version=1,
        rules={"allowed_postal_codes": ["12345", "67890"]},
        is_active=True,
    )

    # Valid postal code
    result = await validate_lead_fields(
        policy=policy,
        lead_data={"postal_code": "12345"},
    )
    assert result is None

    # Invalid postal code
    result = await validate_lead_fields(
        policy=policy,
        lead_data={"postal_code": "99999"},
    )
    assert "not in allowed list" in result


@pytest.mark.asyncio
async def test_validate_lead_fields_allowed_cities():
    from api.services.validation_engine import ValidationPolicy

    policy = ValidationPolicy(
        id=1,
        name="Test Policy",
        version=1,
        rules={"allowed_cities": ["Austin", "Tampa"]},
        is_active=True,
    )

    # Valid city
    result = await validate_lead_fields(
        policy=policy,
        lead_data={"city": "Austin"},
    )
    assert result is None

    # Invalid city
    result = await validate_lead_fields(
        policy=policy,
        lead_data={"city": "Dallas"},
    )
    assert "not in allowed list" in result


@pytest.mark.asyncio
async def test_execute_validation_lead_not_found(db_session: AsyncSession):
    with pytest.raises(ValidationError) as exc_info:
        await execute_validation(session=db_session, lead_id=999999)
    assert exc_info.value.code == "lead_not_found"


@pytest.mark.asyncio
async def test_execute_validation_already_processed(db_session: AsyncSession):
    # This test requires a lead with status != 'received'
    # For now, test structure only
    pass

