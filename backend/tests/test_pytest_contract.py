from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = BACKEND_ROOT / "pyproject.toml"
INTEGRATION_URLS = (
    "SCMS_MYSQL_INTEGRATION_URL",
    "SCMS_SEED_INTEGRATION_URL",
    "SCMS_SEED_ROLLBACK_URL",
    "SCMS_SEED_CONFLICT_URL",
    "SCMS_READINESS_READY_URL",
    "SCMS_READINESS_EMPTY_URL",
    "SCMS_READINESS_WRONG_URL",
    "SCMS_REGISTRATION_INTEGRATION_URL",
)
APPROVED_INTEGRATION_TEST_COUNT = 26


def _integration_environment(*, include_urls: bool) -> dict[str, str]:
    environment = os.environ.copy()
    for index, name in enumerate(INTEGRATION_URLS):
        if include_urls:
            environment[name] = f"mysql+pymysql://placeholder/schema_{index}"
        else:
            environment.pop(name, None)
    return environment


def _collect_integration(
    *extra_arguments: str,
    include_urls: bool = True,
    require_ci_mode: bool = True,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        sys.executable,
        "-m",
        "pytest",
        "--config-file",
        str(PYPROJECT_PATH),
        "--collect-only",
        "-m",
        "integration",
    ]
    if require_ci_mode:
        arguments.append("--require-integration-env")
    arguments.extend(extra_arguments)
    arguments.append("tests/integration")
    return subprocess.run(
        arguments,
        cwd=BACKEND_ROOT,
        env=_integration_environment(include_urls=include_urls),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_unknown_pytest_marker_is_rejected(tmp_path: Path) -> None:
    test_file = tmp_path / "test_unknown_marker.py"
    test_file.write_text(
        "import pytest\n\n@pytest.mark.not_registered\ndef test_example():\n    pass\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--config-file",
            str(PYPROJECT_PATH),
            "--collect-only",
            str(test_file),
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode != 0
    assert "not found in `markers` configuration option" in result.stdout + result.stderr


def test_ci_integration_mode_requires_all_disposable_urls() -> None:
    result = _collect_integration(include_urls=False)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "CI integration mode requires disposable database URLs" in output
    assert all(name in output for name in INTEGRATION_URLS)


def test_ci_integration_mode_rejects_keyword_filtering() -> None:
    result = _collect_integration("-k", "readiness")

    assert result.returncode != 0
    assert "CI integration mode forbids '-k' test filtering" in result.stdout + result.stderr


def test_ci_integration_mode_rejects_incomplete_test_selection() -> None:
    result = _collect_integration(
        "--deselect=tests/integration/test_seed.py::test_seed_refuses_production_before_database_access"
    )

    assert result.returncode != 0
    assert (
        "CI integration collection must select exactly 26 approved tests; selected 25"
        in result.stdout + result.stderr
    )


def test_ci_integration_mode_collects_all_approved_tests() -> None:
    result = _collect_integration("-q")

    assert result.returncode == 0, result.stdout + result.stderr
    node_ids = [line for line in result.stdout.splitlines() if "::test_" in line]
    assert len(node_ids) == APPROVED_INTEGRATION_TEST_COUNT


def test_local_integration_collection_is_safe_without_urls() -> None:
    result = _collect_integration(include_urls=False, require_ci_mode=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CI integration mode requires" not in result.stdout + result.stderr
