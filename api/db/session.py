# C:\work-spaces\lead-gen\lead-gen\api\db\session.py
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from api.core.config import settings
from api.core.exceptions import DatabaseError
from api.core.logging import get_structlog_logger

logger = get_structlog_logger()

# Global engine instance
engine: Optional[AsyncEngine] = None
AsyncSessionLocal: Optional[async_sessionmaker[AsyncSession]] = None


def create_database_engine() -> AsyncEngine:
    """Create and configure the async database engine."""
    global engine, AsyncSessionLocal
    
    if engine is not None:
        return engine
    
    # Configure engine based on environment
    if settings.is_testing:
        # Use NullPool for tests to ensure clean state
        engine = create_async_engine(
            settings.database_url,
            poolclass=NullPool,
            echo=settings.debug,
            future=True,
            connect_args={"server_settings": {"jit": "off"}},
        )
    else:
        # Production/development pool configuration
        engine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            pool_recycle=settings.database_pool_recycle,
            pool_pre_ping=True,  # Verify connections before using
            echo=settings.debug,
            future=True,
            connect_args={
                "command_timeout": 60,
                "server_settings": {
                    "application_name": "leadgen_api",
                    "jit": "off" if settings.is_development else "on",
                }
            },
        )
    
    # Create session factory
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    
    # Add event listeners
    @event.listens_for(engine.sync_engine, "connect")
    def set_search_path(dbapi_connection, connection_record):
        """Set PostgreSQL search path on connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("SET search_path TO public")
        cursor.close()
    
    logger.info(
        "database.engine.created",
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        testing=settings.is_testing,
    )
    
    return engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    global AsyncSessionLocal
    
    if AsyncSessionLocal is None:
        create_database_engine()
    
    session = AsyncSessionLocal()
    
    try:
        # Set statement timeout for this session
        await session.execute(
            text(f"SET statement_timeout = {settings.lead_validation_timeout * 1000}")
        )
        
        # Verify connection is alive
        await session.execute(text("SELECT 1"))
        
        yield session
        
    except SQLAlchemyError as e:
        logger.error("database.session_error", error=str(e))
        await session.rollback()
        raise DatabaseError(
            message="Database session error",
            details={"error": str(e)},
        ) from e
    
    finally:
        await session.close()


@asynccontextmanager
async def transaction_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database transactions."""
    session = AsyncSessionLocal()
    
    try:
        # Begin transaction
        await session.begin()
        
        # Set statement timeout
        await session.execute(
            text(f"SET statement_timeout = {settings.lead_validation_timeout * 1000}")
        )
        
        yield session
        
        # Commit if no exceptions
        await session.commit()
        
    except SQLAlchemyError as e:
        await session.rollback()
        logger.error("database.transaction_error", error=str(e))
        raise DatabaseError(
            message="Database transaction failed",
            details={"error": str(e)},
        ) from e
    
    finally:
        await session.close()


async def get_connection() -> AsyncGenerator[AsyncConnection, None]:
    """Get raw database connection."""
    global engine
    
    if engine is None:
        create_database_engine()
    
    async with engine.connect() as connection:
        try:
            yield connection
        finally:
            await connection.close()


async def health_check() -> dict:
    """Check database health."""
    try:
        async with get_connection() as conn:
            # Check connection
            result = await conn.execute(text("SELECT 1"))
            row = result.fetchone()
            
            # Get database info
            db_info = await conn.execute(
                text("""
                    SELECT 
                        version() as version,
                        current_database() as database,
                        current_user as username,
                        inet_server_addr() as server_address,
                        inet_server_port() as server_port
                """)
            )
            info_row = db_info.fetchone()
            
            # Get connection stats
            stats = await conn.execute(
                text("""
                    SELECT 
                        count(*) as active_connections,
                        sum(case when state = 'active' then 1 else 0 end) as executing_queries
                    FROM pg_stat_activity 
                    WHERE datname = current_database()
                """)
            )
            stats_row = stats.fetchone()
            
            return {
                "status": "healthy" if row and row[0] == 1 else "unhealthy",
                "database": info_row._asdict() if info_row else {},
                "connections": stats_row._asdict() if stats_row else {},
                "timestamp": datetime.utcnow().isoformat(),
            }
            
    except Exception as e:
        logger.error("database.health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


async def execute_in_transaction(query: str, params: dict = None) -> Any:
    """Execute a single query in transaction."""
    async with transaction_session() as session:
        result = await session.execute(text(query), params or {})
        return result


# Initialize engine on module import
create_database_engine()