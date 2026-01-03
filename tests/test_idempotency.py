import pytest

from api.services.idempotency import (
    IdempotencyError,
    canonicalize_idempotency_key,
    derive_idempotency_key,
)


def test_canonicalize_idempotency_key_valid():
    assert canonicalize_idempotency_key("test-key-12345678") == "test-key-12345678"
    assert canonicalize_idempotency_key("  test-key-12345678  ") == "test-key-12345678"
    assert canonicalize_idempotency_key("test.key:12345678") == "test.key:12345678"


def test_canonicalize_idempotency_key_invalid():
    with pytest.raises(IdempotencyError) as exc_info:
        canonicalize_idempotency_key("short")  # Too short
    assert exc_info.value.code == "invalid_idempotency_key_format"

    with pytest.raises(IdempotencyError) as exc_info:
        canonicalize_idempotency_key("test@key")  # Invalid char
    assert exc_info.value.code == "invalid_idempotency_key_format"


def test_derive_idempotency_key():
    key = derive_idempotency_key(
        source_id=1,
        name="John Smith",
        email="john@example.com",
        phone="+15125550123",
        country_code="US",
        postal_code="12345",
        message="Test message",
    )
    assert len(key) == 64  # SHA-256 hex
    assert key.isalnum() or all(c in "abcdef0123456789" for c in key)

    # Same inputs should produce same key
    key2 = derive_idempotency_key(
        source_id=1,
        name="John Smith",
        email="john@example.com",
        phone="+15125550123",
        country_code="US",
        postal_code="12345",
        message="Test message",
    )
    assert key == key2

    # Different source_id should produce different key
    key3 = derive_idempotency_key(
        source_id=2,
        name="John Smith",
        email="john@example.com",
        phone="+15125550123",
        country_code="US",
        postal_code="12345",
        message="Test message",
    )
    assert key != key3


def test_derive_idempotency_key_missing_fields():
    with pytest.raises(IdempotencyError) as exc_info:
        derive_idempotency_key(
            source_id=1,
            name="John Smith",
            email="",  # Missing
            phone="+15125550123",
            country_code="US",
            postal_code="12345",
            message=None,
        )
    assert exc_info.value.code == "idempotency_derivation_failed"

    with pytest.raises(IdempotencyError) as exc_info:
        derive_idempotency_key(
            source_id=1,
            name="John Smith",
            email="john@example.com",
            phone="",  # Missing
            country_code="US",
            postal_code="12345",
            message=None,
        )
    assert exc_info.value.code == "idempotency_derivation_failed"

    with pytest.raises(IdempotencyError) as exc_info:
        derive_idempotency_key(
            source_id=1,
            name="John Smith",
            email="john@example.com",
            phone="+15125550123",
            country_code="US",
            postal_code="",  # Missing
            message=None,
        )
    assert exc_info.value.code == "idempotency_derivation_failed"

