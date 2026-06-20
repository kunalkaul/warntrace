"""Integration tests for fixture packages (transitive dependency classification).

Requires fixture packages to be installed in the test environment:

    pip install -e tests/fixtures/transitive_dependency
    pip install -e tests/fixtures/direct_dependency
    pip install -e tests/fixtures/sample_app
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_APP_DIR = FIXTURES_DIR / "sample_app"


def _fixtures_installed() -> bool:
    try:
        import direct_dependency  # noqa: F401
        import sample_app  # noqa: F401
        import transitive_dependency  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _fixtures_installed(),
    reason="Fixture packages not available (run pip install -e tests/fixtures/*)",
)


def test_direct_dependency_origin() -> None:
    """A direct dependency warning is classified as DIRECT_DEPENDENCY."""
    script = (
        "from warntrace import capture_warnings; "
        "from direct_dependency import direct_warning; "
        "with capture_warnings(): direct_warning(); "
        "r = __import__('warntrace').capture.get_aggregator().build_report(); "
        "for w in r.warnings: print(w.origin.value, w.category_name)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=SAMPLE_APP_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "direct_dependency" in result.stdout


def test_transitive_dependency_origin() -> None:
    """A transitive dependency warning is classified as TRANSITIVE_DEPENDENCY."""
    script = (
        "from warntrace import capture_warnings; "
        "from sample_app import run; "
        "with capture_warnings(): run(); "
        "r = __import__('warntrace').capture.get_aggregator().build_report(); "
        "for w in r.warnings: print(w.origin.value, w.category_name)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=SAMPLE_APP_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "direct_dependency" in result.stdout
    assert "transitive_dependency" in result.stdout


def test_dependency_path_attached() -> None:
    """Dependency warnings have a dependency_path in JSON output."""
    script = (
        "from warntrace import capture_warnings; "
        "from direct_dependency import direct_warning; "
        "from transitive_dependency import transitive_warning; "
        "with capture_warnings(): direct_warning(); transitive_warning(); "
        "r = __import__('warntrace').capture.get_aggregator().build_report(); "
        "print(r.to_json())"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=SAMPLE_APP_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    for w in data["warnings"]:
        path = w.get("dependency_path", [])
        if w["origin"] in ("direct_dependency", "transitive_dependency"):
            assert len(path) > 0, f"Missing dependency_path for {w['origin']}"


def test_cli_classifies_fixture_warnings() -> None:
    """warntrace run classifies fixture warnings by origin."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "warntrace",
            "run",
            sys.executable,
            "-c",
            "from sample_app import run; run()",
        ],
        cwd=SAMPLE_APP_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    origins = {w["origin"] for w in data.get("warnings", [])}
    assert "direct_dependency" in origins, f"Origins: {origins}"
    assert "transitive_dependency" in origins, f"Origins: {origins}"
