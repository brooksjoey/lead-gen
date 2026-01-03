from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Literal, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


MatchMode = Literal["any", "all"]
IncludeSources = Literal["any", "same_source_only"]
DuplicateAction = Literal["reject", "flag", "accept"]


class DuplicateDetectionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DuplicatePolicy:
    enabled: bool
    window_hours: int
    scope: Literal["offer"]
    keys: Sequence[Literal["phone", "email"]]
    match_mode: MatchMode
    exclude_statuses: Sequence[str]
    include_sources: IncludeSources
    action: DuplicateAction
    reason_code: str
    min_fields: Sequence[Literal["phone", "email"]]
    normalize_email: Literal["lower_trim"]
    normalize_phone: Literal["e164_or_digits"]


@dataclass(frozen=True)
class DuplicateResult:
    is_duplicate: bool
    action: Optional[DuplicateAction]
    matched_lead_id: Optional[int]
    matched_keys: Sequence[str]


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164_RE = re.compile(r"^\+[1-9]\d{7,15}$")


def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    e = email.strip().lower()
    if not e:
        return None
    # Syntax is validated elsewhere; here we only ensure it is plausible.
    if not _EMAIL_RE.match(e):
        return None
    return e


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    p = phone.strip()
    if not p:
        return None
    if _E164_RE.match(p):
        return p
    digits = re.sub(r"\D+", "", p)
    if len(digits) < 7:
        return None
    return digits


def _require_min_fields(
    *,
    policy: DuplicatePolicy,
    normalized_phone: Optional[str],
    normalized_email: Optional[str],
) -> bool:
    for f in policy.min_fields:
        if f == "phone" and not normalized_phone:
            return False
        if f == "email" and not normalized_email:
            return False
    return True


async def detect_duplicate(
    *,
    session: AsyncSession,
    lead_id: int,
    offer_id: int,
    source_id: int,
    policy: DuplicatePolicy,
    phone: Optional[str],
    email: Optional[str],
) -> DuplicateResult:
    if not policy.enabled:
        return DuplicateResult(False, None, None, ())

    if policy.scope != "offer":
        raise DuplicateDetectionError("invalid_policy_scope", "duplicate detection scope must be 'offer'")

    norm_phone = normalize_phone(phone) if "phone" in policy.keys else None
    norm_email = normalize_email(email) if "email" in policy.keys else None

    if not _require_min_fields(policy=policy, normalized_phone=norm_phone, normalized_email=norm_email):
        return DuplicateResult(False, None, None, ())

    if not norm_phone and not norm_email:
        return DuplicateResult(False, None, None, ())

    window_hours = int(policy.window_hours)
    if window_hours <= 0 or window_hours > 24 * 365:
        raise DuplicateDetectionError("invalid_window_hours", "window_hours must be within (0, 8760]")

    include_sources = policy.include_sources
    match_mode = policy.match_mode

    # Candidate selection SQL: fetch the best match (most recent) and which keys matched.
    # We ignore the current lead_id and only look back within the window.
    sql = """
    WITH candidates AS (
      SELECT
        l.id AS matched_lead_id,
        l.created_at AS matched_created_at,
        (CASE WHEN :norm_phone IS NOT NULL AND l.normalized_phone = :norm_phone THEN 1 ELSE 0 END) AS phone_match,
        (CASE WHEN :norm_email IS NOT NULL AND l.normalized_email = :norm_email THEN 1 ELSE 0 END) AS email_match
      FROM leads l
      WHERE l.offer_id = :offer_id
        AND l.id <> :lead_id
        AND l.created_at >= (CURRENT_TIMESTAMP - (:window_hours::int * INTERVAL '1 hour'))
        AND (l.status <> ALL(:exclude_statuses))
        AND (:include_sources_any OR l.source_id = :source_id)
        AND (
          (:norm_phone IS NOT NULL AND l.normalized_phone = :norm_phone)
          OR
          (:norm_email IS NOT NULL AND l.normalized_email = :norm_email)
        )
    ),
    filtered AS (
      SELECT *
      FROM candidates
      WHERE
        CASE
          WHEN :match_mode = 'any' THEN (phone_match = 1 OR email_match = 1)
          WHEN :match_mode = 'all' THEN
            (
              (:norm_phone IS NULL OR phone_match = 1)
              AND
              (:norm_email IS NULL OR email_match = 1)
              AND
              -- for 'all' ensure both keys requested are present and match
              (CASE
                 WHEN (:norm_phone IS NOT NULL AND :norm_email IS NOT NULL) THEN (phone_match = 1 AND email_match = 1)
                 ELSE true
               END)
            )
          ELSE false
        END
    )
    SELECT
      matched_lead_id,
      phone_match,
      email_match
    FROM filtered
    ORDER BY matched_created_at DESC, matched_lead_id DESC
    LIMIT 1
    """

    res = await session.execute(
        text(sql),
        {
            "offer_id": offer_id,
            "source_id": source_id,
            "lead_id": lead_id,
            "window_hours": window_hours,
            "exclude_statuses": list(policy.exclude_statuses) if policy.exclude_statuses else [],
            "include_sources_any": include_sources == "any",
            "match_mode": match_mode,
            "norm_phone": norm_phone,
            "norm_email": norm_email,
        },
    )
    rec = res.mappings().first()
    if not rec:
        # Persist normalized values even if not a duplicate
        await _persist_normalized_fields(
            session=session,
            lead_id=lead_id,
            normalized_phone=norm_phone,
            normalized_email=norm_email,
        )
        return DuplicateResult(False, None, None, ())

    matched_lead_id = int(rec["matched_lead_id"])
    matched_keys = []
    if int(rec["phone_match"]) == 1:
        matched_keys.append("phone")
    if int(rec["email_match"]) == 1:
        matched_keys.append("email")

    # Persist normalized values + duplicate flags deterministically.
    await _mark_duplicate(
        session=session,
        lead_id=lead_id,
        normalized_phone=norm_phone,
        normalized_email=norm_email,
        matched_lead_id=matched_lead_id,
        action=policy.action,
        reason_code=policy.reason_code,
    )

    return DuplicateResult(True, policy.action, matched_lead_id, tuple(matched_keys))


