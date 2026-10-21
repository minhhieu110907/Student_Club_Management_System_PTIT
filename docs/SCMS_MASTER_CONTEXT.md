# SCMS — MASTER PROJECT CONTEXT & 21-DAY EXECUTION PLAN

> **Source of Truth — Planning baseline v1.0**  
> Updated: 2026-10-21  
> Project: **Student Club Management System (SCMS)**  
> Status: **V1/21-day plan agreed; Day 1 has NOT been implemented or verified yet.**  
> Language for mentoring/reviews: Vietnamese. Code identifiers and technical artifacts: English.

## 0. HOW AN AI ASSISTANT MUST USE THIS DOCUMENT

1. Read this file at the start of a **new SCMS chat**, especially when the user says `SCMS Day X/21`, `SCMS ngày X/21`, or asks for a Codex prompt. This file describes **agreed intended scope**, not proof that code exists.
2. **Never claim a task completed without code, CI, logs, tests, or user confirmation.** The `Progress Log` near the end is the day-to-day ground truth when updated.
3. **Do not infer exact database columns from this document.** Read the actual companion file `scms_v1_3_outbox.dbml` and, once implemented, inspect SQLAlchemy models and Alembic migrations. The DBML is a baseline pending DBML parser/MySQL validation.
4. Preserve the **3-week demo/academic-project constraint**. Deliver something runnable on other people's **local Docker**, not a 24/7 commercial public production service. Be production-minded in correctness, security, tests, and portability, but do not force paid VPS, domain, Kubernetes, microservices, or complicated observability infrastructure.
5. Prefer **reasoned trade-offs** and vertical slices over premature abstraction. Explain what the user must understand/review; write bounded, actionable Codex prompts with acceptance criteria and tests.
6. Do not conflate this SCMS 21-day *project implementation roadmap* with the user's earlier 21-day *Backend Engineering study roadmap*.
7. If plans conflict, use: (a) user's latest explicit choice, (b) actual repository/schema evidence, (c) this master context. Flag discrepancies and seek a targeted decision rather than silently overriding.
8. Keep answers in Vietnamese and focus on Senior Backend Engineer / Technical Lead level mentoring. Be skeptical of overengineering and hidden security/concurrency failures.

## 1. PURPOSE, CONSTRAINTS, AND DELIVERABLE

- **SCMS** = Student Club Management System. One application manages **many university student clubs**; one student may be a Member in one club and Manager in another.
- **Nature**: SOLO fullstack academic course project + backend/AI-engineering portfolio demo. **No real users or always-on 24/7 production obligation** for V1.
- **Timeline**: **21 days (3 weeks)**. Ambitious estimated focus **4–6 deep-work hours/day**, Codex as primary implementer.
- **User's job**: Technical Lead / Architect / reviewer / acceptance owner; actively learn and understand trade-offs, invariants, failure modes.
- **Codex job**: implement bounded tickets/slices, write tests, run verification, report evidence. Other AI assistants may critique high-risk choices, but avoid redundant broad multi-AI reviews and token waste.
- **V1 end goal**: Another person can `git clone`, configure `.env`, run `docker compose up -d --build`, wait for a **single, safe migration + demo seed bootstrap**, open a localhost URL, log into demo roles, use the UI/AI/demo functions. They do **not** need system Python, local MySQL/Redis/Nginx or a VPS.
- **AI key may be unavailable**: offer a documented **mock AI mode** for reproducible demo. Real LLM usage needs valid key/quota; never commit keys.
- **Philosophy**: **Small Scope — Deep Engineering — Production-minded**. High quality of core invariants matters more than feature count/UI polish.

## 2. TECHNOLOGY & ARCHITECTURE (AGREED)

