import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.classification import (
    SourceResolutionError,
    canonicalize_hostname,
    canonicalize_path,
    canonicalize_source_key,
    resolve_classification,
)


def test_canonicalize_source_key_valid():
    assert canonicalize_source_key("test-key-123") == "test-key-123"
    assert canonicalize_source_key("  test-key-123  ") == "test-key-123"
    assert canonicalize_source_key("test.key:123") == "test.key:123"


def test_canonicalize_source_key_invalid():
    with pytest.raises(SourceResolutionError) as exc_info:
        canonicalize_source_key("")
    assert exc_info.value.code == "invalid_source_key_format"

    with pytest.raises(SourceResolutionError) as exc_info:
        canonicalize_source_key("a")  # Too short
    assert exc_info.value.code == "invalid_source_key_format"

    with pytest.raises(SourceResolutionError) as exc_info:
        canonicalize_source_key("test@key")  # Invalid char
    assert exc_info.value.code == "invalid_source_key_format"


def test_canonicalize_hostname():
    assert canonicalize_hostname("example.com") == "example.com"
    assert canonicalize_hostname("Example.COM") == "example.com"
    assert canonicalize_hostname("example.com:8080") == "example.com"
    assert canonicalize_hostname("  example.com  ") == "example.com"

    with pytest.raises(SourceResolutionError) as exc_info:
        canonicalize_hostname(None)
    assert exc_info.value.code == "missing_host_header"

    with pytest.raises(SourceResolutionError) as exc_info:
        canonicalize_hostname("")
    assert exc_info.value.code == "invalid_hostname"


def test_canonicalize_path():
    assert canonicalize_path("/api/leads") == "/api/leads"
    assert canonicalize_path("/") == "/"
    assert canonicalize_path("") == "/"
    assert canonicalize_path(None) == "/"
    assert canonicalize_path("  /test  ") == "/test"

    with pytest.raises(SourceResolutionError) as exc_info:
        canonicalize_path("api/leads")  # Missing leading /
    assert exc_info.value.code == "invalid_path_format"


@pytest.mark.asyncio
async def test_resolve_classification_by_source_key(db_session: AsyncSession):
    # This test requires database setup with test data
    # For now, test the error cases
    with pytest.raises(SourceResolutionError) as exc_info:
        await resolve_classification(
            session=db_session,
            request=None,
            source_id=None,
            source_key="nonexistent-key",
        )
    assert exc_info.value.code == "invalid_source_key"


@pytest.mark.asyncio
async def test_resolve_classification_missing_inputs(db_session: AsyncSession):
    with pytest.raises(SourceResolutionError) as exc_info:
        await resolve_classification(
            session=db_session,
            request=None,
            source_id=None,
            source_key=None,
        )
    assert exc_info.value.code == "missing_resolution_inputs"

