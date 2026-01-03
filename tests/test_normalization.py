import pytest

from api.services.normalization import normalize_email, normalize_phone


def test_normalize_email():
    assert normalize_email("test@example.com") == "test@example.com"
    assert normalize_email("  Test@Example.COM  ") == "test@example.com"
    assert normalize_email("TEST@EXAMPLE.COM") == "test@example.com"

    assert normalize_email(None) is None
    assert normalize_email("") is None
    assert normalize_email("   ") is None
    assert normalize_email("invalid") is None  # No @
    assert normalize_email("invalid@") is None  # No domain


def test_normalize_phone_e164():
    # E.164 format should be preserved
    assert normalize_phone("+15125550123") == "+15125550123"
    assert normalize_phone("  +15125550123  ") == "+15125550123"
    assert normalize_phone("+1234567890123456") == "+1234567890123456"  # Max length


def test_normalize_phone_digits_only():
    # Non-E.164 should become digits only
    assert normalize_phone("(512) 555-0123") == "5125550123"
    assert normalize_phone("512-555-0123") == "5125550123"
    assert normalize_phone("512.555.0123") == "5125550123"
    assert normalize_phone("512 555 0123") == "5125550123"


def test_normalize_phone_invalid():
    assert normalize_phone(None) is None
    assert normalize_phone("") is None
    assert normalize_phone("   ") is None
    assert normalize_phone("123") is None  # Too short (< 7 digits)
    assert normalize_phone("abc") is None  # No digits

