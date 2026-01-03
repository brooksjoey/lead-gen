# api/services/idempotency.py
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
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
        raise IdempotencyError("invalid_idempotency_key_format", "idempotency_key must match /^[A-Za-z0-9._:-]{16,128}$/ after trimming")
    return k

def _norm_email(email: str) -> str:
    return email.strip().lower()

def _norm_phone(phone: str) -> str:
    return re.sub(r"\s+", "", phone.strip())

def _norm_postal(postal_code: str) -> str:
    return postal_code.strip().upper()

def derive_idempotency_key(*, source_id: int, name: str, email: str, phone: str, country_code: str, postal_code: str, message: Optional[str]) -> str:
    if not email or not phone or not postal_code:
        raise IdempotencyError("idempotency_derivation_failed", "email, phone, and postal_code are required to derive idempotency_key")
    parts = [f"source_id={source_id}", f"name={name.strip()}", f"email={_norm_email(email)}", f"phone={_norm_phone(phone)}", f"country={country_code.strip().upper()}", f"postal={_norm_postal(postal_code)}", f"message={(message or '').strip()}"]
    payload = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

@dataclass(frozen=True)
class LeadInsertResult:
    lead_id: int
    created_new: bool

async def upsert_lead_stub_idempotent(*, session: AsyncSession, source_id: int, offer_id: int, market_id: int, vertical_id: int, source: str, name: str, email: str, phone: str, country_code: str, postal_code: str, city: Optional[str], region_code: Optional[str], message: Optional[str], utm_source: Optional[str], utm_medium: Optional[str], utm_campaign: Optional[str], ip_address: Optional[str], user_agent: Optional[str], idempotency_key: Optional[str]) -> LeadInsertResult:
    if idempotency_key:
        key = canonicalize_idempotency_key(idempotency_key)
    else:
        key = derive_idempotency_key(source_id=source_id, name=name, email=email, phone=phone, country_code=country_code, postal_code=postal_code, message=message)
    row = await session.execute(text("INSERT INTO leads (created_at, updated_at, market_id, vertical_id, offer_id, source_id, idempotency_key, source, name, email, phone, country_code, postal_code, city, region_code, message, utm_source, utm_medium, utm_campaign, ip_address, user_agent) VALUES (CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :market_id, :vertical_id, :offer_id, :source_id, :idempotency_key, :source, :name, :email, :phone, :country_code, :postal_code, :city, :region_code, :message, :utm_source, :utm_medium, :utm_campaign, :ip_address, :user_agent) ON CONFLICT (source_id, idempotency_key) DO UPDATE SET updated_at = CURRENT_TIMESTAMP RETURNING id AS lead_id, (xmax = 0) AS created_new"), {"market_id": market_id, "vertical_id": vertical_id, "offer_id": offer_id, "source_id": source_id, "idempotency_key": key, "source": source, "name": name, "email": email, "phone": phone, "country_code": country_code.strip().upper(), "postal_code": postal_code, "city": city, "region_code": region_code, "message": message, "utm_source": utm_source, "utm_medium": utm_medium, "utm_campaign": utm_campaign, "ip_address": ip_address, "user_agent": user_agent})
    rec = row.mappings().first()
    if not rec:
        raise IdempotencyError("idempotency_insert_failed", "Failed to insert or fetch lead row")
    return LeadInsertResult(lead_id=int(rec["lead_id"]), created_new=bool(rec["created_new"]))

async def resolve_idempotency_key(session: AsyncSession, source_id: int, idempotency_key: str) -> Optional[LeadInsertResult]:
    result = await session.execute(text("SELECT id, created_at FROM leads WHERE source_id = :source_id AND idempotency_key = :idempotency_key"), {"source_id": source_id, "idempotency_key": idempotency_key})
    row = result.mappings().first()
    if row:
        return LeadInsertResult(lead_id=int(row["id"]), created_new=False)
    return None