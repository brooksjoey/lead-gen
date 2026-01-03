# api/services/classification_resolver.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")


@dataclass(frozen=True)
class ClassificationResult:
    source_id: int
    offer_id: int
    market_id: int
    vertical_id: int


class ClassificationError(Exception):
    __slots__ = ("code", "http_status", "details")

    def __init__(self, code: str, http_status: int, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.details = dict(details or {})


def canonicalize_source_key(source_key: str) -> str:
    k = source_key.strip()
    if not _SOURCE_KEY_RE.match(k):
        raise ClassificationError(
            code="invalid_source_key",
            http_status=400,
            details={"source_key": source_key},
        )
    return k


def canonicalize_hostname(host: str) -> str:
    if not host:
        raise ClassificationError(code="unmapped_source", http_status=400, details={"reason": "missing_host"})
    h = host.strip().lower()
    if not h:
        raise ClassificationError(code="unmapped_source", http_status=400, details={"reason": "missing_host"})
    if ":" in h:
        h = h.split(":", 1)[0]
    if not h:
        raise ClassificationError(code="unmapped_source", http_status=400, details={"reason": "missing_host"})
    return h


def canonicalize_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return "/"
    return p if p.startswith("/") else f"/{p}"


_SQL_BY_ID = text(
    """
    SELECT
      s.id AS source_id,
      s.offer_id AS offer_id,
      o.market_id AS market_id,
      o.vertical_id AS vertical_id
    FROM sources s
    JOIN offers o ON o.id = s.offer_id
    WHERE s.is_active = TRUE
      AND s.id = :source_id
    LIMIT 1
"""
)

_SQL_BY_KEY = text(
    """
    SELECT
      s.id AS source_id,
      s.offer_id AS offer_id,
      o.market_id AS market_id,
      o.vertical_id AS vertical_id
    FROM sources s
    JOIN offers o ON o.id = s.offer_id
    WHERE s.is_active = TRUE
      AND s.source_key = :source_key
    LIMIT 1
"""
)

_SQL_BY_HTTP = text(
    """
    WITH candidates AS (
      SELECT
        s.id AS source_id,
        s.offer_id AS offer_id,
        o.market_id AS market_id,
        o.vertical_id AS vertical_id,
        s.path_prefix AS path_prefix,
        LENGTH(COALESCE(s.path_prefix, '')) AS prefix_len
      FROM sources s
      JOIN offers o ON o.id = s.offer_id
      WHERE s.is_active = TRUE
        AND s.hostname = :hostname
        AND (
          s.path_prefix IS NULL
          OR :path LIKE s.path_prefix || '%'
        )
    )
    SELECT
      source_id,
      offer_id,
      market_id,
      vertical_id,
      prefix_len
    FROM candidates
    ORDER BY prefix_len DESC, source_id ASC
    LIMIT 2
"""
)


def _row_to_result(row: Any) -> ClassificationResult:
    return ClassificationResult(
        source_id=int(row.source_id),
        offer_id=int(row.offer_id),
        market_id=int(row.market_id),
        vertical_id=int(row.vertical_id),
    )


async def resolve_classification(
    session: AsyncSession,
    *,
    source_id: Optional[int] = None,
    source_key: Optional[str] = None,
    request_host: Optional[str] = None,
    request_path: Optional[str] = None,
) -> ClassificationResult:
    if source_id is not None:
        res = await session.execute(_SQL_BY_ID, {"source_id": int(source_id)})
        row = res.first()
        if row is None:
            raise ClassificationError(code="invalid_source", http_status=400, details={"source_id": source_id})
        return _row_to_result(row)

    if source_key is not None:
        k = canonicalize_source_key(source_key)
        res = await session.execute(_SQL_BY_KEY, {"source_key": k})
        row = res.first()
        if row is None:
            raise ClassificationError(code="invalid_source_key", http_status=400, details={"source_key": k})
        return _row_to_result(row)

    hostname = canonicalize_hostname(request_host or "")
    path = canonicalize_path(request_path or "/")

    res = await session.execute(_SQL_BY_HTTP, {"hostname": hostname, "path": path})
    rows = res.fetchall()

    if not rows:
        raise ClassificationError(
            code="unmapped_source",
            http_status=400,
            details={"hostname": hostname, "path": path},
        )

    if len(rows) == 1:
        return _row_to_result(rows[0])

    first, second = rows[0], rows[1]
    if int(first.prefix_len) == int(second.prefix_len):
        raise ClassificationError(
            code="ambiguous_source_mapping",
            http_status=409,
            details={
                "hostname": hostname,
                "path": path,
                "candidate_source_ids": [int(first.source_id), int(second.source_id)],
                "prefix_len": int(first.prefix_len),
            },
        )

    return _row_to_result(first)
