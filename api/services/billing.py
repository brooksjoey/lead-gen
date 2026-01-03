from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_structlog_logger

logger = get_structlog_logger()


async def bill_lead(
    session: AsyncSession,
    lead_id: int,
    buyer_id: int,
) -> bool:
    """
    Bill a delivered lead to the buyer.
    
    Uses atomic transaction with idempotency guard to prevent double-billing.
    Gets price from buyer_offers table if available, otherwise uses buyer's default price_per_lead.
    
    Returns True if billing succeeded, False if already billed or buyer not found.
    """
    try:
        # Get price from buyer_offers or buyer default, with lead's offer_id
        price_query = text("""
            WITH lead_info AS (
                SELECT offer_id, buyer_id
                FROM leads
                WHERE id = :lead_id AND buyer_id = :buyer_id
            ),
            price_source AS (
                SELECT 
                    COALESCE(
                        bo.price_per_lead,
                        b.price_per_lead,
                        45.00
                    ) as price
                FROM lead_info li
                JOIN buyers b ON b.id = li.buyer_id
                LEFT JOIN buyer_offers bo ON bo.buyer_id = li.buyer_id 
                    AND bo.offer_id = li.offer_id 
                    AND bo.is_active = true
                    AND bo.deleted_at IS NULL
                WHERE b.is_active = true AND b.deleted_at IS NULL
            )
            SELECT price FROM price_source
        """)
        
        result = await session.execute(price_query, {"lead_id": lead_id, "buyer_id": buyer_id})
        price_row = result.fetchone()
        
        if not price_row:
            logger.warning(
                "billing.buyer_not_found",
                lead_id=lead_id,
                buyer_id=buyer_id,
            )
            return False
        
        price = Decimal(str(price_row[0]))
        
        # Atomic billing transaction with idempotency guard
        # Only bills if billing_status is still 'pending'
        billing_query = text("""
            WITH lead_update AS (
                UPDATE leads 
                SET billing_status = 'billed',
                    price = :price,
                    billed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :lead_id 
                  AND buyer_id = :buyer_id
                  AND billing_status = 'pending'
                  AND status = 'delivered'
                RETURNING id, price
            ),
            buyer_update AS (
                UPDATE buyers 
                SET balance = balance + :price,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :buyer_id
                  AND EXISTS (SELECT 1 FROM lead_update)
                RETURNING id, balance
            )
            SELECT 
                (SELECT id FROM lead_update) as lead_id,
                (SELECT balance FROM buyer_update) as new_balance,
                :price as price
        """)
        
        result = await session.execute(
            billing_query,
            {
                "lead_id": lead_id,
                "buyer_id": buyer_id,
                "price": price,
            }
        )
        
        billing_result = result.fetchone()
        await session.commit()
        
        if billing_result and billing_result[0]:
            logger.info(
                "billing.success",
                lead_id=lead_id,
                buyer_id=buyer_id,
                price=float(price),
                new_balance=float(billing_result[1]) if billing_result[1] else None,
            )
            return True
        else:
            # Already billed or lead not in correct state
            logger.info(
                "billing.skipped",
                lead_id=lead_id,
                buyer_id=buyer_id,
                reason="already_billed_or_wrong_state",
            )
            return False
            
    except Exception as e:
        await session.rollback()
        logger.error(
            "billing.error",
            lead_id=lead_id,
            buyer_id=buyer_id,
            error=str(e),
            traceback=True,
        )
        # Don't block delivery on billing errors - log and continue
        return False
