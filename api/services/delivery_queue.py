"""
Delivery queue integration for enqueueing delivery jobs.
For now, uses simple in-memory queue or direct execution.
In production, would integrate with Redis Streams or RQ.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_structlog_logger
from api.services.delivery_engine import execute_delivery

logger = get_structlog_logger()


async def enqueue_delivery(
    *,
    session: AsyncSession,
    lead_id: int,
) -> None:
    """
    Enqueue a delivery job for a lead.
    
    For now, executes delivery directly (synchronous enqueue).
    In production, would add job to Redis queue and return immediately.
    """
    logger.info("delivery.enqueued", lead_id=lead_id)
    
    # Direct execution for now (can be replaced with queue push)
    try:
        result = await execute_delivery(session=session, lead_id=lead_id)
        if result.success:
            logger.info("delivery.completed", lead_id=lead_id)
        else:
            logger.warning("delivery.failed", lead_id=lead_id, attempts=len(result.attempts))
    except Exception as e:
        logger.error("delivery.enqueue_error", lead_id=lead_id, error=str(e))
        raise

