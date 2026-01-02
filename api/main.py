from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.config import settings
from api.core.logging import configure_structlog, get_structlog_logger
from api.routes.buyers import router as buyers_router
from api.routes.ingest import router as ingest_router

configure_structlog()

app = FastAPI(title="LeadGen API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/health")
async def health():
    get_structlog_logger().info("health.check", status="healthy")
    return {
        "status": "healthy",
        "service": "leadgen_api",
        "environment": settings.environment,
        "version": "0.2.0",
        "database": "connected" if settings.database_url else "unknown"
    }


app.include_router(ingest_router, prefix="/api")
app.include_router(buyers_router, prefix="/api")
