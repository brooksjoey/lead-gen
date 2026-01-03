from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from .logging import get_logger

logger = get_logger(__name__)

class RoutingStrategy(Enum):
    PRIORITY = "priority"
    ROUND_ROBIN = "round_robin"
    CAPACITY_WEIGHTED = "capacity_weighted"
    PERFORMANCE_BASED = "performance_based"
    EXCLUSIVE = "exclusive"

class RoutingError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

@dataclass(frozen=True)
class RoutingPolicy:
    id: int
    name: str
    version: int
    strategy: RoutingStrategy
    config: Dict[str, Any]
    fallback_strategy: Optional[RoutingStrategy] = None
    is_active: bool = True

@dataclass(frozen=True)
class BuyerCapacity:
    daily_used: int
    daily_limit: Optional[int]
    hourly_used: int
    hourly_limit: Optional[int]
    is_capped: bool

@dataclass(frozen=True)
class EligibleBuyer:
    buyer_id: int
    routing_priority: int
    price_per_lead: float
    capacity: BuyerCapacity
    performance_score: Optional[float] = None
    last_assigned: Optional[datetime] = None

@dataclass(frozen=True)
class RoutingResult:
    buyer_id: Optional[int]
    price: Optional[float]
    routing_policy_id: int
    strategy_used: RoutingStrategy
    execution_time_ms: float
    cache_hit: bool = False
    no_route_reason: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

