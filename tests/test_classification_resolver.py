# tests/test_classification_resolver.py
import asyncio
from types import SimpleNamespace

import pytest

from api.services.classification_resolver import (
    ClassificationError,
    resolve_classification,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Session:
    def __init__(self, *, by_id=None, by_key=None, by_http=None):
        self._by_id = by_id
        self._by_key = by_key
        self._by_http = by_http

    async def execute(self, stmt, params):
        sql = str(stmt).lower()
        if "where s.id" in sql:
            return _Result(self._by_id(params))
        if "where s.source_key" in sql:
            return _Result(self._by_key(params))
        if "with candidates" in sql:
            return _Result(self._by_http(params))
        raise AssertionError("unexpected query")


def _row(source_id, offer_id, market_id, vertical_id, prefix_len=None):
    data = dict(
        source_id=source_id,
        offer_id=offer_id,
        market_id=market_id,
        vertical_id=vertical_id,
    )
    if prefix_len is not None:
        data["prefix_len"] = prefix_len
    return SimpleNamespace(**data)


def test_resolve_by_source_id_success():
    s = _Session(
        by_id=lambda p: [_row(10, 20, 30, 40)],
        by_key=lambda p: [],
        by_http=lambda p: [],
    )
    out = asyncio.run(resolve_classification(s, source_id=10))
    assert out.source_id == 10
    assert out.offer_id == 20
    assert out.market_id == 30
    assert out.vertical_id == 40


def test_resolve_by_source_id_missing():
    s = _Session(
        by_id=lambda p: [],
        by_key=lambda p: [],
        by_http=lambda p: [],
    )
    err = None
    try:
        asyncio.run(resolve_classification(s, source_id=999))
    except ClassificationError as e:
        err = e
    assert err is not None
    assert err.code == "invalid_source"
    assert err.http_status == 400


def test_resolve_by_source_key_success():
    s = _Session(
        by_id=lambda p: [],
        by_key=lambda p: [_row(11, 21, 31, 41)],
        by_http=lambda p: [],
    )
    out = asyncio.run(resolve_classification(s, source_key="lp.austin.plumbing"))
    assert out.source_id == 11
    assert out.offer_id == 21
    assert out.market_id == 31
    assert out.vertical_id == 41


def test_resolve_by_source_key_invalid_format():
    s = _Session(
        by_id=lambda p: [],
        by_key=lambda p: [],
        by_http=lambda p: [],
    )
    with pytest.raises(ClassificationError) as ei:
        asyncio.run(resolve_classification(s, source_key=" bad key "))
    e = ei.value
    assert e.code == "invalid_source_key"
    assert e.http_status == 400


def test_resolve_by_http_unmapped():
    s = _Session(
        by_id=lambda p: [],
        by_key=lambda p: [],
        by_http=lambda p: [],
    )
    with pytest.raises(ClassificationError) as ei:
        asyncio.run(resolve_classification(s, request_host="example.com", request_path="/x"))
    e = ei.value
    assert e.code == "unmapped_source"
    assert e.http_status == 400


def test_resolve_by_http_single_best_match():
    s = _Session(
        by_id=lambda p: [],
        by_key=lambda p: [],
        by_http=lambda p: [_row(12, 22, 32, 42, prefix_len=5)],
    )
    out = asyncio.run(resolve_classification(s, request_host="Example.COM:443", request_path="/a/b"))
    assert out.source_id == 12


def test_resolve_by_http_ambiguous_same_prefix_len():
    s = _Session(
        by_id=lambda p: [],
        by_key=lambda p: [],
        by_http=lambda p: [
            _row(100, 200, 300, 400, prefix_len=3),
            _row(101, 201, 301, 401, prefix_len=3),
        ],
    )
    with pytest.raises(ClassificationError) as ei:
        asyncio.run(resolve_classification(s, request_host="example.com", request_path="/x"))
    e = ei.value
    assert e.code == "ambiguous_source_mapping"
    assert e.http_status == 409


def test_resolve_by_http_two_rows_different_prefix_len_picks_longest():
    s = _Session(
        by_id=lambda p: [],
        by_key=lambda p: [],
        by_http=lambda p: [
            _row(110, 210, 310, 410, prefix_len=10),
            _row(111, 211, 311, 411, prefix_len=2),
        ],
    )
    out = asyncio.run(resolve_classification(s, request_host="example.com", request_path="/x/y/z"))
    assert out.source_id == 110