| Concern | Decision |
|---|---|
| Frontend | HTML + CSS + **Vanilla JavaScript**; match existing Figma SCMS pragmatically; no React required |
| Frontend hosting / proxy | **Nginx** serves static frontend and reverse-proxies `/api` to FastAPI (same origin locally) |
| Backend | **Python FastAPI**, Pydantic, SQLAlchemy ORM, Alembic |
| DB | **MySQL 8 / InnoDB**, source of truth |
| App structure | **Lightweight Modular Monolith**, **module-first** by domain; routers → services → repositories when useful → DB |
| Transactions | Service owns transaction boundary; repositories should not commit autonomously |
| Cache | **Redis Cache-Aside**, only for suitable read/public data; correct invalidation/TTL/fallback; authorization/capacity remain DB authoritative |
| Queue | **Redis-backed worker queue** for emails/notifications. **RQ is suggested default, but NOT formally decided**; Celery is alternative |
| Reliable enqueue | **MySQL Transactional Outbox**, dispatcher publishes to queue with at-least-once semantics; consumer dedupe/retry |
| AI | LLM API, **read-only tools** (3A+ target), validated allowlist, JWT identity from authenticated context, business-service authorization |
| Testing | Pytest, HTTPX, unit/integration/API/security/concurrency/worker/AI tests, regression, smoke and small perf checks |
| Logging | Structured JSON logs, request_id/correlation_id, sanitized errors, basic healthchecks and metrics where cheap |
| Automation | GitHub Actions **CI from start**: lint, tests, image build; full public CD optional |
| Packaging | Dockerfiles + **Docker Compose** on Docker Desktop / Docker Engine; local portability required |
| V1 deployment | Full stack local Docker demo. Public frontend-only (GitHub Pages/Vercel) optional and must be marked as UI/mock demo, not full backend. VPS/domain NOT required. |

**Runtime topology by end of V1 (approx. six services):**

```text
Browser (localhost)
       |
       v
Nginx [static frontend + /api reverse proxy]
       |
       v
FastAPI -----------------------------------+
       |                                   |
       +---- MySQL [business/AI/outbox]    +---- Redis [cache/queue]
                       |                          ^         |
                       v                          |         v
               Outbox Dispatcher -----------------+       Worker
                                                          |
                                                  Mock Mailpit / email provider
```

- Service DNS names inside Compose (`api`, `mysql`, `redis`), not hard-coded container IP or `localhost` for container-to-container communication.
- At deployment only Nginx needs a public port; DB and Redis internal. Local developer overrides may publish troubleshooting ports intentionally.
- API/worker/dispatcher can share one backend image with distinct commands/entrypoints.
- Prefer healthchecks, explicit readiness, volumes and separate init job over migrations running from multiple API instances.
- **Docker Desktop is local development software**, not a production hosting requirement. Docker Compose works on other computers and an Ubuntu VPS if the project later needs it.
- Split dev/demo and production-like overrides when useful; NEVER auto-delete DB or seed/reset real deployment data.
- Backend module-first example, to adapt to actual repo:

```text
backend/app/
  core/       # configuration, security, exceptions, logging
  db/         # engine, sessions, shared DB setup
  modules/
    identity/
    clubs/
    events/
    tasks/
    notifications/
    ai/
  workers/
  main.py
backend/alembic/
backend/scripts/seed_demo.py
backend/scripts/reset_demo.py  # LOCAL-only, explicit destructive operation
backend/tests/{unit,integration,concurrency,security,...}/
frontend/{pages,css,js,assets}/
infra/
.github/workflows/
```

## 3. BUSINESS SCOPE AND ROLES — V1

### Roles/authorization

- Global roles: **Student** and **System Admin**.
- Club-scoped roles: **Member** and **Manager** (same account can hold different club memberships/roles).
- Backend MUST enforce resource-scoped RBAC/ownership; frontend hiding a button is NOT authorization. Explicitly test IDOR/BOLA and cross-club access.

### Agreed capabilities