async def _persist_normalized_fields(
    *,
    session: AsyncSession,
    lead_id: int,
    normalized_phone: Optional[str],
    normalized_email: Optional[str],
) -> None:
    await session.execute(
        text(
            """
            UPDATE leads
            SET
              updated_at = CURRENT_TIMESTAMP,
              normalized_phone = COALESCE(:normalized_phone, normalized_phone),
              normalized_email = COALESCE(:normalized_email, normalized_email)
            WHERE id = :lead_id
            """
        ),
        {
            "lead_id": lead_id,
            "normalized_phone": normalized_phone,
            "normalized_email": normalized_email,
        },
    )


async def _mark_duplicate(
    *,
    session: AsyncSession,
    lead_id: int,
    normalized_phone: Optional[str],
    normalized_email: Optional[str],
    matched_lead_id: int,
    action: DuplicateAction,
    reason_code: str,
) -> None:
    # Action semantics:
    # - reject: transition to rejected if still received (do not clobber later states)
    # - flag/accept: mark is_duplicate but do not change status
    if action == "reject":
        await session.execute(
            text(
                """
                UPDATE leads
                SET
                  updated_at = CURRENT_TIMESTAMP,
                  normalized_phone = COALESCE(:normalized_phone, normalized_phone),
                  normalized_email = COALESCE(:normalized_email, normalized_email),
                  is_duplicate = true,
                  duplicate_of_lead_id = :matched_lead_id,
                  status = CASE WHEN status = 'received' THEN 'rejected' ELSE status END,
                  validation_reason = CASE WHEN status = 'received' THEN :reason_code ELSE validation_reason END
                WHERE id = :lead_id
                """
            ),
            {
                "lead_id": lead_id,
                "normalized_phone": normalized_phone,
                "normalized_email": normalized_email,
                "matched_lead_id": matched_lead_id,
                "reason_code": reason_code,
            },
        )
    else:
        await session.execute(
            text(
                """
                UPDATE leads
                SET
                  updated_at = CURRENT_TIMESTAMP,
                  normalized_phone = COALESCE(:normalized_phone, normalized_phone),
                  normalized_email = COALESCE(:normalized_email, normalized_email),
                  is_duplicate = true,
                  duplicate_of_lead_id = :matched_lead_id
                WHERE id = :lead_id
                """
            ),
            {
                "lead_id": lead_id,
                "normalized_phone": normalized_phone,
                "normalized_email": normalized_email,
                "matched_lead_id": matched_lead_id,
            },
        )

