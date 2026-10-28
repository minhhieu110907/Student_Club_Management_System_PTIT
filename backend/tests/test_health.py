from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

from app.health.service import (
    DATABASE_TIMEOUT_SECONDS,
    EXPECTED_ALEMBIC_REVISION,
    ReadinessService,
    build_readiness_service,
)
from app.main import app, create_app


class FakeScalarResult:
    def __init__(
        self,
        revision_rows: tuple[str, ...],
        error: Exception | None = None,
    ) -> None:
        self.revision_rows = revision_rows
        self.error = error

    def one(self) -> str:
        if self.error is not None:
            raise self.error
        if not self.revision_rows:
            raise NoResultFound
        if len(self.revision_rows) > 1:
            raise MultipleResultsFound
        return self.revision_rows[0]


class FakeResult:
    def __init__(self, scalar_result: FakeScalarResult) -> None:
        self.scalar_result = scalar_result

    def scalars(self) -> FakeScalarResult:
        return self.scalar_result


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(
        self,
        *,
        revision_rows: tuple[str, ...] = (EXPECTED_ALEMBIC_REVISION,),
        revision_error: Exception | None = None,
    ) -> None:
        self.revision_rows = revision_rows
        self.revision_error = revision_error
        self.queries: list[str] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def scalar(self, statement: Any) -> int:
        query = str(statement)
        self.queries.append(query)
        assert query == "SELECT 1"
        return 1

    def execute(self, statement: Any) -> FakeResult:
        query = str(statement)
        self.queries.append(query)
        assert query == "SELECT version_num FROM alembic_version"
        return FakeResult(FakeScalarResult(self.revision_rows, self.revision_error))


class FakeEngine:
    def __init__(
        self,
        connection: FakeConnection | None = None,
        error: Exception | None = None,
    ) -> None:
        self.connection = connection or FakeConnection()
        self.error = error
        self.connect_calls = 0
        self.dispose_calls = 0

    def connect(self) -> FakeConnection:
        self.connect_calls += 1
        if self.error is not None:
            raise self.error
        return self.connection

    def dispose(self) -> None:
        self.dispose_calls += 1


def _service(engine: FakeEngine | None) -> ReadinessService:
    return ReadinessService(cast(Any, engine))


class DisposableResource:
    def __init__(self, dispose_error: BaseException | None = None) -> None:
        self.dispose_error = dispose_error
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1
        if self.dispose_error is not None:
            raise self.dispose_error


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_succeeds_without_starting_database_lifecycle() -> None:
    response = TestClient(app).get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_lifespan_disposes_readiness_and_database_resources() -> None:
    readiness = DisposableResource()
    database = DisposableResource()
    test_app = create_app(lambda: cast(Any, readiness), lambda: cast(Any, database))

    with TestClient(test_app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        assert readiness.dispose_calls == 0
        assert database.dispose_calls == 0

    assert database.dispose_calls == 1
    assert readiness.dispose_calls == 1


def test_database_startup_failure_disposes_readiness_and_preserves_original_error() -> None:
    cleanup_error = RuntimeError("secondary cleanup failure")
    readiness = DisposableResource(cleanup_error)
    startup_error = ValueError("invalid configured database")

    def fail_database_startup():
        raise startup_error

    test_app = create_app(
        lambda: cast(Any, readiness),
        cast(Any, fail_database_startup),
    )

    with pytest.raises(ValueError) as raised:
        with TestClient(test_app):
            pass

    assert raised.value is startup_error
    assert readiness.dispose_calls == 1


def test_readiness_without_database_url_returns_safe_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    test_app = create_app(build_readiness_service)

    with TestClient(test_app) as client:
        response = client.get(
            "/api/v1/health/ready",
            headers={"X-Request-ID": "readiness-request-id"},
        )

    assert response.status_code == 503
    assert response.headers["X-Request-ID"] == "readiness-request-id"
    assert response.json() == {
        "success": False,
        "message": "Service is not ready",
        "error_code": "NOT_READY",
        "details": None,
        "request_id": "readiness-request-id",
    }


def test_unreachable_database_returns_safe_503() -> None:
    error = OperationalError("SELECT 1", {}, RuntimeError("password=secret"))
    engine = FakeEngine(error=error)
    test_app = create_app(lambda: _service(engine))

    with TestClient(test_app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error_code"] == "NOT_READY"
    assert "secret" not in response.text
    assert "SELECT" not in response.text


def test_empty_database_returns_503() -> None:
    connection = FakeConnection(revision_rows=())
    engine = FakeEngine(connection)
    test_app = create_app(lambda: _service(engine))

    with TestClient(test_app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error_code"] == "NOT_READY"
    assert connection.queries == ["SELECT 1", "SELECT version_num FROM alembic_version"]


def test_multiple_migration_revisions_return_503() -> None:
    connection = FakeConnection(revision_rows=(EXPECTED_ALEMBIC_REVISION, "second_head"))
    engine = FakeEngine(connection)
    test_app = create_app(lambda: _service(engine))

    with TestClient(test_app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error_code"] == "NOT_READY"


def test_revision_query_error_returns_503() -> None:
    missing_version_table = ProgrammingError(
        "SELECT version_num", {}, RuntimeError("table missing")
    )
    connection = FakeConnection(revision_error=missing_version_table)
    engine = FakeEngine(connection)
    test_app = create_app(lambda: _service(engine))

    with TestClient(test_app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error_code"] == "NOT_READY"
    assert connection.queries == ["SELECT 1", "SELECT version_num FROM alembic_version"]
    assert "table missing" not in response.text


def test_wrong_migration_revision_returns_503() -> None:
    engine = FakeEngine(FakeConnection(revision_rows=("wrong_revision",)))
    test_app = create_app(lambda: _service(engine))

    with TestClient(test_app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error_code"] == "NOT_READY"


def test_correct_database_and_revision_return_ready() -> None:
    connection = FakeConnection()
    engine = FakeEngine(connection)
    test_app = create_app(lambda: _service(engine))

    with TestClient(test_app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert connection.queries == ["SELECT 1", "SELECT version_num FROM alembic_version"]


def test_readiness_reuses_engine_and_disposes_it_on_shutdown() -> None:
    engine = FakeEngine()
    factory_calls = 0

    def factory() -> ReadinessService:
        nonlocal factory_calls
        factory_calls += 1
        return _service(engine)

    test_app = create_app(factory)
    with TestClient(test_app) as client:
        assert client.get("/api/v1/health/ready").status_code == 200
        assert client.get("/api/v1/health/ready").status_code == 200
        assert engine.dispose_calls == 0

    assert factory_calls == 1
    assert engine.connect_calls == 2
    assert engine.dispose_calls == 1


def test_engine_configuration_uses_bounded_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    engine = FakeEngine()

    def fake_create_engine(database_url: str, **options: Any) -> Any:
        captured["database_url"] = database_url
        captured.update(options)
        return engine

    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://health-only.invalid/scms")
    monkeypatch.setattr("app.health.service.create_db_engine", fake_create_engine)

    service = build_readiness_service()

    assert service.engine is engine
    assert captured["pool_pre_ping"] is True
    assert captured["pool_timeout"] == DATABASE_TIMEOUT_SECONDS
    assert captured["connect_args"] == {
        "connect_timeout": DATABASE_TIMEOUT_SECONDS,
        "read_timeout": DATABASE_TIMEOUT_SECONDS,
        "write_timeout": DATABASE_TIMEOUT_SECONDS,
    }