1. Authentication and user/profile; access JWT + secure refresh token rotation, family tracking/revocation/reuse policy; role-protected screens.
2. Student proposes a new club; System Admin approves/rejects. On approval create Club + founding Manager membership **atomically** (proposed policy agreed as working baseline).
3. Students apply to join clubs; appropriate Manager approves/rejects; membership per club scoped to user; duplicates/races prevented.
4. Managers manage events; events can be public or members-only. **Non-members with registered accounts may sign up for public events**. Internal events require relevant active membership.
5. Event registration capacity is enforced under contention, no waitlist in V1. Active registration count must stay consistent with `events.registration_count`; handle cancellation/last-seat race and retries.
6. Managers assign event organization tasks **only to members of the event's organizing club**. Scoped progress access: appropriate Manager/assigned members, not arbitrary outsiders.
7. In-app notifications; asynchronous email notifications through worker and transactional outbox for selected important events.
8. AI conversational assistant with 4 read-only tools below; usage, turns, messages and tool-execution records.
9. Basic search/list/pagination and UI state/error handling for main flows.

### AI read-only tools (exact intended names)

- `list_upcoming_events`
- `get_my_registrations`
- `get_my_tasks`
- `get_event_progress`

Tool executor: allowlist; validate schemas; extract user from auth/JWT (never accept fabricated user_id as authority); call actual business service; enforce club/user/object-level permissions; bound output size; handle timeout/rate limit; log only safe metadata; treat untrusted LLM tool instructions/data cautiously. No arbitrary SQL, no autonomous privilege grant, no RAG required in V1. Provider/model choice should be verified at implementation; **do not assume a named model/API free tier exists without checking.**

### Business policy decisions still OPEN — must resolve before corresponding slice

- Last active Manager leaves a club: transfer/block/appoint? Define policy before membership leave.
- Member exits club while assigned event tasks: unassign, preserve history, block departure, etc.?
- Members-only registration when member subsequently leaves: cancel automatically or preserve?
- Club suspension / deletion effects on memberships/events/registrations.
- Event cancellation and capacity reduction: whether registrations remain as cancelled records, notifications, refund (not applicable unless introduced), etc.
- Event deadline, visibility and status transitions.
- Scope of retries/idempotency keys on distinct commands.

Do not silently invent policies inside Codex implementation.

## 4. DATABASE SOURCE OF TRUTH

- Companion schema file: **`scms_v1_3_outbox.dbml`**; **18-table baseline** (17 earlier domain/system tables + new `outbox_events`). Earlier schema V1.2 reported 29 FKs. V1.3 outbox uses polymorphic aggregate reference, so may add no FK, but validate from the actual DBML.
- Key tables: `users`, `refresh_token_families`, `refresh_tokens`, `club_creation_requests`, `clubs`, `membership_applications`, `club_memberships`, `events`, `event_registrations`, `event_tasks`, `notifications`, `audit_logs`, `ai_conversations`, `ai_turns`, `ai_messages`, `ai_usage_records`, `ai_tool_executions`, `outbox_events`.
- V1.2 carefully tightened `membership_applications` ↔ `club_memberships` provenance using composite FK `(source_application_id, club_id, user_id)` to `(id, club_id, user_id)` and supporting unique/index, preserving NULL founder source. Respect actual SQL syntax and MySQL 8 behavior.
- Database generated-column/nullable uniqueness approach was contemplated for unique active memberships/registrations; test DDL for MySQL 8 specifically.
- Event `capacity`, `registration_count`, optional `version`; ensure correct business invariant under concurrent register/cancel/change capacity. A CHECK `(0 <= registration_count <= capacity)` alone does **not** prove count equals actual active registrations.
- `event_tasks` composite FK constraints intended to enforce organizing club match; assignee *active status* is a service-level policy and must be checked under concurrency.
- Refresh token family/rotation: hashed opaque refresh tokens; expired/revoked states, reuse detection; cleanup must not invalidate state prematurely.
- `outbox_events` represents durable **intent to enqueue**, not confirmation email was received. Dispatcher lease/claim, retries and at-least-once publishing; worker needs idempotency/dedupe for DB effects. External email *exactly once* is NOT guaranteed.
- Existing DBML has **NOT YET BEEN VERIFIED as a valid MySQL deployment**. At Day 2 inspect DBML, render/parser where practical, build ORM + Alembic migration, test composite FKs/generated columns/indexes/checks against fresh MySQL 8. Correct documented schema differences via decision log. Do not assert final implementation based on diagram alone.

### Demo data setup

