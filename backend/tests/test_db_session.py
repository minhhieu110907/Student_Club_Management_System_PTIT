from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.db.session import DatabaseResources, build_database_resources, get_db_session


def test_database_resources_are_optional_without_configuration(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert build_database_resources() is None


def test_database_resources_build_shared_engine_and_factory(monkeypatch) -> None:
    engine = MagicMock()
    session_factory = MagicMock()
    create_engine = MagicMock(return_value=engine)
    create_factory = MagicMock(return_value=session_factory)
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://configured/scms")
    monkeypatch.setattr("app.db.session.create_db_engine", create_engine)
    monkeypatch.setattr("app.db.session.create_session_factory", create_factory)

    resources = build_database_resources()

    assert resources == DatabaseResources(engine=engine, session_factory=session_factory)
    create_engine.assert_called_once_with("mysql+pymysql://configured/scms", pool_pre_ping=True)
    create_factory.assert_called_once_with(engine)


def test_invalid_configured_database_url_propagates(monkeypatch) -> None:
    configuration_error = ValueError("malformed database URL")
    monkeypatch.setenv("DATABASE_URL", "malformed")
    monkeypatch.setattr(
        "app.db.session.create_db_engine", MagicMock(side_effect=configuration_error)
    )

    with pytest.raises(ValueError) as raised:
        build_database_resources()

    assert raised.value is configuration_error


def test_database_resources_dispose_owned_engine() -> None:
    engine = MagicMock()
    resources = DatabaseResources(engine=engine, session_factory=MagicMock())

    resources.dispose()

    engine.dispose.assert_called_once_with()


def test_request_session_is_reused_closed_and_not_committed() -> None:
    engine = MagicMock()
    session = MagicMock()
    resources = DatabaseResources(engine=engine, session_factory=MagicMock(return_value=session))
    dependency = get_db_session(
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_resources=resources)))
    )

    assert next(dependency) is session
    with pytest.raises(StopIteration):
        next(dependency)

    session.close.assert_called_once_with()
    session.commit.assert_not_called()


def test_request_session_rolls_back_on_error() -> None:
    session = MagicMock()
    resources = DatabaseResources(
        engine=MagicMock(), session_factory=MagicMock(return_value=session)
    )
    dependency = get_db_session(
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_resources=resources)))
    )
    next(dependency)

    with pytest.raises(RuntimeError, match="failure"):
        dependency.throw(RuntimeError("failure"))

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
