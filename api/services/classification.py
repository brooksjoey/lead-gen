from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class SourceResolutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResolvedClassification:
    source_id: int
    offer_id: int
    market_id: int
    vertical_id: int


def canonicalize_source_key(source_key: str) -> str:
    """
    Canonicalize source_key: strip() only.
    Must match [A-Za-z0-9][A-Za-z0-9._:-]{1,127} (2-128 chars)
    """
    k = source_key.strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$", k):
        raise SourceResolutionError(
            code="invalid_source_key_format",
            message="source_key must match [A-Za-z0-9][A-Za-z0-9._:-]{1,127} after trimming",
        )
    return k


def canonicalize_hostname(host: Optional[str]) -> str:
    """
    Canonicalize hostname: lower-case; strip port.
    If missing Host header → fail
    """
    if not host:
        raise SourceResolutionError(
            code="missing_host_header",
            message="Host header is required for HTTP mapping resolution",
        )
    # Strip port if present
    hostname = host.split(":")[0].lower().strip()
    if not hostname:
        raise SourceResolutionError(
            code="invalid_hostname",
            message="Hostname cannot be empty",
        )
    return hostname


def canonicalize_path(path: Optional[str]) -> str:
    """
    Canonicalize path: must start with /; if empty → /
    """
    if not path or path.strip() == "":
        return "/"
    p = path.strip()
    if not p.startswith("/"):
        raise SourceResolutionError(
            code="invalid_path_format",
            message="Path must start with /",
        )
    return p


async def resolve_classification(
    *,
    session: AsyncSession,
    request: Optional[Request] = None,
    source_id: Optional[int] = None,
    source_key: Optional[str] = None,
) -> ResolvedClassification:
    """
    Deterministic source resolution algorithm per spec.
    
    Priority order:
    1. source_id (header or body)
    2. source_key (body)
    3. HTTP mapping (Host + request Path using sources.hostname + sources.path_prefix)
    """
    # Priority 1: source_id
    if source_id is not None:
        row = await session.execute(
            text(
                """
                SELECT
                  s.id        AS source_id,
                  s.offer_id  AS offer_id,
                  o.market_id AS market_id,
                  o.vertical_id AS vertical_id
                FROM sources s
                JOIN offers o ON o.id = s.offer_id
                WHERE s.is_active = true
                  AND s.id = :source_id
                LIMIT 1
                """
            ),
            {"source_id": int(source_id)},
        )
        rec = row.mappings().first()
        if not rec:
            raise SourceResolutionError("invalid_source", "source_id not found or inactive")
        return ResolvedClassification(
            source_id=int(rec["source_id"]),
            offer_id=int(rec["offer_id"]),
            market_id=int(rec["market_id"]),
            vertical_id=int(rec["vertical_id"]),
        )

    # Priority 2: source_key
    if source_key is not None:
        key = canonicalize_source_key(source_key)
        row = await session.execute(
            text(
                """
                SELECT
                  s.id            AS source_id,
                  s.offer_id      AS offer_id,
                  o.market_id     AS market_id,
                  o.vertical_id   AS vertical_id
                FROM sources s
                JOIN offers o ON o.id = s.offer_id
                WHERE s.is_active = true
                  AND s.source_key = :source_key
                LIMIT 1
                """
            ),
            {"source_key": key},
        )
        rec = row.mappings().first()
        if not rec:
            raise SourceResolutionError("invalid_source_key", "source_key not found or inactive")
        return ResolvedClassification(
            source_id=int(rec["source_id"]),
            offer_id=int(rec["offer_id"]),
            market_id=int(rec["market_id"]),
            vertical_id=int(rec["vertical_id"]),
        )

    # Priority 3: HTTP mapping (Host + Longest Path Prefix)
    if request is None:
        raise SourceResolutionError(
            "missing_resolution_inputs",
            "Either source_id, source_key, or HTTP request (for hostname/path mapping) must be provided",
        )

    hostname = canonicalize_hostname(request.headers.get("host"))
    path = canonicalize_path(request.url.path)

    # Query active sources with matching hostname and path prefix match
    row = await session.execute(
        text(
            """
            WITH candidates AS (
              SELECT
                s.id            AS source_id,
                s.offer_id      AS offer_id,
                o.market_id     AS market_id,
                o.vertical_id   AS vertical_id,
                s.path_prefix   AS path_prefix,
                LENGTH(COALESCE(s.path_prefix, '')) AS prefix_len
              FROM sources s
              JOIN offers o ON o.id = s.offer_id
              WHERE s.is_active = true
                AND s.hostname = :hostname
                AND (
                  s.path_prefix IS NULL
                  OR :path LIKE s.path_prefix || '%'
                )
            ),
            ranked AS (
              SELECT *
              FROM candidates
              ORDER BY prefix_len DESC, source_id ASC
            )
            SELECT *
            FROM ranked
            LIMIT 2
            """
        ),
        {"hostname": hostname, "path": path},
    )
    results = row.mappings().all()

    if len(results) == 0:
        raise SourceResolutionError("unmapped_source", f"No active source found for hostname={hostname}, path={path}")

    if len(results) == 1:
        rec = results[0]
        return ResolvedClassification(
            source_id=int(rec["source_id"]),
            offer_id=int(rec["offer_id"]),
            market_id=int(rec["market_id"]),
            vertical_id=int(rec["vertical_id"]),
        )

    # 2 rows: check if prefix_len is equal (ambiguous) or different (take longest)
    first_len = int(results[0]["prefix_len"])
    second_len = int(results[1]["prefix_len"])

    if first_len == second_len:
        raise SourceResolutionError(
            "ambiguous_source_mapping",
            f"Multiple sources match hostname={hostname}, path={path} with same prefix length={first_len}",
        )

    # Take first (longest prefix)
    rec = results[0]
    return ResolvedClassification(
        source_id=int(rec["source_id"]),
        offer_id=int(rec["offer_id"]),
        market_id=int(rec["market_id"]),
        vertical_id=int(rec["vertical_id"]),
    )