- Bootstrap flow: MySQL health/readiness → **one init job** `alembic upgrade head` → **demo-only idempotent seed** → API/worker start when prerequisites ready; do not let multiple API replicas each migrate.
- Demo seed: stable Student/Admin/Manager accounts, clubs, pending/approved/rejected applications, memberships across clubs, public/member-only events, full/almost-full events (e.g. capacity 20, registered 19), registrations, tasks with varied statuses, notifications.
- Separate deterministic demo seed from **isolated test fixtures**. Concurrency tests create their own database/test data, not rely on mutable demo data.
- `reset_demo.py` is explicit, guarded, local-only; **never auto-wipe volumes** in normal `docker compose up`.
- Credentials may be openly documented for local demo ONLY; no real secrets committed.

## 5. DEVELOPMENT METHOD & REVIEW CONTRACT

**Build along vertical slices, not `all CRUD → all concurrency → all infra → tests`**:

1. **Business contract**: actor, permissions, state transitions, DTOs/API, pre-/postconditions, error responses, failure cases.
2. **Design/invariants**: database constraints, transaction boundary, query plan, concurrency strategy, idempotency/cache/outbox when use case demands, alternatives/trade-offs.
3. **Codex implementation**: bounded scope including API/service/repository and minimal usable frontend.
4. **Tests**: unit, integration/API, object-authorization, concurrency, failure tests relevant to slice. Ideally specify acceptance tests BEFORE implementation.
5. **Review**: security correctness, DB transactions, logging, N+1/indexes, error handling, dependency boundaries, migrations; request evidence not just verbal assurances.
6. **Gate**: CI green + manually exercised UI + regression + decisions/docs updated + commit. Only then advance.

**Just-in-time infrastructure:** logging, test scaffolding, CI, MySQL schema and Docker Day 1–3; transactions/auth when implementing corresponding domain; Redis cache when public listing exists; outbox with first durable notification; queue/worker when async notification use case exists. Do not run six services on Day 1 merely for appearances.

**Engineering invariants**:

- DB is source of truth, Redis only derived cache/transient broker.
- Service owns commit/rollback; atomic business state + outbox insertion.
- Scoped auth on every relevant endpoint AND AI tool.
- Registration count never > capacity, never < 0, and reconciles with active registrations.
- Use real MySQL concurrency tests for locking semantics; mock unit tests are insufficient.
- At-least-once outbox + idempotent consumption; separate state enqueued vs email completed.
- Redis down should not compromise DB correctness; document whether cache/queue fail-open or fail-closed for each flow.
- Safe logs, `request_id` across API, `correlation_id` to worker/outbox; no passwords/tokens/keys/full private AI message logs.
- Measure performance, optimize only backed by evidence.
- No Docker image/README/CI claim counts as passing without run output.

## 6. DAILY EXECUTION ROADMAP (21 DAYS)

**Interpretation:** The deliverables below are *target* scope per day. Depth and sequencing can be adjusted based on actual code/test evidence, without silently deleting agreed V1 requirements.

### WEEK 1 — Foundation, Identity, Clubs (Days 01–07)

#### DAY 01 — Repository & Docker Foundation
- Create monorepo (`frontend`, `backend`, `infra`, `.github`).
- Module-first FastAPI skeleton, minimal `/health` endpoint, config loading.
- Nginx static frontend + reverse proxy `/api` to FastAPI; Dockerfiles.
- Basic `compose.yaml` + dev override: **nginx, api, mysql** only initially; MySQL volume/healthcheck; service networking; `.env.example`, `.gitignore`, README.
- **Acceptance**: `docker compose up -d --build` brings all 3 services healthy; from browser Nginx loads page and `/api/health` returns success; no exposed production credentials; no hard-coded container IP; verify restart. Do NOT prematurely mark MySQL migrations or full auth complete.
- **Deliverable**: repeatable scaffold on Docker Desktop.

#### DAY 02 — DBML Validation, ORM, Alembic & Seed
- Read actual V1.3 DBML; verify FKs/checks/indexes/uniqueness on MySQL 8; resolve schema discrepancies explicitly.
- Implement SQLAlchemy models, Alembic initial migration; review generated DDL, run on empty DB.
- Demo seed (deterministic, idempotent) and single bootstrap/init service; local guarded reset command; isolated DB for tests.
- **Acceptance**: fresh migration pass; seed twice no duplicates; restart keeps data; constraints verified with negative tests.
- **Deliverable**: DB bootstrap + populated demo.

