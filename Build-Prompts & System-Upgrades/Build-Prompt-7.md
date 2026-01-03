### <span style="color: #88c0d0;">System Role</span>

You are a <span style="color: #8fbcbb;">Senior Routing Policy Engineer</span>.
Your output will be consumed by autonomous AI agents that execute real work.
Ambiguity, placeholders, or advisory language are prohibited.
Your task is to implement **policy-driven routing** (eligibility + deterministic selection) exactly as defined in the frozen architecture spec, and nothing beyond that scope.

---

### <span style="color: #88c0d0;">Hard Rules (Non-Negotiable)</span>

* <span style="color: #8fbcbb;">Source of truth</span>
  `C:\work-spaces\lead-gen\lead-gen\Technical-Architecture-Specification.md` is binding.
* <span style="color: #8fbcbb;">Scope lock</span>
  Implement ONLY:

  1. buyer eligibility evaluation scoped to offer + market + vertical
  2. exclusivity handling per policy
  3. deterministic routing strategy selection (priority/rotation/weighted if spec defines)
  4. state transition from `validated` → `routed` (or equivalent spec status) with `buyer_id` assigned
     Do NOT implement delivery (posting/email/SMS), billing/invoicing, payments, workers, or pricing computations.
* <span style="color: #8fbcbb;">Policy-only logic</span>
  All routing behavior MUST be driven by persisted configuration:

  * `routing_policies.rules/config`
  * `buyer_offers`
  * `buyer_service_areas`
  * `offer_exclusivities`
    No hardcoded ZIPs, cities, schedules, niches, or buyer assumptions.
* <span style="color: #8fbcbb;">Determinism requirement</span>
  Given the same lead attributes and configuration state, selected buyer MUST be identical.
  Tie-breakers MUST be explicit and stable.
* <span style="color: #8fbcbb;">No truncation</span>
  All files created must be complete and runnable. No TODOs.

---

### <span style="color: #88c0d0;">Canonical Prompt Structure (Do Not Deviate)</span>

<span style="color: #8fbcbb;">Prompt Header</span>
ROLE: Routing Policy Engineer
TARGET PLATFORM: Windows 11 x64 + PowerShell 7 + Python 3.11 + FastAPI + PostgreSQL 15
CONSTRAINT LEVEL: Production

<span style="color: #8fbcbb;">Primary Instruction</span>
Write a Python 3.11 routing subsystem
that performs deterministic buyer eligibility + selection using routing policies
with **p95 routing decision latency ≤ 120ms** per lead on **4 cores / 16GB RAM / SSD**.

---

### <span style="color: #88c0d0;">Functional Requirements</span>

1. Operate ONLY on leads that are already `validated` (or the exact equivalent status in the spec).
2. Load the applicable routing policy for the lead’s `offer_id` (and/or market/vertical if spec defines resolution rules).
3. Implement buyer eligibility strictly per Buyer Scoping Contract:

   * buyer MUST have active `buyer_offers` enrollment for the lead’s `offer_id`
   * buyer MUST cover the lead geo scope via `buyer_service_areas` for the lead’s `market_id`
   * buyer MUST satisfy capacity constraints if configured (daily/hourly caps)
   * buyer MUST be excluded if paused/outside acceptance hours if policy includes those constraints
   * buyer MUST satisfy any financial constraints if the schema includes them (e.g., minimum balance)
4. Deterministic eligibility output:

   * Produce an ordered list of eligible buyers with explicit reasons for exclusion of ineligible buyers (stored or returned for debugging if spec allows; otherwise in tests only).
5. Exclusivity semantics:

   * If an active exclusivity rule matches `offer_id + scope` then route ONLY to that exclusive buyer unless ineligible.
   * If exclusive buyer is ineligible, follow policy-configured fallback behavior:

     * `fail_closed` OR `fallback_allowed` (must be a policy field; must not be hardcoded).
6. Routing evaluation order MUST be:

   1. resolve eligible buyers
   2. apply exclusivity constraints
   3. apply routing strategy (`priority`, `rotation`, `weighted`, or spec-defined set)
   4. enforce caps and SLAs (if policy defines SLA preference behavior)
   5. select winner deterministically using stable tie-breakers
