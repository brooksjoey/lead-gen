from __future__ import annotations

import re
from typing import Optional

# Email normalization regex (basic validation)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# E.164 phone format regex
_E164_RE = re.compile(r"^\+[1-9]\d{7,15}$")


def normalize_email(email: Optional[str]) -> Optional[str]:
    """
    Normalize email: lower_trim
    - strip(), lowercase
    - empty → NULL
    """
    if not email:
        return None
    e = email.strip().lower()
    if not e:
        return None
    # Basic syntax validation
    if not _EMAIL_RE.match(e):
        return None
    return e


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """
    Normalize phone: e164_or_digits
    - If already E.164 (+ followed by digits, length 8-16), keep
    - Else strip all non-digits
    - If result length < 7 → NULL
    """
    if not phone:
        return None
    p = phone.strip()
    if not p:
        return None
    # Check if already E.164 format
    if _E164_RE.match(p):
        return p
    # Strip all non-digits
    digits = re.sub(r"\D+", "", p)
    if len(digits) < 7:
        return None
    return digits