#### DAY 03 — CI, Logging & Test Foundation
- Pytest/HTTPX, DB fixture infrastructure, unit/integration scaffolding.
- Ruff lint/format; GitHub Actions CI on PR/push: lint, tests, Docker build; integration job with isolated MySQL and migration.
- Structured JSON logging, request ID middleware, safe centralized exception handlers/error contract; healthchecks and basic instrumentation.
- **Acceptance**: CI green; logs correlate request, don't expose secrets; HTTP error mapping consistent.
- **Deliverable**: engineering quality gate.

#### DAY 04 — Authentication & Refresh Token Security
- Registration/login, secure password hashing, short-lived JWT access, hashed opaque refresh with rotation/family revocation/reuse policy.
- Cookies/storage + CSRF policy, rate limiting on auth endpoints (Redis introduced here if needed); frontend auth.
- **Acceptance**: happy path, expiry, logout, old refresh reuse, concurrent refresh, privilege checks, logs safe.
- **Deliverable**: authentication end to end.

#### DAY 05 — Club Creation & System Admin
- Student club-creation request; Admin approve/reject; state machine.
- Atomic approval creates club + founder Manager membership; audit entry; UI Admin.
- **Acceptance**: double approval no duplicate, injected failure rolls back, student cannot impersonate Admin.
- **Deliverable**: club creation approval workflow.

#### DAY 06 — Membership Lifecycle / Scope RBAC
- Apply to join, Manager approve/reject, club-scoped Member/Manager, leave/rejoin policy; preserve source application linkage.
- Deduplicate active memberships, handle concurrent approvals, optional outbox event for notification when introduced.
- **Acceptance**: cross-club IDOR denied, concurrent duplicate approval safe, duplicate active membership prevented.
- **Deliverable**: membership workflows.

#### DAY 07 — CHECKPOINT 1: Identity + Clubs
- Integrate auth/club/membership UI; seed multi-role demo; N+1/pagination check.
- Review transaction/auth/security tests, CI, decision log (ADR).
- **Acceptance**: Student requests club → Admin approves → Student joins → Manager approves; all scoped correctly end-to-end.
- **Deliverable**: demoable club management.

### WEEK 2 — Events, Concurrency, Tasks, Reliability Start (Days 08–14)

#### DAY 08 — Event Management
- Manager creates/updates/publishes/cancels event; public vs members-only, status/deadline/capacity rules; scoped edit.
- List/detail UI with status/error/loading; queries/filter/pagination.
- **Acceptance**: invalid state transition and unauthorized cross-club edit rejected.
- **Deliverable**: event lifecycle.

#### DAY 09 — Atomic Event Registration
- Register with MySQL transaction, conditional atomic update/locking, uniqueness, capacity counter; active membership for private events.
- Stable lock order, appropriate indexes, UI full/registered states.
- **Acceptance**: e.g. 50–100 concurrent attempts for one seat → exactly one success; capacity never exceeded; counter reconciles.
- **Deliverable**: registration concurrency proof.

#### DAY 10 — Cancellation / Idempotency / Races
- Cancel registration, restore capacity once; repeated requests; event cancellation, closing, capacity reduction consistent with registration path.
- Limited deadlock retry with correct rollback, idempotency where side effects warrant keys.
- **Acceptance**: double click/retries/concurrent register/cancel don't corrupt counts or oversell.
- **Deliverable**: resilient registration lifecycle.

#### DAY 11 — Task Assignment & Progress
- Manager assigns event tasks to currently active member of organizing club; scoped assignee update; progress aggregation.
- UI My Tasks / Manager task board; decide departure policy.
- **Acceptance**: no outsiders assigned, no cross-club data leak, progress permissions enforced.
- **Deliverable**: event tasks.

