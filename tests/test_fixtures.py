"""Integration tests for fixture packages (transitive dependency classification).

Requires fixture packages to be installed in the test environment:

    uv pip install tests/fixtures/transitive_dependency
    uv pip install tests/fixtures/direct_dependency
    uv pip install tests/fixtures/sample_app

Do NOT use ``-e`` (editable) — editable installs hide source files from
``importlib.metadata``, breaking the distribution index lookup.
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
    reason="Fixture packages not available (run uv pip install tests/fixtures/*)",
)


def _run_script(script: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a script file via subprocess, passing sample_app dir as CWD."""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd or SAMPLE_APP_DIR,
        capture_output=True,
        text=True,
    )


def test_direct_dependency_origin() -> None:
    """A direct dependency warning is classified as DIRECT_DEPENDENCY."""
    result = _run_script(
        "import json; from warntrace import WarningTracer; "
        "from direct_dependency import direct_warning; "
        "t = WarningTracer(); t.start(); direct_warning(); r = t.stop(); "
        "data = json.loads(json.dumps(r.to_dict())); "
        "print(data['warnings'][0]['origin'])"
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "direct_dependency" in result.stdout


def test_transitive_dependency_origin() -> None:
    """A transitive dependency warning is classified as TRANSITIVE_DEPENDENCY."""
    result = _run_script(
        "from warntrace import WarningTracer; "
        "from sample_app import run; "
        "t = WarningTracer(); t.start(); run(); r = t.stop(); "
        "origins = [w.origin for w in r.warnings]; "
        "print(','.join(sorted(o.value for o in origins)))"
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "direct_dependency" in result.stdout
    assert "transitive_dependency" in result.stdout


def test_dependency_path_attached() -> None:
    """Dependency warnings have a dependency_path in JSON output."""
    result = _run_script(
        "import json; from warntrace import WarningTracer; "
        "from direct_dependency import direct_warning; "
        "from transitive_dependency import transitive_warning; "
        "t = WarningTracer(); t.start(); "
        "direct_warning(); transitive_warning(); r = t.stop(); "
        "data = json.loads(json.dumps(r.to_dict())); "
        "paths = [w.get('dependency_path', []) for w in data['warnings'] "
        "         if w['origin'] in ('direct_dependency', 'transitive_dependency')]; "
        "print(all(len(p) > 0 for p in paths))"
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "True" in result.stdout


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
