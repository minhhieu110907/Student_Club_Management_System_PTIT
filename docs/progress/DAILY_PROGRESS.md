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

### SCMS Day 02 — 2026-10-26 — STATUS: IN PROGRESS
- Owner approval: Slice 01 and Slice 02 passed owner review and are approved for commit; no commit is recorded yet.
- Slice 01: Database Audit completed against DBML V1.3.
- Slice 02: SQLAlchemy 2.x Typed Declarative ORM mappings completed for all 18 tables using the shared metadata registry and modular domain-first organization.
- Metadata parity verification: PASS — 29 foreign key constraints including 4 composite foreign keys, 17 named CHECK constraints, 20 non-primary-key unique keys, 5 STORED generated columns, and 6 approved FK-supporting indexes.
- Python 3.12 Docker verification: PASS on Python 3.12.15 — metadata tests 7/7, health test 1/1, and full test suite 8/8.
- Dependency status: Runtime and test dependencies were resolved and locked in a clean Python 3.12 environment; the Pytest 8.x project contract is preserved.
- Known issue / deferred review: `ai_usage_records.estimated_cost` currently uses Python `float` typing for a MySQL `DECIMAL(18,8)` column; Python typing is deferred for later review.
- Pending work: Physical schema verification against MySQL 8.4.4 and the initial Alembic migration remain pending. No migration or real MySQL schema change was performed in Slice 02.