#### DAY 12 — CHECKPOINT 2: Complete Core Fullstack
- Integrate Student/Manager/Admin flows according to Figma; strengthen UX and domain edge states; demo fixture coverage.
- Regression security and concurrency; query counts / N+1.
- **Acceptance**: end-to-end demo across ≥2 clubs, events, capacity races, assigned tasks.
- **Deliverable**: stable fullstack business core.

#### DAY 13 — Redis Cache-Aside
- Cache appropriate public club/event list/detail; TTL/invalidation following DB commit; pagination/filter key design; fallback.
- Benchmark cache vs DB, test stale data & outage.
- **Acceptance**: cache hit/miss, invalidation and Redis-down graceful DB fallback; auth/capacity never depend on cache.
- **Deliverable**: measured caching.

#### DAY 14 — Notifications & Worker Queue
- Choose RQ or Celery explicitly (default proposal RQ for shorter setup); Redis queue; email integration via Mailpit/fake adapter; in-app notification workflow.
- Backoff/retry/logging/correlation. Do not silently direct-publish business critical jobs outside outbox once the outbox path is used.
- **Acceptance**: job async, provider failure retry, restart does not corrupt business state.
- **Deliverable**: worker-powered notifications.

### WEEK 3 — Outbox, AI, Portable Release (Days 15–21)

#### DAY 15 — Transactional Outbox Reliability
- Insert outbox in same business transaction. Dispatcher claims/reclaims and publishes to Redis queue; retry policy and DEAD status.
- Handle crash before publish and after publish before acknowledge; dedupe consumer DB effects; document external email semantics.
- **Acceptance**: no lost committed intent; duplicated publish safe for idempotent effects; dead-event observability.
- **Deliverable**: failure-tested outbox pipeline.

#### DAY 16 — CHECKPOINT 3: Reliability Integration
- Nginx + FastAPI + MySQL + Redis + Worker + Dispatcher (six runtime services); notifications/cache integration and recovery drills.
- Logging, health, connection pools, indexes, regression.
- **Acceptance**: controlled process restarts and transient outages recover; business correctness tests remain green.
- **Deliverable**: integrated six-service demo stack.

#### DAY 17 — AI Conversations & Orchestration
- AI conversation/turn/message persistence, provider adapter, configurable model, mock mode; cost/tokens/latency tracking.
- Timeout/rate limit/budget controls and basic AI UI; avoid premature complex AI leases.
- **Acceptance**: mock mode works without key; provider timeout fails safely; turn state/usage consistent.
- **Deliverable**: AI chat foundation.

#### DAY 18 — AI Tools & Permissions
- Implement the 4 read-only tools with allowlist, schema validation, JWT identity and business-service auth.
- Test prompt injection, forged IDs, data minimization, cross-user/cross-club access.
- **Acceptance**: no unauthorized data via any tool, including manipulated tool args.
- **Deliverable**: AI 3A+ connected to real data.

#### DAY 19 — AI + Full Regression / Feature Freeze
- Integrate UI/history, usage records and error UX; tool failures, latency; complete regression including security/perf/retries.
- Freeze new features; resolve blockers only.
- **Acceptance**: 4 tools work against seed, mock mode complete, permission and other critical tests green.
- **Deliverable**: feature-complete V1 release candidate.

#### DAY 20 — Portable Deployment Readiness
- Compose dev/demo setup, optional production-like override; README, env template, demo user accounts, health/readiness, safe secrets.
- CI green; backup/restore rehearsal and clean install.
- **Acceptance**: fresh clone/local docker environment → build → migrate → seed → login; restart retains DB.
- **Deliverable**: reproducible portable release candidate.

#### DAY 21 — FINAL EXAM / V1 RELEASE
- Walkthrough Student/Manager/Admin + AI four tools.
- Chaos/security proofs: same-seat race, Redis outage, worker crash, dispatcher crash, auth boundary attempts.
- Clean machine acceptance, docs/screenshots/test evidence; `v1.0` tag and post-V1 backlog.
- **Acceptance**: another person or genuinely clean Docker environment runs SCMS and demos full scope; reliable test evidence exists.
- **Deliverable**: SCMS V1.0 local Dockerized demo, no VPS required.

