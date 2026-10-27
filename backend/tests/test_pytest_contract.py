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
    environment = os.environ.copy()
    for name in INTEGRATION_URLS:
        environment.pop(name, None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--config-file",
            str(PYPROJECT_PATH),
            "--collect-only",
            "-m",
            "integration",
            "--require-integration-env",
            "tests/integration",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "CI integration mode requires disposable database URLs" in output
    assert all(name in output for name in INTEGRATION_URLS)
