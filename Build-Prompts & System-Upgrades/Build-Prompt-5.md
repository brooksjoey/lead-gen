You are a <span style="color: #8fbcbb;">Senior Lead Ingestion Engineer</span>.
Your output will be consumed by autonomous AI agents that execute real work.
Ambiguity, placeholders, or advisory language are prohibited.
Your task is to implement the lead ingestion pipeline exactly as the architecture spec defines, with deterministic classification and ingestion idempotency, and nothing beyond that scope.

<span style="color: #88c0d0;">Hard Rules (Non-Negotiable)</span>

<span style="color: #8fbcbb;">Source of truth</span>
C:\work-spaces\lead-gen\lead-gen\Technical-Architecture-Specification.md is binding.

<span style="color: #8fbcbb;">Scope lock</span>
Implement ONLY:

lead ingestion API surface required by the spec

classification (resolve source_id → offer_id → market_id/vertical_id)

idempotent lead creation using (source_id, idempotency_key) uniqueness

persistence of raw + normalized contact fields required for later duplicate detection
Do NOT implement duplicate detection decisions, validation decisions, routing, delivery, billing, invoicing, worker processing, or buyer selection.

<span style="color: #8fbcbb;">No truncation</span>
No partial modules. All files created by this prompt must be complete and runnable.

<span style="color: #8fbcbb;">Deterministic behavior</span>
Given the same request inputs and DB state, the output MUST be identical.

<span style="color: #8fbcbb;">No hidden niche logic</span>
No market/vertical hardcoding. All resolution is through sources → offers → markets/verticals.

<span style="color: #88c0d0;">Canonical Prompt Structure (Do Not Deviate)</span>

<span style="color: #8fbcbb;">Prompt Header</span>
ROLE: Lead Ingestion Engineer
TARGET PLATFORM: Windows 11 x64 + PowerShell 7 + Python 3.11 + FastAPI + PostgreSQL 15 (Docker)
CONSTRAINT LEVEL: Production

<span style="color: #8fbcbb;">Primary Instruction</span>
Write a Python 3.11 FastAPI ingestion component
that implements deterministic lead classification + idempotent lead creation
with p95 request latency ≤ 120ms on 4 cores / 16GB RAM / SSD against local Docker Postgres.

<span style="color: #88c0d0;">Functional Requirements</span>

Implement exactly one API endpoint if and only if it is specified by the architecture spec:
POST /api/leads (or the exact path the spec declares).
If the spec declares a different path, use that path.

Input contract MUST support:

lead contact fields required by the spec

optional source_id

optional source_key

optional idempotency_key

Implement deterministic classification exactly as specified:

Priority order: source_id → source_key → HTTP mapping (Host + request path, longest path_prefix)

Canonicalization rules per spec for source_key, hostname, path

Failure modes per spec with explicit error codes:

invalid_source

invalid_source_key

unmapped_source

ambiguous_source_mapping

Implement ingestion idempotency exactly as specified:

If idempotency_key provided: validate charset/length; canonicalize (strip only)

If absent: derive deterministically per spec rules and persist

Enforce uniqueness via (source_id, idempotency_key)

Replay MUST return the same lead_id and current known state

Failure modes:

invalid_idempotency_key_format

idempotency_derivation_failed

Persist lead row with these immutable classification bindings:

source_id, offer_id, market_id, vertical_id

Persist raw fields AND normalized fields required for later duplicate detection:

email + normalized_email (lower+trim)

phone + normalized_phone (E.164 if present else digits-only; length < 7 becomes NULL)

Response contract MUST return:

lead_id

resolved source_id, offer_id, market_id, vertical_id

the idempotency_key used (client or derived)

current status

Concurrency safety:

Must be safe under concurrent duplicate POSTs with same (source_id, idempotency_key) without double inserts.

No duplicate detection decisions:

You may compute/store normalization and references needed later, but MUST NOT reject/flag/accept duplicates in this prompt.

<span style="color: #88c0d0;">Technical Requirements</span>

Language/runtime: Python 3.11

Frameworks/libraries:

FastAPI (exact version from spec)

Pydantic (exact version from spec)

SQLAlchemy async (exact version from spec, if spec uses it) OR psycopg async if spec specifies

asyncpg (if spec specifies)

DB access:

Must use parameterized queries only

No ORM model invention if spec already defines patterns; follow repo conventions created in Prompt 3

Error format:

JSON body: { "error": { "code": "<code>", "message": "<message>", "details": { ... } } }

HTTP status: 400 for invalid input, 409 for ambiguity conflict, 500 only for unexpected exceptions

Logging:

Use spec-defined logging (if present). If not present, do not add new logging framework.

File encoding: UTF-8

Line endings: LF

<span style="color: #88c0d0;">Integration Requirements</span>

Must integrate with:

existing FastAPI bootstrap from Prompt 3

database schema from Prompt 2 (sources/offers/leads)

docker-compose networking

Interface contract:

Input: HTTP POST request + DB state

Output: lead record created or reused idempotently

Backward compatibility constraints: YES — no breaking of existing app boot.

<span style="color: #88c0d0;">Performance & Benchmarks</span>

Metric(s): request latency, DB round trips

Target:

p50: ≤ 60ms

p95: ≤ 120ms

p99: ≤ 250ms

Test environment:

Hardware: 4 CPU cores, 16GB RAM, SSD

OS: Windows 11 x64

Load profile:

100 sequential requests

20 concurrent requests for same (source_id, idempotency_key) to test race behavior

<span style="color: #88c0d0;">Failure Modes & Handling</span>

Failure case #1: Cannot resolve a single source deterministically → return correct error code and HTTP status (409 for ambiguity, 400 otherwise).

Failure case #2: Invalid idempotency key format → 400 invalid_idempotency_key_format.

Failure case #3: Derived idempotency cannot be computed due to missing required fields → 400 idempotency_derivation_failed.

Failure case #4: DB conflict on idempotency uniqueness → must return existing lead result (not error).

<span style="color: #88c0d0;">Testing & Validation</span>

Test type(s): unit + integration

Required coverage:

Unit: 95%+ for classification + idempotency derivation + normalization

Integration: must hit real Postgres container

Edge cases:

source_key whitespace variations

hostname includes port

multiple sources match same hostname/path with same longest prefix

concurrent identical POSTs

phone with symbols vs E.164

Validation command(s):

cd C:\work-spaces\lead-gen\lead-gen

docker compose up -d postgres redis (if redis is present in compose; otherwise postgres only)

Start API (spec command):

python -m uvicorn <SPEC_MODULE_PATH>:<SPEC_APP_NAME> --host 0.0.0.0 --port 8000

Run tests:

python -m pytest -q

Concurrency test (must be included in tests):

spawn 20 concurrent POSTs and assert same lead_id

<span style="color: #88c0d0;">Deliverables (Acceptance Criteria)</span>

Deliver:

File structure (exact paths may differ; follow existing repo conventions from Prompt 3):

API route module implementing POST /api/leads

Classification resolver module (sources/offers binding)

Idempotency module (validate/derive + DB upsert)

Normalization utilities (email/phone)

Test suite:

unit tests for classification/idempotency/normalization

integration test hitting Postgres container

Build / run command:

Spec-defined uvicorn command

Acceptance:

Deterministic source resolution with required failure codes

Idempotent replay returns same lead_id

20-concurrent test passes

No routing/validation/dedupe decisions implemented

<span style="color: #88c0d0;">Output Rules</span>

Output ONLY the final compiled prompt.
No explanations.
No commentary.
No alternatives.
No questions.