## 7. TEST & LOGGING EXPECTATIONS BY MODULE

| Area | Minimum test evidence | Logging/observability |
|---|---|---|
| Foundation | `/api/health`, compose bootstrap, restart | request ID, route, status, duration |
| Auth | unit/security/API; concurrent refresh/reuse | auth failures, token family anomalies without tokens |
| Clubs | transaction rollback, simultaneous approvals, BOLA | admin action audit, membership decision |
| Events | parallel last-seat requests, duplicate registration, cancellation races | event/reg IDs, conflict/error codes |
| Cache | hit/miss/invalidation, Redis outage fallback | cache latency/hit/miss if cheap |
| Worker/outbox | crash/retry/requeue/duplicate consumption | event/job ID, attempts, transition, correlation |
| AI | each tool authorized vs unauthorized, timeout, token limit, mock fallback | turn ID, tool name, result status, latency and token usage, not sensitive prompt body |
| Release | fresh-machine Compose smoke + DB persistence | logs available and privacy-safe |

**Testing and logging are part of EVERY slice; they are not postponed to Day 20.** Heavy load tests may run separately from each PR CI, but correctness-focused concurrency tests must exist.

## 8. MILESTONES, PRIORITIES, AND SCOPE CONTROL

- **Day 07:** End-to-end authentication/club/membership works with permissions.
- **Day 12:** Core business UI complete; concurrency registration proof passes.
- **Day 16:** Cache + worker + outbox integrated; failure/recovery verified.
- **Day 19:** AI 4 tools integrated, security regression, feature freeze.
- **Day 21:** Another machine/environment can run full project locally.

If late: prioritize **working end-to-end slices, test evidence, security, concurrency correctness and Docker portability** over UI polish, dashboards, additional provider integrations, broad abstractions. Do not eliminate agreed Redis/queue/outbox/AI entirely without a new explicit scope decision; reduce their breadth (e.g. one email-trigger event) first.

## 9. AFTER THE THREE WEEKS — NOT V1 REQUIREMENTS

Potential **V1.5 / V2** learning backlog, NOT pre-committed implementation:

- Redis distributed locking vs SQL-native concurrency, leases, fencing and failure modes (only if use case warrants).
- Higher-level AI orchestration: serializing by conversation, AI turn recovery/leases/fencing, write tools requiring explicit confirmation, RAG only for justified unstructured corpora.
- Advanced scalability/performance: systematic load tests, multi-instance app deployments, cache stampede mitigation, connection-pool tuning, benchmark-driven index/query refactors.
- Operations: production VPS deployment if later desired, HTTPS/TLS, firewall, automated CD, backups offsite, disaster recovery, HA when needed.
- Observability stack: OpenTelemetry tracing, Prometheus/Grafana, centralized logs, alerting.
- Advanced queue/delivery: broker persistence trade-offs, deeper DLQ/reconciliation, stronger consumer dedupe and workflow monitoring.
- Security hardening: threat modeling, audit retention, suspicious refresh/activity detection.
- Product: QR check-in, event waitlist, analytics, richer admin UI, feedback-driven features.
- **Do not introduce microservices, Kubernetes, Kafka or React by default.**

## 10. HOW TO START A NEW CHAT AND WORK WITH CODEX

### Initial message to a fresh ChatGPT conversation

> Tôi đang làm **SCMS — Student Club Management System V1 trong 21 ngày**, đồ án fullstack cá nhân có Docker Compose, FastAPI, MySQL, Redis, Worker, Transactional Outbox, AI read-only 3A+, tests và logging. **Hãy đọc kỹ file `SCMS_MASTER_CONTEXT.md` đính kèm; coi đây là source of truth cho roadmap và quyết định kiến trúc.** Khi cần DB schema, đọc thêm `scms_v1_3_outbox.dbml`, không tự đoán tên cột. Tôi đang ở **Day X/21**, tiến độ thực tế ghi trong Progress Log. Hãy làm Senior Backend Engineer/Technical Lead: trước khi giao Codex code, giải thích các trade-offs, đưa checklist, acceptance tests, review gates và prompt thực thi phạm vi hẹp; không mở rộng scope sang V2.

