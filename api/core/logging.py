# C:\work-spaces\lead-gen\lead-gen\api\core\logging.py
from __future__ import annotations

import logging
import sys

import structlog

from api.core.config import settings


def configure_structlog() -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_structlog_logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger()


def set_request_id(request_id: Optional[str] = None) -> None:
    """Set request ID in structlog context."""
    import structlog.contextvars
    if request_id:
        structlog.contextvars.bind_contextvars(request_id=request_id)
    else:
        structlog.contextvars.clear_contextvars()
