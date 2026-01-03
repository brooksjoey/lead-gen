from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.duplicate_detection import (
    DuplicatePolicy,
    DuplicateResult,
    detect_duplicate,
)


class ValidationError(Exception):
    def __init__(self, code: str, message: str, reason: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason


@dataclass(frozen=True)
class ValidationPolicy:
    id: int
    name: str
    version: int
    rules: Dict[str, Any]
    is_active: bool


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    reason: Optional[str] = None
    duplicate_result: Optional[DuplicateResult] = None


async def load_validation_policy(
    *, session: AsyncSession, offer_id: int
) -> ValidationPolicy:
    """
    Load validation policy for an offer.
    """
    row = await session.execute(
        text(
            """
            SELECT
              vp.id,
              vp.name,
              vp.version,
              vp.rules,
              vp.is_active
            FROM offers o
            JOIN validation_policies vp ON vp.id = o.validation_policy_id
            WHERE o.id = :offer_id
              AND vp.is_active = true
            LIMIT 1
            """
        ),
        {"offer_id": offer_id},
    )
    rec = row.mappings().first()
    if not rec:
        raise ValidationError(
            code="validation_policy_not_found",
            message=f"Validation policy not found for offer_id={offer_id}",
        )

    rules = rec["rules"]
    if not isinstance(rules, dict):
        raise ValidationError(
            code="invalid_validation_policy",
            message=f"Validation policy rules must be a JSON object, got {type(rules)}",
        )

    return ValidationPolicy(
        id=int(rec["id"]),
        name=str(rec["name"]),
        version=int(rec["version"]),
        rules=rules,
        is_active=bool(rec["is_active"]),
    )


def parse_duplicate_detection_policy(
    rules: Dict[str, Any]
) -> Optional[DuplicatePolicy]:
    """
    Parse duplicate_detection section from validation_policies.rules into DuplicatePolicy.
    """
    dup_config = rules.get("duplicate_detection")
    if not dup_config:
        return None

    if not isinstance(dup_config, dict):
        return None

    enabled = dup_config.get("enabled", False)
    if not enabled:
        return None

    # Extract required fields
    window_hours = int(dup_config.get("window_hours", 24))
    scope = dup_config.get("scope", "offer")
    keys = dup_config.get("keys", [])
    match_mode = dup_config.get("match_mode", "any")
    exclude_statuses = dup_config.get("exclude_statuses", [])
    include_sources = dup_config.get("include_sources", "any")
    action = dup_config.get("action", "reject")
    reason_code = dup_config.get("reason_code", "duplicate_recent")
    min_fields = dup_config.get("min_fields", ["phone"])

    normalize_config = dup_config.get("normalize", {})
    normalize_email = normalize_config.get("email", "lower_trim")
    normalize_phone = normalize_config.get("phone", "e164_or_digits")

    return DuplicatePolicy(
        enabled=True,
        window_hours=window_hours,
        scope=scope,
        keys=keys,
        match_mode=match_mode,
        exclude_statuses=exclude_statuses,
        include_sources=include_sources,
        action=action,
        reason_code=reason_code,
        min_fields=min_fields,
        normalize_email=normalize_email,
        normalize_phone=normalize_phone,
    )


async def validate_lead_fields(
    *, policy: ValidationPolicy, lead_data: Dict[str, Any]
) -> Optional[str]:
    """
    Evaluate field validation rules from policy.
    Returns None if valid, or reason string if invalid.
    """
    rules = policy.rules

    # Check required fields
    required_fields = rules.get("required_fields", [])
    for field in required_fields:
        if field not in lead_data or not lead_data.get(field):
            return f"Required field '{field}' is missing or empty"

    # Check allowed postal codes
    allowed_postal_codes = rules.get("allowed_postal_codes")
    if allowed_postal_codes:
        postal_code = lead_data.get("postal_code", "").strip().upper()
        if postal_code not in allowed_postal_codes:
            return f"Postal code '{postal_code}' not in allowed list"

    # Check allowed cities
    allowed_cities = rules.get("allowed_cities")
    if allowed_cities:
        city = lead_data.get("city", "").strip()
        if city and city not in allowed_cities:
            return f"City '{city}' not in allowed list"

    # Check allowed country codes
    allowed_country_codes = rules.get("allowed_country_codes")
    if allowed_country_codes:
        country_code = lead_data.get("country_code", "").strip().upper()
        if country_code not in allowed_country_codes:
            return f"Country code '{country_code}' not in allowed list"

    # Additional validation rules can be added here based on policy structure
    # All rules must be policy-driven, not hardcoded

    return None  # Valid


async def execute_validation(
    *,
    session: AsyncSession,
    lead_id: int,
) -> ValidationResult:
    """
    Execute validation pipeline for a lead:
    1. Load validation policy
    2. Execute duplicate detection (if enabled)
    3. Execute field validation
    4. Return validation result
    """
    # Load lead data
    lead_row = await session.execute(
        text(
            """
            SELECT
              id,
              offer_id,
              source_id,
              status,
              name,
              email,
              phone,
              country_code,
              postal_code,
              city,
              region_code,
              normalized_email,
              normalized_phone
            FROM leads
            WHERE id = :lead_id
            """
        ),
        {"lead_id": lead_id},
    )
    lead_rec = lead_row.mappings().first()
    if not lead_rec:
        raise ValidationError(
            code="lead_not_found",
            message=f"Lead with id={lead_id} not found",
        )

    if lead_rec["status"] != "received":
        # Already processed, return current state
        return ValidationResult(
            is_valid=lead_rec["status"] == "validated",
            reason=lead_rec.get("validation_reason"),
        )

    offer_id = int(lead_rec["offer_id"])
    source_id = int(lead_rec["source_id"])

    # Load validation policy
    policy = await load_validation_policy(session=session, offer_id=offer_id)

    # Step 1: Duplicate detection (if enabled)
    duplicate_policy = parse_duplicate_detection_policy(policy.rules)
    duplicate_result: Optional[DuplicateResult] = None

    if duplicate_policy:
        duplicate_result = await detect_duplicate(
            session=session,
            lead_id=lead_id,
            offer_id=offer_id,
            source_id=source_id,
            policy=duplicate_policy,
            phone=lead_rec["phone"],
            email=lead_rec["email"],
        )

        # If duplicate action is "reject", duplicate detection already transitioned to rejected
        if duplicate_result.is_duplicate and duplicate_result.action == "reject":
            # Commit the duplicate detection status change
            await session.commit()
            # Check current status
            status_row = await session.execute(
                text("SELECT status, validation_reason FROM leads WHERE id = :lead_id"),
                {"lead_id": lead_id},
            )
            status_rec = status_row.mappings().first()
            return ValidationResult(
                is_valid=False,
                reason=status_rec["validation_reason"] if status_rec else duplicate_policy.reason_code,
                duplicate_result=duplicate_result,
            )

    # Step 2: Field validation
    lead_data = {
        "name": lead_rec["name"],
        "email": lead_rec["email"],
        "phone": lead_rec["phone"],
        "country_code": lead_rec["country_code"],
        "postal_code": lead_rec["postal_code"],
        "city": lead_rec.get("city"),
        "region_code": lead_rec.get("region_code"),
    }

    validation_reason = await validate_lead_fields(policy=policy, lead_data=lead_data)

    if validation_reason:
        # Transition to rejected (guarded)
        await session.execute(
            text(
                """
                UPDATE leads
                SET
                  status = 'rejected',
                  validation_reason = :reason,
                  updated_at = CURRENT_TIMESTAMP
                WHERE id = :lead_id
                  AND status = 'received'
                """
            ),
            {
                "lead_id": lead_id,
                "reason": validation_reason,
            },
        )
        await session.commit()
        return ValidationResult(
            is_valid=False,
            reason=validation_reason,
            duplicate_result=duplicate_result,
        )

    # Step 3: Transition to validated (guarded)
    await session.execute(
        text(
            """
            UPDATE leads
            SET
              status = 'validated',
              validation_reason = NULL,
              updated_at = CURRENT_TIMESTAMP
            WHERE id = :lead_id
              AND status = 'received'
            """
        ),
        {"lead_id": lead_id},
    )
    await session.commit()

    return ValidationResult(
        is_valid=True,
        reason=None,
        duplicate_result=duplicate_result,
    )

