# LeadGen

LeadGen is an event-driven lead distribution platform starter kit. It couples modern FastAPI services with worker processes, PostgreSQL, Redis, and a secure NGINX front door to support ingestion, routing, delivery, and billing workflows for any service vertical.

## Architecture Highlights

- **API**: FastAPI + SQLAlchemy Async Engine powering `/api` endpoints; structlog used for structured, JSON-formatted logs.
- **Workers**: Dedicated background workers (notify/invoice) that can grow into RQ/Celery pipelines.
- **Infra**: Docker Compose v3.9 orchestrates PostgreSQL 17, Redis 7, API, worker, and NGINX with TLS-ready proxy config.
- **Landing**: Static marketing site targeting any niche; swap copy/UTM controls to refocus on a new region.
- **Configuration**: `.env.example` documents secrets, webhook behavior, Twilio/SMS placeholders, and logging options.

## Getting Started

1. Copy `.env.example` to `.env` and adjust values (database credentials, SMTP, webhook secrets).
2. Build and run the stack with `docker compose up --build` (note: we target Compose V2).
3. CLI health check: `curl http://localhost/health`.
4. Submit leads via `POST http://localhost/api/leads` with JSON payload (see API docs).

## Database: Apply Migrations

The database schema is defined in `api/db/migrations/` and implements the complete Technical Architecture Specification schema.

### Fresh Database Setup

To create a fresh database and apply all migrations:

```bash
docker compose down -v
docker compose up -d postgres
```

Migrations are automatically applied when the Postgres container starts if they are mounted to `/docker-entrypoint-initdb.d/`.

### Manual Migration Application

If migrations need to be applied manually:

```bash
# Apply migrations in order
docker compose exec -T postgres psql -U leadgen -d leadgen -f /path/to/002_spec_schema_enums.sql
docker compose exec -T postgres psql -U leadgen -d leadgen -f /path/to/003_spec_schema_core_tables.sql
docker compose exec -T postgres psql -U leadgen -d leadgen -f /path/to/004_spec_schema_buyers.sql
docker compose exec -T postgres psql -U leadgen -d leadgen -f /path/to/005_spec_schema_leads.sql
docker compose exec -T postgres psql -U leadgen -d leadgen -f /path/to/006_spec_schema_invoices_audit.sql
docker compose exec -T postgres psql -U leadgen -d leadgen -f /path/to/007_spec_schema_indexes.sql
```

### Verify Schema

To verify the schema was applied correctly:

```bash
# List all tables
docker compose exec -T postgres psql -U leadgen -d leadgen -c "\dt"

# Inspect leads table structure
docker compose exec -T postgres psql -U leadgen -d leadgen -c "\d+ leads"

# Inspect sources table structure
docker compose exec -T postgres psql -U leadgen -d leadgen -c "\d+ sources"

# Inspect offers table structure
docker compose exec -T postgres psql -U leadgen -d leadgen -c "\d+ offers"
```

All migrations are idempotent and can be safely re-run multiple times.

## Testing

- Run `pip install -r api/requirements.txt` then `python -m pytest` for FastAPI unit tests.
- Worker-specific checks live under `workers/` and can follow the same install path once logic is added.

## Development Notes

- Keep `.env` out of source control; use `.env.example` for reference values.
- Routing logic, validations, and billing are stubs—extend services in `api/services/` before production use.
- Use `infra/deploy/setup.sh` for Compose-based deployment helpers and hook it into your CI/CD pipeline.
