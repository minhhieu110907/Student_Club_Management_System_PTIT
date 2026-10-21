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
python -m pytest
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
