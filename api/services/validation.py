"""Simple validation functions for lead data."""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from api.services.normalization import normalize_email, normalize_phone, PhoneFormat


def validate_email(email: Optional[str]) -> bool:
    """Validate email format."""
    if not email:
        return False
    normalized = normalize_email(email)
    return normalized is not None


def validate_phone_number(phone: Optional[str]) -> bool:
    """Validate phone number format."""
    if not phone:
        return False
    normalized, format_type = normalize_phone(phone)
    return normalized is not None and format_type != PhoneFormat.INVALID


def validate_zip_code(zip_code: Optional[str], country_code: str = "US") -> bool:
    """Validate postal/zip code format."""
    if not zip_code:
        return False
    
    zip_code = zip_code.strip()
    
    if country_code == "US":
        # US ZIP: 5 digits or 5+4 format
        us_zip_pattern = re.compile(r"^\d{5}(-\d{4})?$")
        return bool(us_zip_pattern.match(zip_code))
    elif country_code == "CA":
        # Canadian postal code: A1A 1A1 format
        ca_postal_pattern = re.compile(r"^[A-Za-z]\d[A-Za-z] ?\d[A-Za-z]\d$")
        return bool(ca_postal_pattern.match(zip_code))
    
    # Default: non-empty string
    return len(zip_code) > 0


def validate_lead_data(lead_data: Dict) -> List[str]:
    """Validate lead data and return list of errors."""
    errors = []
    
    # Required fields
    if not lead_data.get("name"):
        errors.append("name is required")
    
    if not lead_data.get("email") and not lead_data.get("phone"):
        errors.append("email or phone is required")
    
    # Email validation
    if lead_data.get("email") and not validate_email(lead_data["email"]):
        errors.append("invalid email format")
    
    # Phone validation
    if lead_data.get("phone") and not validate_phone_number(lead_data["phone"]):
        errors.append("invalid phone number format")
    
    # Postal code validation
    if lead_data.get("postal_code"):
        country_code = lead_data.get("country_code", "US")
        if not validate_zip_code(lead_data["postal_code"], country_code):
            errors.append(f"invalid postal code format for {country_code}")
    
    return errors


async def deduplicate_leads(
    session,
    lead_data: Dict,
    window_hours: int = 24,
) -> Optional[Dict]:
    """Check for duplicate leads and return duplicate if found."""
    # This is a placeholder - actual deduplication should use duplicate_detection service
    # For now, return None (no duplicate found)
    # In production, this should call the proper duplicate detection service
    return None

