# C:\work-spaces\lead-gen\lead-gen\api\services\redis.py
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Union

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff

from api.core.config import settings
from api.core.exceptions import ServiceUnavailableError
from api.core.logging import get_structlog_logger

logger = get_structlog_logger(__name__)

# Global Redis connection pool
_redis_pool: Optional[ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None


async def init_redis_pool() -> None:
    """Initialize Redis connection pool."""
    global _redis_pool, _redis_client
    
    if _redis_pool is not None:
        return
    
    try:
        # Configure retry strategy
        retry = Retry(
            backoff=ExponentialBackoff(base=1, max_attempts=3),
            retries=3,
        )
        
        # Create connection pool
        _redis_pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            retry=retry,
            retry_on_error=[redis.ConnectionError, redis.TimeoutError],
            health_check_interval=30,
        )
        
        # Create Redis client
        _redis_client = redis.Redis(
            connection_pool=_redis_pool,
            decode_responses=True,
            encoding="utf-8",
        )
        
        # Test connection
        await _redis_client.ping()
        
        logger.info(
            "redis.connected",
            url=settings.redis_url,
            max_connections=settings.redis_max_connections,
        )
        
    except Exception as e:
        logger.error("redis.connection_failed", error=str(e))
        raise ServiceUnavailableError(
            message="Redis connection failed",
            details={"error": str(e), "url": settings.redis_url},
        )


async def get_redis_client() -> redis.Redis:
    """Get Redis client instance."""
    global _redis_client
    
    if _redis_client is None:
        await init_redis_pool()
    
    return _redis_client


async def close_redis_pool() -> None:
    """Close Redis connection pool."""
    global _redis_pool, _redis_client
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None
    
    logger.info("redis.connections_closed")


class RedisCache:
    """High-level Redis cache operations."""
    
    def __init__(self, redis_client: redis.Redis, prefix: str = "cache"):
        self.redis = redis_client
        self.prefix = prefix
    
    def _make_key(self, key: str) -> str:
        """Create namespaced key."""
        return f"{self.prefix}:{key}"
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache."""
        try:
            full_key = self._make_key(key)
            value = await self.redis.get(full_key)
            
            if value is None:
                return default
            
            # Try to decode JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
                
        except Exception as e:
            logger.error("cache.get_error", key=key, error=str(e))
            return default
    
    async def set(
        self,
        key: str,
        value: Any,
        expire: Optional[int] = None
    ) -> bool:
        """Set value in cache."""
        try:
            full_key = self._make_key(key)
            
            # Serialize value
            if isinstance(value, (dict, list, tuple, set)):
                value = json.dumps(value)
            
            if expire:
                await self.redis.setex(full_key, expire, value)
            else:
                await self.redis.set(full_key, value)
            
            return True
            
        except Exception as e:
            logger.error("cache.set_error", key=key, error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        try:
            full_key = self._make_key(key)
            result = await self.redis.delete(full_key)
            return result > 0
            
        except Exception as e:
            logger.error("cache.delete_error", key=key, error=str(e))
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            full_key = self._make_key(key)
            return await self.redis.exists(full_key) > 0
            
        except Exception as e:
            logger.error("cache.exists_error", key=key, error=str(e))
            return False
    
    async def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment counter value."""
        try:
            full_key = self._make_key(key)
            return await self.redis.incrby(full_key, amount)
            
        except Exception as e:
            logger.error("cache.incr_error", key=key, error=str(e))
            return None
    
    async def decr(self, key: str, amount: int = 1) -> Optional[int]:
        """Decrement counter value."""
        try:
            full_key = self._make_key(key)
            return await self.redis.decrby(full_key, amount)
            
        except Exception as e:
            logger.error("cache.decr_error", key=key, error=str(e))
            return None
    
    async def get_or_set(
        self,
        key: str,
        callback,
        expire: Optional[int] = None,
        force_refresh: bool = False
    ) -> Any:
        """Get value from cache or set it using callback."""
        if not force_refresh:
            cached = await self.get(key)
            if cached is not None:
                return cached
        
        # Generate value using callback
        value = await callback() if asyncio.iscoroutinefunction(callback) else callback()
        
        # Store in cache
        await self.set(key, value, expire)
        
        return value
    
    async def clear_prefix(self, prefix: str) -> int:
        """Clear all keys with given prefix."""
        try:
            pattern = f"{self.prefix}:{prefix}:*"
            keys = []
            
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                return await self.redis.delete(*keys)
            
            return 0
            
        except Exception as e:
            logger.error("cache.clear_prefix_error", prefix=prefix, error=str(e))
            return 0


class RedisLock:
    """Distributed lock using Redis."""
    
    def __init__(self, redis_client: redis.Redis, key: str, timeout: int = 30):
        self.redis = redis_client
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.identifier = None
    
    async def acquire(self) -> bool:
        """Acquire distributed lock."""
        import uuid
        
        self.identifier = str(uuid.uuid4())
        
        try:
            # Try to set lock with NX (only if not exists) and EX (expire)
            acquired = await self.redis.set(
                self.key,
                self.identifier,
                ex=self.timeout,
                nx=True,
            )
            
            if acquired:
                logger.debug("lock.acquired", key=self.key, identifier=self.identifier[:8])
            
            return acquired
            
        except Exception as e:
            logger.error("lock.acquire_error", key=self.key, error=str(e))
            return False
    
    async def release(self) -> bool:
        """Release distributed lock."""
        if not self.identifier:
            return False
        
        try:
            # Use Lua script for atomic release
            lua_script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
            """
            
            result = await self.redis.eval(
                lua_script,
                1,
                self.key,
                self.identifier,
            )
            
            released = result > 0
            
            if released:
                logger.debug("lock.released", key=self.key, identifier=self.identifier[:8])
            
            return released
            
        except Exception as e:
            logger.error("lock.release_error", key=self.key, error=str(e))
            return False
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()


async def health_check() -> Dict[str, Any]:
    """Check Redis health."""
    try:
        client = await get_redis_client()
        
        # Test connection
        start_time = asyncio.get_event_loop().time()
        pong = await client.ping()
        response_time = (asyncio.get_event_loop().time() - start_time) * 1000
        
        if not pong:
            return {
                "status": "unhealthy",
                "error": "Ping failed",
                "response_time_ms": response_time,
            }
        
        # Get Redis info
        info = await client.info()
        
        return {
            "status": "healthy",
            "response_time_ms": response_time,
            "version": info.get("redis_version"),
            "memory": {
                "used_memory": info.get("used_memory"),
                "used_memory_human": info.get("used_memory_human"),
                "maxmemory": info.get("maxmemory"),
                "maxmemory_human": info.get("maxmemory_human"),
            },
            "clients": {
                "connected_clients": info.get("connected_clients"),
                "blocked_clients": info.get("blocked_clients"),
            },
            "stats": {
                "total_connections_received": info.get("total_connections_received"),
                "total_commands_processed": info.get("total_commands_processed"),
                "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec"),
            },
        }
        
    except Exception as e:
        logger.error("redis.health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "response_time_ms": None,
        }


# Global cache instance
cache: Optional[RedisCache] = None


async def get_cache() -> RedisCache:
    """Get global cache instance."""
    global cache
    
    if cache is None:
        client = await get_redis_client()
        cache = RedisCache(client)
    
    return cache