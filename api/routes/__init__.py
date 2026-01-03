# api/routes/__init__.py
"""
API route handlers organized by domain.
"""

from api.routes.buyers import router as buyers_router
from api.routes.leads import router as leads_router

__all__ = [
    "buyers_router",
    "leads_router",
]
