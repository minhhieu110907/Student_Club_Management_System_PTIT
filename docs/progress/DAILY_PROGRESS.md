### SCMS Day 01 — 2026-10-21 — STATUS: VERIFIED
- Branch / commit / PR: `feature/day01-foundation`; Slice 01 commit `39bc66f`; Slice 02 commit `71d73de`; no PR recorded.
- Implemented (based on code inspection):
  - Slice 01: Minimal FastAPI skeleton with Python 3.12 packaging, locked dependencies, non-root Docker runtime, `GET /api/v1/health`, and Pytest/HTTPX health endpoint coverage.
  - Slice 02: Nginx static frontend and `/api/` reverse proxy, Docker Compose stack for Nginx/FastAPI/MySQL 8.4.4, named MySQL volume, separated `edge` and internal `data` networks, API healthcheck, and authenticated MySQL `SELECT 1` healthcheck.
- Tests run and results (include commands):
  - `python -m pytest` from `backend/`: PASS — health endpoint test passed.
  - `docker compose up -d --build`: PASS — images built and all three services started.
  - Proxied `GET http://localhost:8080/api/v1/health`: PASS — returned `{"status":"ok"}`.
  - Persistence check: PASS — a MySQL test record survived container recreation; the temporary test table was removed afterward.
- Docker / environment status: Nginx, API, and MySQL were running; API and MySQL reported healthy. Nginx served the frontend at `http://localhost:8080` and proxied API requests through the Compose service name `api`.
- Important architectural decisions (ADR): Only Nginx publishes an application host port. Nginx and API share the `edge` network; API and MySQL share the internal `data` network. MySQL persists data in the named `mysql_data` volume. No separate ADR was required for this foundation slice.
- Schema / migration changes: None. DBML V1.3 was not modified, and no SQLAlchemy models, Alembic migrations, or application schema were created on Day 01.
- Open bugs and tech debt: No known Day 01 blocker. Database schema correctness against MySQL 8.4.4 remains unverified until the Day 02 ORM/Alembic work.
- Deferred work: Business modules, authentication, SQLAlchemy models, Alembic migrations, seed data, Redis, workers, transactional outbox processing, and AI integration.
- Next day prerequisites: Implement SQLAlchemy models and the initial Alembic migration, then verify generated MySQL schema constraints, indexes, foreign keys, and generated-column behavior against DBML V1.3.
- Evidence links or filenames: `backend/app/main.py`, `backend/tests/test_health.py`, `backend/Dockerfile`, `backend/requirements.lock`, `compose.yaml`, `frontend/nginx.conf`, `frontend/index.html`, `.env.example`, `README.md`, and `docs/database/scms_v1_3_outbox.dbml`.

### SCMS Day 02 — 2026-10-26 — STATUS: VERIFIED
- Branch / commits: `feature/day02-database`; ORM `0bf1cbe`; Alembic `b87f6eb`; live MySQL verification `e0583c7`; deterministic seed `1352505`; merged to `main` by PR #3 (`25a7c3f`).
- Slice 01: Database Audit completed against DBML V1.3.
- Slice 02: SQLAlchemy 2.x Typed Declarative ORM mappings completed for all 18 tables using the shared metadata registry and modular domain-first organization.
- Metadata parity verification: PASS — 29 foreign key constraints including 4 composite foreign keys, 17 named CHECK constraints, 20 non-primary-key unique keys, 5 STORED generated columns, and 6 approved FK-supporting indexes.
- Python 3.12 Docker verification: PASS on Python 3.12.15 — metadata tests 7/7, health test 1/1, and full test suite 8/8.
- Dependency status: Runtime and test dependencies were resolved and locked in a clean Python 3.12 environment; the Pytest 8.x project contract is preserved.
- Known issue / deferred review: `ai_usage_records.estimated_cost` currently uses Python `float` typing for a MySQL `DECIMAL(18,8)` column; Python typing is deferred for later review.
- Alembic / physical verification: Initial revision `20261026_01` was added and verified against disposable MySQL 8.4.4 resources; development MySQL and persistent volumes were not used.
- Deterministic demo seed: Added for all 18 tables with idempotency, rollback, collision, environment-guard, relationship, and business-invariant integration coverage.
- Deferred work: `ai_usage_records.estimated_cost` Python `float` typing remains deferred for later review. No production/shared database migration was performed.

### SCMS Day 03 — 2026-10-27 — STATUS: IN PROGRESS
- Branch / commits: `feature/day03-quality-gate`; pytest/Ruff `ce73bba`; structured logging/request correlation `5ecd7a8`; centralized exception handling `05592ee`; liveness/readiness `9a87379`; GitHub Actions Slice 05 remains uncommitted for owner review.
- Implemented (based on code inspection): Strict pytest markers and integration fail-closed contract; transitional Ruff scope; JSON application/access logging; validated request IDs with async context isolation; standard secure API error responses; dependency-free liveness; pooled MySQL/Alembic readiness with bounded timeouts and shutdown disposal.
- Current Slice 05 candidate: Three-job GitHub Actions workflow for quality, isolated MySQL 8.4.4 integration, and production Docker build. Readiness integration adds migrated, empty, wrong-revision, and missing-URL cases.
- Tests run for Slice 05 candidate: Python 3.12 ordinary suite PASS (`51 passed, 13 deselected`); integration collection PASS (`13/64 collected`, comprising 9 existing and 4 readiness tests); missing-URL CI mode failed closed with expected pytest exit 4; disposable MySQL 8.4.4 integration PASS (`13 passed, 51 deselected`); `pip check` PASS; workflow YAML structural parse PASS; local production Docker build PASS.
- Docker / environment status: Ordinary verification used `--network none`. Live integration used one uniquely named/labeled MySQL 8.4.4 container with tmpfs data and a random loopback-only host port; ownership cleanup passed with no run resources remaining. The production image built locally without push. The GitHub-hosted workflow itself has not yet run and remains NOT VERIFIED pending owner review/CI.
- Safety decisions: CI uses synthetic credentials, a fresh MySQL service without persistent volumes, explicit migrations, seven isolated schemas, and a helper that refuses non-CI or non-loopback targets. Existing Windows verification harnesses and Compose topology are unchanged.
- Open issue: Existing `StarletteDeprecationWarning` for the current `httpx`/`TestClient` combination remains non-blocking. Day 03 must not be marked complete until the workflow runs successfully and the owner approves it.
