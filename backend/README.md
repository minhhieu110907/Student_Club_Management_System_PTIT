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

The health endpoint is available at <http://127.0.0.1:8000/api/v1/health>.

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
python -m ruff check app/main.py app/db/session.py tests/conftest.py tests/test_health.py tests/test_pytest_contract.py

# Verify formatting without rewriting files.
python -m ruff format --check app/main.py app/db/session.py tests/conftest.py tests/test_health.py tests/test_pytest_contract.py

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

CI integration mode requires all four disposable database variables:
`SCMS_MYSQL_INTEGRATION_URL`, `SCMS_SEED_INTEGRATION_URL`,
`SCMS_SEED_ROLLBACK_URL`, and `SCMS_SEED_CONFLICT_URL`. Never point these at a
shared or development database.
