from fastapi import APIRouter, Depends

from api.core.config import settings
from api.core.logging import get_structlog_logger

router = APIRouter()


@router.get("/buyers")
async def list_buyers(environment: str = Depends(lambda: settings.environment)):
    get_structlog_logger().info("buyers.list", environment=environment)
    return {"buyers": [], "environment": environment}
