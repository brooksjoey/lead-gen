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

## Testing

- Run `pip install -r api/requirements.txt` then `python -m pytest` for FastAPI unit tests.
- Worker-specific checks live under `workers/` and can follow the same install path once logic is added.

## Development Notes

- Keep `.env` out of source control; use `.env.example` for reference values.
- Routing logic, validations, and billing are stubs—extend services in `api/services/` before production use.
- Use `infra/deploy/setup.sh` for Compose-based deployment helpers and hook it into your CI/CD pipeline.