### Recommended request for one day

> SCMS Day X/21. Dựa vào master context và trạng thái repo hiện tại, hãy: (1) xác minh tiến độ và prerequisites, (2) các kiến trúc phải quyết định hôm nay và alternatives, (3) task list có ưu tiên/P0-P1, (4) acceptance tests đủ cả positive/negative/failure/concurrency khi liên quan, (5) Codex implementation prompt giới hạn files/scope, (6) các tiêu chí review và bằng chứng cần chạy, (7) cập nhật Progress Log để chuyển chat ngày tiếp theo. Đừng tự tuyên bố task pass khi chưa có kết quả chạy thực tế.

### Typical Codex prompt contract

- **Context**: current architecture, real repository facts, schema DBML/migration, relevant ADRs.
- **Goal**: one vertical slice or bounded foundation piece.
- **Allowed scope**: target directories/files; explicitly note deferred work.
- **Constraints**: no unauthorized architecture changes, new libraries without explanation, surprise DB schema changes, business policies invented, unnecessary abstractions.
- **Correctness**: invariants, DB transactions, resource-scoped access, error cases and idempotency where warranted.
- **Tests**: create relevant tests; report exact command and pass/fail output; do not fake results.
- **Definition of Done**: builds, tests, lint, migrations, Compose behavior, documentation/ADR, summary of unresolved issues.

### Git/review practice

For solo SCMS, main + short-lived feature branches with PRs are sufficient; `develop` is optional, unlike team-six workflow. Preserve practical CI quality gates. One major high-risk review at design stage, focused code/security/concurrency review at implementation stage, then test evidence; no repeated full-project analysis every small commit.

## 11. PROGRESS LOG — UPDATE AFTER EACH DAY

**Current status at document creation:** Project V1 scope and 21-day roadmap agreed. **DAY 01 NOT STARTED / NO TASKS VERIFIED.** Prior FastAPI Project Management project and Docker/Nginx experience are *background*, not evidence of SCMS implementation.

Use the template and append one block per completed or paused day:

```md
### SCMS Day NN — YYYY-MM-DD — STATUS: NOT STARTED | IN PROGRESS | BLOCKED | VERIFIED
- Branch / commit / PR: ...
- Implemented (based on code inspection): ...
- Tests run and results (include commands): ...
- Docker / environment status: ...
- Important architectural decisions (ADR): ...
- Schema / migration changes: ...
- Open bugs and tech debt: ...
- Deferred work: ...
- Next day prerequisites: ...
- Evidence links or filenames: ...
```

**Single source of truth for actual execution** should ultimately be the **repository**: keep this context and a `docs/progress.md`/ADRs committed and updated. Memory summaries and chat claims are secondary. Do not assume edits to this downloaded file automatically synchronize across new chats; reattach the latest version or store/update it in GitHub.

## 12. KEY REFERENCES AND STATUS

- **Figma SCMS design** (user-owned design file): `https://www.figma.com/design/fMT21zR5lj3alq8D8RHaVK` — prior discussion identified 3 pages with desktop/mobile and UI states; verify against latest design when implementing.
- **DBML V1.3**: `scms_v1_3_outbox.dbml` is supplied separately with this context package. The **actual DBML** takes precedence for exact fields/constraints. MySQL schema verification still pending.
- **Prior detailed roadmap**: embedded in Section 6; avoid requesting old chat solely to retrieve phase/day breakdown.
- **Outbox V1.3 concept**: outbox state enum PENDING/PROCESSING/PUBLISHED/DEAD; claim/retry metadata; validate exact fields in actual file. PUBLISHED does not mean delivered.
- **Provider decisions pending**: RQ vs Celery; current AI model/provider availability; specific email mock/provider; optional host for public preview.
- **Production deployment**: consciously OUT of scope. Local portable demo with Docker is IN scope.

---

**AI HANDOFF RULE:** Never start by rebuilding the entire roadmap from scratch. Read the user's current day, last verified Progress Log, relevant repo files and DBML, then proceed with the next bounded engineering task and its verifiable acceptance gate.
