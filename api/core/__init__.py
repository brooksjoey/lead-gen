# api/core/__init__.py
"""
Core package for configuration, logging, and shared utilities.
"""

from api.core.config import Settings, settings
from api.core.logging import configure_structlog, get_structlog_logger

__all__ = [
    "Settings",
    "settings",
    "configure_structlog",
    "get_structlog_logger",
]
