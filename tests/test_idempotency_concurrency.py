# tests/test_idempotency_concurrency.py
import asyncio
import os

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from api.routes.leads import router as leads_router


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (expected async postgres url)")
def test_20_concurrent_posts_same_idempotency_result_in_single_lead_id():
    async def _run():
        app = FastAPI()
        app.include_router(leads_router, prefix="/api")

        payload = {
            "source_key": "lp.austin.plumbing",
            "idempotency_key": "idem_conc_0000000001",
            "name": "Joey Brooks",
            "email": "joey.concurrent@example.com",
            "phone": "5551234567",
            "zip": "78701",
            "message": "Need help now",
            "consent": True,
            "gdpr_consent": True,
        }

        async with AsyncClient(app=app, base_url="http://test") as ac:
            async def one():
                r = await ac.post("/api/leads", json=payload, headers={"host": "example.com"})
                assert r.status_code == 202, r.text
                return r.json()["lead_id"]

            ids = await asyncio.gather(*[one() for _ in range(20)])
            assert len(set(ids)) == 1

    asyncio.run(_run())

