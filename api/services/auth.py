# api/services/auth.py
from typing import Dict
from fastapi import Depends, HTTPException, status

def get_current_user() -> Dict:
    """Stub auth function - returns empty user dict."""
    return {}

def require_role(role: str):
    """Stub role requirement - no-op for now."""
    def _check(user: Dict = Depends(get_current_user)) -> Dict:
        return user
    return _check