7. Assign the selected `buyer_id` to the lead and transition lead status from `validated` → `routed` (or spec equivalent).
8. Guarded transition:

   * Update MUST be conditional so the same lead cannot be routed twice.
9. No delivery and no billing:

   * Do not send anything to the buyer.
   * Do not compute price.
   * Do not create invoices.

---

### <span style="color: #88c0d0;">Technical Requirements</span>

* Language/runtime: Python 3.11
* Frameworks/libraries:

  * Use existing project stack (FastAPI/SQLAlchemy async/asyncpg) exactly as already established
* DB access:

  * Parameterized queries only
  * Any selection ordering must be explicit (`ORDER BY`) and stable
* Data locking / concurrency:

  * Must be safe under concurrent route attempts:

    * use guarded update on lead status
    * use `SELECT ... FOR UPDATE SKIP LOCKED` only if spec requires; otherwise rely on guarded updates + unique constraints if present
* File encoding: UTF-8
* Line endings: LF

---

### <span style="color: #88c0d0;">Integration Requirements</span>

* Must integrate with:

  * ingestion pipeline output (lead classification fields persisted)
  * validation pipeline output (`validated` state)
  * DB schema: buyers, buyer_offers, buyer_service_areas, offers, offer_exclusivities, routing_policies, leads
* Interface contract:

  * Input: `lead_id`
  * Output: lead updated with `buyer_id` and routed status (or explicit no-route outcome)
* Backward compatibility constraints: YES

---

### <span style="color: #88c0d0;">Performance & Benchmarks</span>

* Metric(s): routing decision latency, DB query count
* Target:

  * p50: ≤ 60ms
  * p95: ≤ 120ms
  * p99: ≤ 250ms
* Test environment:

  * Hardware: 4 CPU cores, 16GB RAM, SSD
  * OS: Windows 11 x64
  * Load profile:

    * 1,000 sequential routing decisions
    * 50 concurrent route attempts on different leads
    * 10 concurrent route attempts on the same lead (must result in single winner / no double assignment)

---

### <span style="color: #88c0d0;">Failure Modes & Handling</span>

* Failure case #1: No eligible buyers found → return deterministic `no_route` outcome; do not change lead to routed.
* Failure case #2: Exclusivity match but exclusive buyer ineligible and policy says `fail_closed` → return deterministic `no_route_exclusive_fail_closed`.
* Failure case #3: Concurrent routing attempt on already-routed lead → NO-OP, return current state.

---

### <span style="color: #88c0d0;">Testing & Validation</span>

* Test type(s): unit + integration
* Required coverage:

  * Unit: ≥95% for eligibility filtering, exclusivity, and deterministic selection/tie-breakers
  * Integration: real Postgres container with seeded buyers/offers/service areas/policies
* Edge cases:

  * multiple eligible buyers same priority (tie-break)
  * exclusivity scope match by postal_code/city (as spec defines)
  * cap reached mid-run under concurrency
  * buyer paused or after-hours policy exclusion
* Validation command(s):

  * `cd C:\work-spaces\lead-gen\lead-gen`
  * `docker compose up -d postgres`
  * `python -m pytest -q`
  * (if you add a simple local load test script in tests): `python -m pytest -q -k routing_load`

---

### <span style="color: #88c0d0;">Deliverables (Acceptance Criteria)</span>

Deliver:

* Routing engine module(s):

  * eligibility evaluation
  * exclusivity evaluation
  * strategy selection + deterministic tie-breakers
  * guarded lead update to routed state
* Test suite:

  * unit tests for each routing phase
  * integration tests with real Postgres
  * concurrency test proving no double-route
* Acceptance:

  * A validated lead routes to exactly one buyer deterministically
  * No delivery/billing code present
  * Guarded transitions prevent double assignment
  * All tests pass

---

### <span style="color: #88c0d0;">Output Rules</span>

Output ONLY the final compiled prompt.
No explanations.
No commentary.
No alternatives.
No questions.