class RoutingEngine:
    def __init__(self, redis_client: Optional[Redis] = None, cache_ttl: int = 300):
        self.redis = redis_client
        self.cache_ttl = cache_ttl
        self._strategy_handlers = {
            RoutingStrategy.PRIORITY: self._priority_strategy,
            RoutingStrategy.ROUND_ROBIN: self._round_robin_strategy,
            RoutingStrategy.CAPACITY_WEIGHTED: self._capacity_weighted_strategy,
            RoutingStrategy.EXCLUSIVE: self._exclusive_strategy,
        }
    
    async def route_lead(self, session: AsyncSession, lead_id: int) -> RoutingResult:
        start_time = datetime.now()
        execution_id = str(uuid4())
        
        try:
            logger.info("routing.start", 
                       lead_id=lead_id, 
                       execution_id=execution_id)
            
            # Load lead with lock to prevent concurrent routing
            lead = await self._get_lead_for_routing(session, lead_id)
            
            if lead.status != "validated":
                return RoutingResult(
                    buyer_id=lead.buyer_id,
                    price=lead.price,
                    routing_policy_id=0,
                    strategy_used=RoutingStrategy.PRIORITY,
                    execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                    no_route_reason=f"Lead not validated: {lead.status}"
                )
            
            # Check cache for recent routing decision
            cache_key = f"routing:{lead.offer_id}:{lead.postal_code}:{hashlib.md5(lead.email.encode()).hexdigest()[:8]}"
            cached_result = await self._get_cached_routing(cache_key)
            
            if cached_result:
                logger.info("routing.cache_hit", 
                           lead_id=lead_id, 
                           cache_key=cache_key)
                return RoutingResult(**cached_result, cache_hit=True)
            
            # Load routing policy
            policy = await self._load_routing_policy(session, lead.offer_id)
            
            # Check exclusivity first
            exclusive_buyer = await self._check_exclusivity(
                session, lead.offer_id, lead.postal_code, lead.city
            )
            
            if exclusive_buyer:
                strategy = RoutingStrategy.EXCLUSIVE
                selected_buyer = exclusive_buyer
                price = await self._get_buyer_price(session, lead.offer_id, exclusive_buyer)
            else:
                # Get eligible buyers
                eligible = await self._get_eligible_buyers(
                    session, lead.offer_id, lead.market_id, 
                    lead.postal_code, lead.city
                )
                
                if not eligible:
                    return RoutingResult(
                        buyer_id=None,
                        price=None,
                        routing_policy_id=policy.id,
                        strategy_used=policy.strategy,
                        execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                        no_route_reason="no_eligible_buyers"
                    )
                
                # Apply strategy
                handler = self._strategy_handlers.get(policy.strategy, self._priority_strategy)
                selected_buyer = await handler(eligible, policy.config)
                
                if not selected_buyer and policy.fallback_strategy:
                    fallback_handler = self._strategy_handlers.get(policy.fallback_strategy)
                    selected_buyer = await fallback_handler(eligible, policy.config)
                
                price = await self._get_buyer_price(session, lead.offer_id, selected_buyer)
                strategy = policy.strategy
            
            # Update lead with routing decision (guarded)
            updated = await self._update_lead_routing(
                session, lead_id, selected_buyer, price
            )
            
            if not updated:
                logger.warning("routing.concurrent_update",
                             lead_id=lead_id,
                             execution_id=execution_id)
                # Get current state
                current = await self._get_lead_for_routing(session, lead_id)
                return RoutingResult(
                    buyer_id=current.buyer_id,
                    price=current.price,
                    routing_policy_id=policy.id,
                    strategy_used=strategy,
                    execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                    warnings=["concurrent_routing_detected"]
                )
            
            result = RoutingResult(
                buyer_id=selected_buyer,
                price=price,
                routing_policy_id=policy.id,
                strategy_used=strategy,
                execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000
            )
            
            # Cache result
            await self._cache_routing(cache_key, result)
            
            logger.info("routing.complete",
                       lead_id=lead_id,
                       buyer_id=selected_buyer,
                       price=price,
                       strategy=strategy.value,
                       execution_ms=result.execution_time_ms)
            
            return result
            
        except Exception as e:
            logger.error("routing.error",
                        lead_id=lead_id,
                        execution_id=execution_id,
                        error=str(e),
                        traceback=True)
            raise RoutingError(
                code="routing_engine_failure",
                message=f"Routing failed for lead {lead_id}: {str(e)}",
                details={"execution_id": execution_id}
            )
    
    async def _get_lead_for_routing(self, session: AsyncSession, lead_id: int):
        """Load lead with FOR UPDATE SKIP LOCKED for concurrency control."""
        query = text("""
            SELECT 
                l.id, l.offer_id, l.market_id, l.status, l.postal_code, l.city,
                l.email, l.buyer_id, l.price,
                o.routing_policy_id
            FROM leads l
            JOIN offers o ON o.id = l.offer_id
            WHERE l.id = :lead_id
            FOR UPDATE SKIP LOCKED
        """)
        
        result = await session.execute(query, {"lead_id": lead_id})
        row = result.mappings().first()
        
        if not row:
            raise RoutingError(
                code="lead_not_found",
                message=f"Lead {lead_id} not found or locked"
            )
        
        return row
    
    async def _load_routing_policy(self, session: AsyncSession, offer_id: int) -> RoutingPolicy:
        query = text("""
            SELECT 
                rp.id, rp.name, rp.version, rp.config, rp.is_active
            FROM routing_policies rp
            JOIN offers o ON o.routing_policy_id = rp.id
            WHERE o.id = :offer_id AND rp.is_active = TRUE
        """)
        
        result = await session.execute(query, {"offer_id": offer_id})
        row = result.mappings().first()
        
        if not row:
            raise RoutingError(
                code="routing_policy_not_found",
                message=f"No active routing policy for offer {offer_id}"
            )
        
        config = row.config
        strategy_str = config.get("strategy", "priority")
        
        try:
            strategy = RoutingStrategy(strategy_str)
        except ValueError:
            strategy = RoutingStrategy.PRIORITY
        
        fallback = None
        if config.get("fallback_strategy"):
            try:
                fallback = RoutingStrategy(config["fallback_strategy"])
            except ValueError:
                pass
        
        return RoutingPolicy(
            id=row.id,
            name=row.name,
            version=row.version,
            strategy=strategy,
            config=config,
            fallback_strategy=fallback,
            is_active=row.is_active
        )
    
    async def _check_exclusivity(self, session: AsyncSession, offer_id: int, 
                                postal_code: str, city: Optional[str]) -> Optional[int]:
        conditions = []
        params = {"offer_id": offer_id}
        
        if postal_code:
            conditions.append("(scope_type = 'postal_code' AND scope_value = :postal_code)")
            params["postal_code"] = postal_code
        
        if city:
            conditions.append("(scope_type = 'city' AND scope_value = :city)")
            params["city"] = city
        
        if not conditions:
            return None
        
        where_clause = " OR ".join(conditions)
        
        query = text(f"""
            SELECT buyer_id 
            FROM offer_exclusivities 
            WHERE offer_id = :offer_id 
            AND is_active = TRUE 
            AND ({where_clause})
            LIMIT 1
        """)
        
        result = await session.execute(query, params)
        row = result.mappings().first()
        
        return row.buyer_id if row else None
    
    async def _get_eligible_buyers(self, session: AsyncSession, offer_id: int, 
                                  market_id: int, postal_code: str, 
                                  city: Optional[str]) -> List[EligibleBuyer]:
        # Complex query with service area matching and capacity checks
        query = text("""
            WITH eligible_base AS (
                SELECT 
                    bo.buyer_id,
                    bo.routing_priority,
                    COALESCE(bo.price_per_lead, o.default_price_per_lead) as price_per_lead,
                    bo.capacity_per_day,
                    bo.capacity_per_hour,
                    b.min_balance_required,
                    b.balance,
                    bo.pause_until,
                    bo.last_assigned
                FROM buyer_offers bo
                JOIN offers o ON o.id = bo.offer_id
                JOIN buyers b ON b.id = bo.buyer_id
                WHERE bo.offer_id = :offer_id
                AND bo.is_active = TRUE
                AND b.is_active = TRUE
                AND (bo.pause_until IS NULL OR bo.pause_until < NOW())
                AND (b.min_balance_required IS NULL OR b.balance >= b.min_balance_required)
            ),
            service_area_match AS (
                SELECT DISTINCT buyer_id
                FROM buyer_service_areas
                WHERE market_id = :market_id
                AND is_active = TRUE
                AND (
                    (scope_type = 'postal_code' AND scope_value = :postal_code)
                    OR
                    (scope_type = 'city' AND scope_value = :city)
                    OR
                    (scope_type = 'postal_code' AND scope_value LIKE SUBSTRING(:postal_code FROM 1 FOR 3) || '%')
                )
            ),
            capacity_check AS (
                SELECT 
                    eb.*,
                    COALESCE(dc.lead_count, 0) as daily_count,
                    COALESCE(hc.lead_count, 0) as hourly_count
                FROM eligible_base eb
                LEFT JOIN (
                    SELECT buyer_id, COUNT(*) as lead_count
                    FROM leads
                    WHERE offer_id = :offer_id
                    AND buyer_id IS NOT NULL
                    AND delivered_at >= NOW() - INTERVAL '24 HOURS'
                    GROUP BY buyer_id
                ) dc ON dc.buyer_id = eb.buyer_id
                LEFT JOIN (
                    SELECT buyer_id, COUNT(*) as lead_count
                    FROM leads
                    WHERE offer_id = :offer_id
                    AND buyer_id IS NOT NULL
                    AND delivered_at >= NOW() - INTERVAL '1 HOUR'
                    GROUP BY buyer_id
                ) hc ON hc.buyer_id = eb.buyer_id
                WHERE (eb.capacity_per_day IS NULL OR COALESCE(dc.lead_count, 0) < eb.capacity_per_day)
                AND (eb.capacity_per_hour IS NULL OR COALESCE(hc.lead_count, 0) < eb.capacity_per_hour)
            )
            SELECT cc.*, sam.buyer_id as service_approved
            FROM capacity_check cc
            INNER JOIN service_area_match sam ON sam.buyer_id = cc.buyer_id
            ORDER BY cc.routing_priority ASC, cc.last_assigned ASC NULLS FIRST
        """)
        
        result = await session.execute(query, {
            "offer_id": offer_id,
            "market_id": market_id,
            "postal_code": postal_code,
            "city": city or ""
        })
        
        buyers = []
        for row in result.mappings():
            capacity = BuyerCapacity(
                daily_used=row.daily_count,
                daily_limit=row.capacity_per_day,
                hourly_used=row.hourly_count,
                hourly_limit=row.capacity_per_hour,
                is_capped=(
                    (row.capacity_per_day is not None and row.daily_count >= row.capacity_per_day) or
                    (row.capacity_per_hour is not None and row.hourly_count >= row.capacity_per_hour)
                )
            )
            
            buyers.append(EligibleBuyer(
                buyer_id=row.buyer_id,
                routing_priority=row.routing_priority,
                price_per_lead=float(row.price_per_lead),
                capacity=capacity,
                last_assigned=row.last_assigned
            ))
        
        return buyers
    
    async def _priority_strategy(self, buyers: List[EligibleBuyer], config: Dict) -> Optional[int]:
        if not buyers:
            return None
        
        # Sort by priority, then by least recently assigned
        sorted_buyers = sorted(buyers, key=lambda b: (
            b.capacity.is_capped,  # Uncapped first
            b.routing_priority,
            1 if b.last_assigned else 0,  # Never assigned first
            b.last_assigned or datetime.min
        ))
        
        return sorted_buyers[0].buyer_id
    
    async def _round_robin_strategy(self, buyers: List[EligibleBuyer], config: Dict) -> Optional[int]:
        if not buyers:
            return None
        
        # Filter out capped buyers
        available = [b for b in buyers if not b.capacity.is_capped]
        
        if not available:
            return None
        
        # Sort by last assigned (NULLs first), then by priority
        sorted_buyers = sorted(available, key=lambda b: (
            1 if b.last_assigned else 0,
            b.last_assigned or datetime.min,
            b.routing_priority
        ))
        
        return sorted_buyers[0].buyer_id
    
    async def _capacity_weighted_strategy(self, buyers: List[EligibleBuyer], config: Dict) -> Optional[int]:
        if not buyers:
            return None
        
        available = [b for b in buyers if not b.capacity.is_capped]
        
        if not available:
            return None
        
        # Calculate weights based on remaining capacity
        weighted_buyers = []
        for buyer in available:
            if buyer.capacity.daily_limit:
                remaining = max(0, buyer.capacity.daily_limit - buyer.capacity.daily_used)
                weight = remaining / buyer.capacity.daily_limit
            else:
                weight = 1.0
            
            weighted_buyers.append((buyer, weight))
        
        # Sort by weight (descending), then priority
        sorted_buyers = sorted(weighted_buyers, key=lambda x: (-x[1], x[0].routing_priority))
        
        return sorted_buyers[0][0].buyer_id if sorted_buyers else None
    
    async def _exclusive_strategy(self, buyers: List[EligibleBuyer], config: Dict) -> Optional[int]:
        # Exclusive strategy only used when exclusivity is detected
        # This handler shouldn't be called directly
        return None
    
    async def _get_buyer_price(self, session: AsyncSession, offer_id: int, buyer_id: int) -> float:
        query = text("""
            SELECT COALESCE(bo.price_per_lead, o.default_price_per_lead) as price
            FROM buyer_offers bo
            JOIN offers o ON o.id = bo.offer_id
            WHERE bo.offer_id = :offer_id 
            AND bo.buyer_id = :buyer_id
            AND bo.is_active = TRUE
        """)
        
        result = await session.execute(query, {"offer_id": offer_id, "buyer_id": buyer_id})
        row = result.mappings().first()
        
        if not row:
            raise RoutingError(
                code="buyer_price_not_found",
                message=f"Price not found for buyer {buyer_id} on offer {offer_id}"
            )
        
        return float(row.price)
    
    async def _update_lead_routing(self, session: AsyncSession, lead_id: int, 
                                  buyer_id: int, price: float) -> bool:
        query = text("""
            UPDATE leads 
            SET 
                buyer_id = :buyer_id,
                price = :price,
                updated_at = NOW(),
                routing_attempts = COALESCE(routing_attempts, 0) + 1
            WHERE id = :lead_id 
            AND status = 'validated'
            RETURNING id
        """)
        
        result = await session.execute(query, {
            "lead_id": lead_id,
            "buyer_id": buyer_id,
            "price": price
        })
        
        return result.rowcount > 0
    
    async def _get_cached_routing(self, cache_key: str) -> Optional[Dict]:
        if not self.redis:
            return None
        
        try:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            logger.warning("routing.cache_read_failed", key=cache_key)
        
        return None
    
    async def _cache_routing(self, cache_key: str, result: RoutingResult):
        if not self.redis:
            return
        
        try:
            cache_data = {
                "buyer_id": result.buyer_id,
                "price": result.price,
                "routing_policy_id": result.routing_policy_id,
                "strategy_used": result.strategy_used.value,
                "execution_time_ms": result.execution_time_ms
            }
            
            await self.redis.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(cache_data)
            )
        except Exception:
            logger.warning("routing.cache_write_failed", key=cache_key)

# Global instance
routing_engine = RoutingEngine()