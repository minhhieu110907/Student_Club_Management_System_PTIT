from __future__ import annotations

import os
from pathlib import Path

import pytest

REQUIRED_INTEGRATION_ENV = (
    "SCMS_MYSQL_INTEGRATION_URL",
    "SCMS_SEED_INTEGRATION_URL",
    "SCMS_SEED_ROLLBACK_URL",
    "SCMS_SEED_CONFLICT_URL",
    "SCMS_READINESS_READY_URL",
    "SCMS_READINESS_EMPTY_URL",
    "SCMS_READINESS_WRONG_URL",
)
REQUIRED_INTEGRATION_MODULES = {
    "tests/integration/test_health_readiness.py",
    "tests/integration/test_mysql_schema.py",
    "tests/integration/test_seed.py",
}
APPROVED_INTEGRATION_TEST_COUNT = 13


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-integration-env",
        action="store_true",
        default=False,
        help="Fail closed unless every disposable MySQL integration URL is configured.",
    )


def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("--require-integration-env"):
        return

    if config.option.markexpr.strip() != "integration":
        raise pytest.UsageError(
            "--require-integration-env must be used with exactly '-m integration'"
        )
    if config.option.keyword.strip():
        raise pytest.UsageError("CI integration mode forbids '-k' test filtering")

    missing = [name for name in REQUIRED_INTEGRATION_ENV if not os.getenv(name)]
    if missing:
        raise pytest.UsageError(
            "CI integration mode requires disposable database URLs: " + ", ".join(missing)
        )


def pytest_collection_finish(session: pytest.Session) -> None:
    integration_items = [
        item for item in session.items if item.get_closest_marker("integration") is not None
    ]
    integration_paths = {
        Path(item.path).relative_to(session.config.rootpath).as_posix()
        for item in integration_items
    }

    unmarked_integration_items = [
        item.nodeid
        for item in session.items
        if "/integration/" in f"/{Path(str(item.path)).as_posix()}"
        and item.get_closest_marker("integration") is None
    ]
    if unmarked_integration_items:
        raise pytest.UsageError(
            "Integration tests must carry the integration marker: "
            + ", ".join(unmarked_integration_items)
        )

    if not session.config.getoption("--require-integration-env"):
        return

    missing_modules = REQUIRED_INTEGRATION_MODULES - integration_paths
    if missing_modules:
        raise pytest.UsageError(
            "CI integration collection is incomplete; missing modules: "
            + ", ".join(sorted(missing_modules))
        )
    if len(integration_items) != APPROVED_INTEGRATION_TEST_COUNT:
        raise pytest.UsageError(
            "CI integration collection must select exactly "
            f"{APPROVED_INTEGRATION_TEST_COUNT} approved tests; "
            f"selected {len(integration_items)}"
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not session.config.getoption("--require-integration-env"):
        return

    terminal_reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = [] if terminal_reporter is None else terminal_reporter.stats.get("skipped", [])
    if exitstatus == pytest.ExitCode.OK and skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        if terminal_reporter is not None:
            terminal_reporter.write_line(
                "CI integration mode failed closed because integration tests were skipped",
                red=True,
            )
