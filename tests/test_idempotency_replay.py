# tests/test_idempotency_replay.py
import asyncio
import os
import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from api.routes.leads import router as leads_router


def _read_sql(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


async def _apply_migrations(engine, schema: str) -> None:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api", "db", "migrations"))
    paths = [
        os.path.join(base, "001_initial.sql"),
        os.path.join(base, "002_reference_entities.sql"),
        os.path.join(base, "003_leads_attribution.sql"),
        os.path.join(base, "004_leads_idempotency.sql"),
    ]

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
        await conn.exec_driver_sql(f'SET search_path TO "{schema}";')
        for p in paths:
            await conn.exec_driver_sql(_read_sql(p))


async def _seed_reference(engine, schema: str) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql(f'SET search_path TO "{schema}";')

        # market
        await conn.exec_driver_sql(
            "INSERT INTO markets(name, timezone, is_active) VALUES ('Austin TX','America/Chicago',true);"
        )
        # vertical
        await conn.exec_driver_sql(
            "INSERT INTO verticals(name, slug, is_active) VALUES ('Plumbing','plumbing',true);"
        )
        # offer
        await conn.exec_driver_sql(
            """
            INSERT INTO offers(market_id, vertical_id, name, offer_key, default_price_per_lead_cents, is_active)
            SELECT m.id, v.id, 'Austin Plumbing', 'austin.plumbing', 2500, true
            FROM markets m, verticals v
            WHERE m.name='Austin TX' AND v.slug='plumbing';
            """
        )
        # source
        await conn.exec_driver_sql(
            """
            INSERT INTO sources(offer_id, source_key, kind, name, hostname, path_prefix, is_active)
            SELECT o.id, 'lp.austin.plumbing', 'landing_page', 'Austin LP', 'example.com', '/leads', true
            FROM offers o
            WHERE o.offer_key='austin.plumbing';
            """
        )


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set (expected async postgres url)")
def test_replay_same_source_idempotency_key_returns_same_lead_id():
    async def _run():
        schema = f"t_{uuid.uuid4().hex[:16]}"
        engine = create_async_engine(os.environ["DATABASE_URL"], future=True, echo=False)

        await _apply_migrations(engine, schema)
        await _seed_reference(engine, schema)

        app = FastAPI()
        app.include_router(leads_router, prefix="/api")

        # Override DB search_path for this test schema by monkeypatching settings at the DB layer is out of scope;
        # instead use Postgres `options` in DATABASE_URL if provided by caller. If not provided, fail explicitly.
        #
        # REQUIRED: DATABASE_URL must include: ?options=-csearch_path%3D<schema>
        if f"search_path%3D{schema}" not in os.environ["DATABASE_URL"]:
            raise RuntimeError(
                "DATABASE_URL must include options to set search_path for tests, "
                f"example: postgresql+asyncpg://.../db?options=-csearch_path%3D{schema}"
            )

        async with AsyncClient(app=app, base_url="http://test") as ac:
            payload = {
                "source_key": "lp.austin.plumbing",
                "idempotency_key": "idem_replay_00000001",
                "name": "Joey Brooks",
                "email": "joey@example.com",
                "phone": "5551234567",
                "zip": "78701",
                "message": "Need help",
                "consent": True,
                "gdpr_consent": True,
            }

            r1 = await ac.post("/api/leads", json=payload, headers={"host": "example.com"})
            r2 = await ac.post("/api/leads", json=payload, headers={"host": "example.com"})

            assert r1.status_code == 202, r1.text
            assert r2.status_code == 202, r2.text

            j1 = r1.json()
            j2 = r2.json()

            assert j1["lead_id"] == j2["lead_id"]
            assert j1["source_id"] == j2["source_id"]
            assert j1["offer_id"] == j2["offer_id"]
            assert j1["market_id"] == j2["market_id"]
            assert j1["vertical_id"] == j2["vertical_id"]
            assert j1["idempotency_key"] == j2["idempotency_key"]

        await engine.dispose()

    asyncio.run(_run())

