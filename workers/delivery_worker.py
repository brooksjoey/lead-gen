"""
Delivery worker for processing lead delivery jobs.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from api.core.config import settings
from api.core.logging import configure_structlog, get_structlog_logger
from api.services.delivery_engine import DeliveryError, execute_delivery

configure_structlog()
logger = get_structlog_logger()


async def process_delivery_job(lead_id: int) -> None:
    """
    Process a single delivery job.
    """
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        try:
            result = await execute_delivery(session=session, lead_id=lead_id)
            if result.success:
                logger.info(
                    "delivery.success",
                    lead_id=lead_id,
                    attempts=len(result.attempts),
                    final_status=result.final_status,
                )
            else:
                logger.warning(
                    "delivery.failed",
                    lead_id=lead_id,
                    attempts=len(result.attempts),
                    final_status=result.final_status,
                )
        except DeliveryError as e:
            logger.error(
                "delivery.error",
                lead_id=lead_id,
                code=e.code,
                message=e.message,
            )
        except Exception as e:
            logger.error(
                "delivery.unexpected_error",
                lead_id=lead_id,
                error=str(e),
                exc_info=True,
            )


async def worker_main() -> None:
    """
    Main worker loop.
    For now, processes jobs from command-line arguments or stdin.
    In production, would poll Redis queue or similar.
    """
    logger.info("delivery_worker.starting")

    # For now, accept lead_id from command line or stdin
    if len(sys.argv) > 1:
        lead_ids = [int(arg) for arg in sys.argv[1:]]
    else:
        # Read from stdin (one lead_id per line)
        lead_ids = []
        for line in sys.stdin:
            line = line.strip()
            if line:
                try:
                    lead_ids.append(int(line))
                except ValueError:
                    logger.warning("delivery_worker.invalid_lead_id", line=line)

    if not lead_ids:
        logger.warning("delivery_worker.no_jobs")
        return

    # Process jobs sequentially (can be parallelized with asyncio.gather)
    for lead_id in lead_ids:
        await process_delivery_job(lead_id)

    logger.info("delivery_worker.completed", processed=len(lead_ids))


if __name__ == "__main__":
    asyncio.run(worker_main())

