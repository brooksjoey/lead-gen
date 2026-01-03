# api/services/lead_ingest.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.classification_resolver import ClassificationResult


@dataclass(frozen=True)
class LeadIngestResult:
    lead_id: int
    status: str
    source_id: int
    offer_id: int
    market_id: int
    vertical_id: int
    idempotency_key: str


_INSERT_IDEMPOTENT = text(
    """
    INSERT INTO leads (
      source_id, offer_id, market_id, vertical_id,
      idempotency_key,
      name, email, phone, zip, message,
      consent, gdpr_consent,
      utm_source, utm_medium, utm_campaign
    )
    VALUES (
      :source_id, :offer_id, :market_id, :vertical_id,
      :idempotency_key,
      :name, :email, :phone, :zip, :message,
      :consent, :gdpr_consent,
      :utm_source, :utm_medium, :utm_campaign
    )
    ON CONFLICT (source_id, idempotency_key)
    DO UPDATE SET updated_at = CURRENT_TIMESTAMP
    RETURNING
      id AS lead_id,
      status,
      source_id,
      offer_id,
      market_id,
      vertical_id,
      idempotency_key
"""
)


def _p(payload: Mapping[str, Any], key: str, default: Any = None) -> Any:
    v = payload.get(key, default)
    return default if v is None else v


async def ingest_lead(
    session: AsyncSession,
    *,
    payload: Mapping[str, Any],
    classification: ClassificationResult,
    idempotency_key: str,
) -> LeadIngestResult:
    params: Dict[str, Any] = {
        "source_id": classification.source_id,
        "offer_id": classification.offer_id,
        "market_id": classification.market_id,
        "vertical_id": classification.vertical_id,
        "idempotency_key": idempotency_key,
        "name": _p(payload, "name"),
        "email": _p(payload, "email"),
        "phone": _p(payload, "phone"),
        "zip": _p(payload, "zip"),
        "message": _p(payload, "message"),
        "consent": bool(_p(payload, "consent", False)),
        "gdpr_consent": bool(_p(payload, "gdpr_consent", True)),
        "utm_source": _p(payload, "utm_source"),
        "utm_medium": _p(payload, "utm_medium"),
        "utm_campaign": _p(payload, "utm_campaign"),
    }

    res = await session.execute(_INSERT_IDEMPOTENT, params)
    row = res.first()
    if row is None:
        raise RuntimeError("lead_ingest_failed")

    # Ensure persistence before returning (idempotency depends on commit durability).
    await session.commit()

    return LeadIngestResult(
        lead_id=int(row.lead_id),
        status=str(row.status),
        source_id=int(row.source_id),
        offer_id=int(row.offer_id),
        market_id=int(row.market_id),
        vertical_id=int(row.vertical_id),
        idempotency_key=str(row.idempotency_key),
    )

