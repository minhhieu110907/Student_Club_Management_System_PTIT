from __future__ import annotations

import pytest

from scripts import bootstrap_demo
from scripts.seed import SeedError


class _FakeDialect:
    def __init__(self, name: str = "mysql") -> None:
        self.name = name


class _FakeConnection:
    def __init__(self, scalar_results: list[object]) -> None:
        self._scalar_results = list(scalar_results)

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalar(self, *_args: object, **_kwargs: object) -> object:
        return self._scalar_results.pop(0) if self._scalar_results else None


class _FakeEngine:
    def __init__(self, scalar_results: list[object], *, dialect: str = "mysql") -> None:
        self.dialect = _FakeDialect(dialect)
        self._scalar_results = scalar_results

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._scalar_results)

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self._scalar_results)


def test_bootstrap_skips_seed_when_flag_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCMS_ALLOW_DEMO_SEED", "0")
    monkeypatch.setenv("SCMS_ENV", "demo")
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(bootstrap_demo, "_seed", fail_if_called)
    bootstrap_demo._maybe_seed_demo(_FakeEngine([]))
    assert called is False


def test_bootstrap_refuses_seed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCMS_ALLOW_DEMO_SEED", "1")
    monkeypatch.setenv("SCMS_ENV", "production")
    with pytest.raises(SeedError, match="development, demo, or test"):
        bootstrap_demo._maybe_seed_demo(_FakeEngine([]))


def test_bootstrap_skips_seed_when_database_already_has_non_demo_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCMS_ALLOW_DEMO_SEED", "1")
    monkeypatch.setenv("SCMS_ENV", "demo")
    called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(bootstrap_demo, "_seed", fail_if_called)
    # First scalar query (`SELECT 1 FROM users LIMIT 1`) returns 1 (existing non-demo user)
    bootstrap_demo._maybe_seed_demo(_FakeEngine([1, None]))
    assert called is False


def test_bootstrap_requires_demo_password_or_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCMS_ALLOW_DEMO_SEED", "1")
    monkeypatch.setenv("SCMS_ENV", "demo")
    monkeypatch.delenv("SCMS_DEMO_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("SCMS_DEMO_PASSWORD", raising=False)
    with pytest.raises(SeedError, match="SCMS_DEMO_PASSWORD_HASH or SCMS_DEMO_PASSWORD"):
        bootstrap_demo._maybe_seed_demo(_FakeEngine([None, None]))
