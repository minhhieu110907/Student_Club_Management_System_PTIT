# SCMS backend

Minimal FastAPI foundation for the Student Club Management System.

## Local development

From the `backend/` directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install -e ".[test]" --no-deps
python -m pytest -m "not integration"
python -m uvicorn app.main:app --reload
```

Health endpoints are available at:

- `GET /api/v1/health` — backward-compatible process health.
- `GET /api/v1/health/live` — dependency-free liveness.
- `GET /api/v1/health/ready` — MySQL connectivity and Alembic revision readiness.

## Docker

From the `backend/` directory:

```powershell
docker build -t scms-backend .
docker run --rm -p 8000:8000 scms-backend
```

The Docker image installs the exact versions in `requirements.lock`. The local
test command uses the same locked runtime dependencies and adds only Pytest and
HTTPX from the test extra.

No database, cache, frontend, or other infrastructure is required for this slice.

## Quality commands

Run these commands from `backend/` after installing the locked dependencies and
the test extra shown above.

The initial Ruff scope is intentionally limited to the application/testing
foundation below. The verified ORM models, Alembic revision, database parity
tests, integration tests, and seed implementation remain outside formatting
scope until a separately reviewed cleanup.

```powershell
# Lint the approved foundation scope.
python -m ruff check app/main.py app/core app/health app/db/session.py scripts/create_ci_databases.py tests/conftest.py tests/test_health.py tests/test_logging.py tests/test_exception_handlers.py tests/test_pytest_contract.py tests/integration/test_health_readiness.py

# Verify formatting without rewriting files.
python -m ruff format --check app/main.py app/core app/health app/db/session.py scripts/create_ci_databases.py tests/conftest.py tests/test_health.py tests/test_logging.py tests/test_exception_handlers.py tests/test_pytest_contract.py tests/integration/test_health_readiness.py

# Ordinary, database-independent tests.
python -m pytest -m "not integration"

# Local integration selection. Tests skip safely when disposable URLs are absent.
python -m pytest -m integration

# CI integration selection. Missing URLs, missing integration modules, or skipped
# integration tests make the command fail.
python -m pytest -m integration --require-integration-env

# Full collection; integration tests retain their environment safety guards.
python -m pytest
```

CI integration mode requires all seven disposable database variables:
`SCMS_MYSQL_INTEGRATION_URL`, `SCMS_SEED_INTEGRATION_URL`,
`SCMS_SEED_ROLLBACK_URL`, `SCMS_SEED_CONFLICT_URL`,
`SCMS_READINESS_READY_URL`, `SCMS_READINESS_EMPTY_URL`, and
`SCMS_READINESS_WRONG_URL`. Never point these at a shared or development
database.

## GitHub Actions

[`backend-ci.yml`](../.github/workflows/backend-ci.yml) runs on pushes and pull
requests for `main` and `develop` with read-only repository permissions:

- **Quality** installs the lockfile, runs `pip check`, the explicit transitional
  Ruff scope, and every database-independent test.
- **MySQL integration** starts a fresh MySQL 8.4.4 service, creates isolated
  schemas, applies migrations explicitly, and runs every integration module in
  fail-closed mode. No repository secret or persistent database volume is used.
- **Docker build** builds the production backend image without publishing it.

The CI-only schema helper refuses to run unless `CI=true` and MySQL is on a
loopback host. Integration URLs must always target disposable schemas. If the
integration job reports missing URLs, skipped tests, or incomplete module
collection, treat that as a CI configuration failure rather than bypassing the
guard.
