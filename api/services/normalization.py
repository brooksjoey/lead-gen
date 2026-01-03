from __future__ import annotations

import re
from typing import Optional
from dataclasses import dataclass
from enum import Enum

class NormalizationError(Exception):
    """Base normalization error."""
    pass

class PhoneFormat(Enum):
    E164 = "e164"
    DIGITS = "digits"
    INVALID = "invalid"

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

@dataclass(frozen=True)
class NormalizedContact:
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_format: PhoneFormat = PhoneFormat.INVALID

class ContactNormalizer:
    def __init__(self, require_e164: bool = True, min_phone_length: int = 7):
        self.require_e164 = require_e164
        self.min_phone_length = min_phone_length
    
    def normalize_email(self, email: Optional[str]) -> Optional[str]:
        if not email:
            return None
        
        normalized = email.strip().lower()
        if not _EMAIL_PATTERN.match(normalized):
            return None
        
        return normalized
    
    def normalize_phone(self, phone: Optional[str]) -> tuple[Optional[str], PhoneFormat]:
        if not phone:
            return None, PhoneFormat.INVALID
        
        cleaned = phone.strip()
        
        # Check E.164 format first
        if _E164_PATTERN.match(cleaned):
            return cleaned, PhoneFormat.E164
        
        # Extract digits
        digits = re.sub(r"\D+", "", cleaned)
        
        if len(digits) < self.min_phone_length:
            return None, PhoneFormat.INVALID
        
        # If E.164 required but not in that format, convert if possible
        if self.require_e164:
            # Try to infer country code (US/Canada default)
            if digits.startswith("1") and len(digits) == 11:
                return f"+{digits}", PhoneFormat.E164
            elif len(digits) == 10:
                return f"+1{digits}", PhoneFormat.E164
            else:
                return None, PhoneFormat.INVALID
        
        return digits, PhoneFormat.DIGITS
    
    def normalize_all(self, email: Optional[str], phone: Optional[str]) -> NormalizedContact:
        norm_email = self.normalize_email(email)
        norm_phone, phone_format = self.normalize_phone(phone)
        
        return NormalizedContact(
            email=norm_email,
            phone=norm_phone,
            phone_format=phone_format
        )

# Global instance with production defaults
normalizer = ContactNormalizer(require_e164=True, min_phone_length=10)

def normalize_email(email: Optional[str]) -> Optional[str]:
    """Production alias for email normalization."""
    return normalizer.normalize_email(email)

def normalize_phone(phone: Optional[str]) -> tuple[Optional[str], PhoneFormat]:
    """Production alias for phone normalization."""
    return normalizer.normalize_phone(phone)

def normalize_contact(email: Optional[str], phone: Optional[str]) -> NormalizedContact:
    """Production alias for full contact normalization."""
    return normalizer.normalize_all(email, phone)