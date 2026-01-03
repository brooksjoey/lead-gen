from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class IdempotencyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonicalize_idempotency_key(key: str) -> str:
    k = key.strip()
    if not _IDEMPOTENCY_RE.match(k):
        raise IdempotencyError(
            code="invalid_idempotency_key_format",
            message="idempotency_key must match /^[A-Za-z0-9._:-]{16,128}$/ after trimming",
        )
    return k


def _norm_email(email: str) -> str:
    return email.strip().lower()


def _norm_phone(phone: str) -> str:
    # Minimal normalization: remove whitespace; do not strip symbols aggressively here unless
    # your upstream already canonicalizes to E.164.
    return re.sub(r"\s+", "", phone.strip())


def _norm_postal(postal_code: str) -> str:
    return postal_code.strip().upper()


def derive_idempotency_key(
    *,
    source_id: int,
    name: str,
    email: str,
    phone: str,
    country_code: str,
    postal_code: str,
    message: Optional[str],
) -> str:
    """
    Deterministic server-side idempotency key derivation.

    Properties:
    - scoped by source_id
    - stable across restarts
    - uses fields that define "same submission"
    - SHA-256 hex => 64 chars (always valid)
    """
    if not email or not phone or not postal_code:
        raise IdempotencyError(
            code="idempotency_derivation_failed",
            message="email, phone, and postal_code are required to derive idempotency_key",
        )

    parts = [
        f"source_id={source_id}",
        f"name={name.strip()}",
        f"email={_norm_email(email)}",
        f"phone={_norm_phone(phone)}",
        f"country={country_code.strip().upper()}",
        f"postal={_norm_postal(postal_code)}",
        f"message={(message or '').strip()}",
    ]
    payload = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()  # 64 chars, hex


@dataclass(frozen=True)
class LeadInsertResult:
    lead_id: int
    created_new: bool


async def upsert_lead_stub_idempotent(
    *,
    session: AsyncSession,
    # classification (already resolved)
    source_id: int,
    offer_id: int,
    market_id: int,
    vertical_id: int,
    # lead payload
    source: str,
    name: str,
    email: str,
    phone: str,
    country_code: str,
    postal_code: str,
    city: Optional[str],
    region_code: Optional[str],
    message: Optional[str],
    utm_source: Optional[str],
    utm_medium: Optional[str],
    utm_campaign: Optional[str],
    ip_address: Optional[str],
    user_agent: Optional[str],
    # idempotency
    idempotency_key: Optional[str],
    # normalized fields for duplicate detection
    normalized_email: Optional[str] = None,
    normalized_phone: Optional[str] = None,
    now: Optional[datetime] = None,
) -> LeadInsertResult:
    """
    Creates (or reuses) a lead row deterministically keyed by (source_id, idempotency_key).

    This function ONLY establishes the immutable identity row and classification binding.
    Subsequent phases (validation/routing/billing) MUST operate on lead_id and be idempotent
    in their own right (status transitions guarded by WHERE clauses / expected state).
    """
    if now is None:
        # Use DB time for authoritative timestamps; this is only used if you want to store updated_at.
        pass

    if idempotency_key:
        key = canonicalize_idempotency_key(idempotency_key)
    else:
        key = derive_idempotency_key(
            source_id=source_id,
            name=name,
            email=email,
            phone=phone,
            country_code=country_code,
            postal_code=postal_code,
            message=message,
        )

    # Concurrency-safe upsert: return the existing lead id if it already exists.
    # DO UPDATE is a no-op update that allows RETURNING always.
    row = await session.execute(
        text(
            """
            INSERT INTO leads (
              created_at,
              updated_at,
              market_id,
              vertical_id,
              offer_id,
              source_id,
              idempotency_key,
              source,
              name,
              email,
              phone,
              country_code,
              postal_code,
              city,
              region_code,
              message,
              utm_source,
              utm_medium,
              utm_campaign,
              ip_address,
              user_agent,
              normalized_email,
              normalized_phone
            )
            VALUES (
              CURRENT_TIMESTAMP,
              CURRENT_TIMESTAMP,
              :market_id,
              :vertical_id,
              :offer_id,
              :source_id,
              :idempotency_key,
              :source,
              :name,
              :email,
              :phone,
              :country_code,
              :postal_code,
              :city,
              :region_code,
              :message,
              :utm_source,
              :utm_medium,
              :utm_campaign,
              :ip_address,
              :user_agent,
              :normalized_email,
              :normalized_phone
            )
            ON CONFLICT (source_id, idempotency_key)
            DO UPDATE SET
              updated_at = CURRENT_TIMESTAMP
            RETURNING
              id AS lead_id,
              (xmax = 0) AS created_new
            """
        ),
        {
            "market_id": market_id,
            "vertical_id": vertical_id,
            "offer_id": offer_id,
            "source_id": source_id,
            "idempotency_key": key,
            "source": source,
            "name": name,
            "email": email,
            "phone": phone,
            "country_code": country_code.strip().upper(),
            "postal_code": postal_code,
            "city": city,
            "region_code": region_code,
            "message": message,
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": utm_campaign,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "normalized_email": normalized_email,
            "normalized_phone": normalized_phone,
        },
    )
    rec = row.mappings().first()
    if not rec:
        # Should never happen; indicates a DB-level issue.
        raise IdempotencyError("idempotency_insert_failed", "Failed to insert or fetch lead row")

    return LeadInsertResult(
        lead_id=int(rec["lead_id"]),
        created_new=bool(rec["created_new"]),
    )

