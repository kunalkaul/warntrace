"""Tests for pytest compatibility under ``warntrace run pytest``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _extract_json(stdout: str) -> str:
    """Find the JSON object in potentially mixed stdout."""
    idx = stdout.find("{")
    return stdout[idx:] if idx >= 0 else stdout


def _run_warntrace_pytest(
    test_file: Path,
    *extra_args: str,
    show_all: bool = False,
    no_passthrough: bool = False,
) -> subprocess.CompletedProcess:
    """Run ``warntrace run pytest`` on a test file and return the result."""
    cmd = [sys.executable, "-m", "warntrace", "run"]
    if show_all:
        cmd.append("--show-all")
    if no_passthrough:
        cmd.append("--no-passthrough")
    cmd.extend(extra_args)
    cmd.extend(["--", sys.executable, "-m", "pytest", str(test_file), "-q", "--no-header"])
    return subprocess.run(cmd, capture_output=True, text=True)


def _assert_warning_count(result: subprocess.CompletedProcess, expected: int) -> dict:
    """Assert the report contains exactly ``expected`` unique warnings."""
    data = json.loads(_extract_json(result.stdout))
    assert data["summary"]["unique_warnings"] == expected, (
        f"Expected {expected} warnings, got {data['summary']['unique_warnings']}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return data


class TestPytestBasicCapture:
    def test_captures_warning_from_pytest(self, tmp_path: Path):
        test_file = tmp_path / "test_simple.py"
        test_file.write_text(
            "import warnings\n"
            "def test_warn():\n"
            "    warnings.warn('pytest captured', UserWarning)\n"
            "    assert True\n"
        )
        result = _run_warntrace_pytest(test_file)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        _assert_warning_count(result, 1)

    def test_pytest_exit_code_preserved_on_success(self, tmp_path: Path):
        test_file = tmp_path / "test_pass.py"
        test_file.write_text("def test_ok():\n    assert True\n")
        result = _run_warntrace_pytest(test_file)
        assert result.returncode == 0

    def test_pytest_exit_code_preserved_on_failure(self, tmp_path: Path):
        test_file = tmp_path / "test_fail.py"
        test_file.write_text(
            "import warnings\n"
            "def test_fail():\n"
            "    warnings.warn('failing', UserWarning)\n"
            "    assert False\n"
        )
        result = _run_warntrace_pytest(test_file)
        assert result.returncode != 0
        # Still captured the warning even on failure
        _assert_warning_count(result, 1)

    def test_repeated_warnings_counted_correctly(self, tmp_path: Path):
        test_file = tmp_path / "test_repeated.py"
        test_file.write_text(
            "import warnings\n"
            "def test_repeated():\n"
            "    for _ in range(5):\n"
            "        warnings.warn('repeated', UserWarning)\n"
            "    assert True\n"
        )
        result = _run_warntrace_pytest(test_file)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(_extract_json(result.stdout))
        assert data["summary"]["unique_warnings"] == 1
        assert data["summary"]["total_occurrences"] == 5


class TestPytestNoPassthrough:
    def test_no_passthrough_suppresses_warning_display(self, tmp_path: Path):
        test_file = tmp_path / "test_silent.py"
        test_file.write_text(
            "import warnings\n"
            "def test_silent():\n"
            "    warnings.warn('silent', UserWarning)\n"
            "    assert True\n"
        )
        result = _run_warntrace_pytest(test_file, no_passthrough=True)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Warning should still be captured
        _assert_warning_count(result, 1)
        # Passthrough warnings should not appear in stderr
        assert "UserWarning" not in result.stderr

    def test_passthrough_location_is_correct(self, tmp_path: Path):
        test_file = tmp_path / "test_location.py"
        test_file.write_text(
            "import warnings\n"
            "def test_loc():\n"
            "    warnings.warn('loc check', UserWarning)\n"
            "    assert True\n"
        )
        result = _run_warntrace_pytest(test_file, show_all=True)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        _assert_warning_count(result, 1)
        # Passthrough location should point to the test file, not capture.py
        assert "capture.py" not in result.stdout

    def test_no_passthrough_still_captures_all(self, tmp_path: Path):
        test_file = tmp_path / "test_all_silent.py"
        test_file.write_text(
            "import warnings\n"
            "def test_multi():\n"
            "    warnings.warn('a', UserWarning)\n"
            "    warnings.warn('b', DeprecationWarning)\n"
            "    assert True\n"
        )
        result = _run_warntrace_pytest(test_file, no_passthrough=True, show_all=True)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        _assert_warning_count(result, 2)


class TestPytestWarningFilters:
    def test_W_flag_filterwarnings_error(self, tmp_path: Path):
        test_file = tmp_path / "test_werror.py"
        test_file.write_text(
            "import warnings\n"
            "def test_werror():\n"
            "    warnings.warn('should error', DeprecationWarning)\n"
            "    assert True\n"
        )
        cmd = [
            sys.executable,
            "-m",
            "warntrace",
            "run",
            "--",
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-q",
            "--no-header",
            "-W",
            "error::DeprecationWarning",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        # DeprecationWarning becomes error → test fails → non-zero exit
        assert result.returncode != 0
        # Warntrace still captured it
        _assert_warning_count(result, 1)

    def test_W_flag_filterwarnings_ignore(self, tmp_path: Path):
        test_file = tmp_path / "test_wignore.py"
        test_file.write_text(
            "import warnings\n"
            "def test_wignore():\n"
            "    warnings.warn('should be ignored', UserWarning)\n"
            "    assert True\n"
        )
        cmd = [
            sys.executable,
            "-m",
            "warntrace",
            "run",
            "--",
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-q",
            "--no-header",
            "-W",
            "ignore::UserWarning",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Warntrace captures before filters, so warning is still in report
        _assert_warning_count(result, 1)


class TestPytestShowAll:
    def test_show_all_captures_suppressed_types(self, tmp_path: Path):
        test_file = tmp_path / "test_suppressed.py"
        test_file.write_text(
            "import warnings\n"
            "def test_suppressed():\n"
            "    warnings.warn('bytes', BytesWarning)\n"
            "    warnings.warn('import', ImportWarning)\n"
            "    assert True\n"
        )
        # Without show-all
        result_no = _run_warntrace_pytest(test_file, show_all=False)
        assert result_no.returncode == 0, f"stderr: {result_no.stderr}"
        # Warn wrapper captures everything regardless of show-all
        _assert_warning_count(result_no, 2)

    def test_show_all_does_not_break_pytest(self, tmp_path: Path):
        test_file = tmp_path / "test_showall.py"
        test_file.write_text(
            "import warnings\n"
            "def test_normal():\n"
            "    warnings.warn('normal', UserWarning)\n"
            "    assert True\n"
        )
        result = _run_warntrace_pytest(test_file, show_all=True)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        _assert_warning_count(result, 1)


class TestPytestOutputFormat:
    def test_detailed_format_with_pytest(self, tmp_path: Path):
        test_file = tmp_path / "test_detailed.py"
        test_file.write_text(
            "import warnings\n"
            "def test_det():\n"
            "    warnings.warn('detailed', FutureWarning)\n"
            "    assert True\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--format",
                "detailed",
                "--",
                sys.executable,
                "-m",
                "pytest",
                str(test_file),
                "-q",
                "--no-header",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "detailed" in result.stdout
        assert "FutureWarning" in result.stdout

    def test_max_frames_limits_output_with_pytest(self, tmp_path: Path):
        test_file = tmp_path / "test_maxframes.py"
        test_file.write_text(
            "import warnings\n"
            "def test_mf():\n"
            "    warnings.warn('deep', UserWarning)\n"
            "    assert True\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--format",
                "detailed",
                "--max-frames",
                "3",
                "--",
                sys.executable,
                "-m",
                "pytest",
                str(test_file),
                "-q",
                "--no-header",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "more frames" in result.stdout

    def test_output_file_works_with_pytest(self, tmp_path: Path):
        test_file = tmp_path / "test_outputfile.py"
        test_file.write_text(
            "import warnings\n"
            "def test_of():\n"
            "    warnings.warn('file output', UserWarning)\n"
            "    assert True\n"
        )
        out_file = tmp_path / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--output",
                str(out_file),
                "--show-all",
                "--",
                sys.executable,
                "-m",
                "pytest",
                str(test_file),
                "-q",
                "--no-header",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["summary"]["unique_warnings"] == 1

    def test_output_file_detailed_no_ansi(self, tmp_path: Path):
        test_file = tmp_path / "test_noansi.py"
        test_file.write_text(
            "import warnings\n"
            "def test_na():\n"
            "    warnings.warn('no ansi in file', UserWarning)\n"
            "    assert True\n"
        )
        out_file = tmp_path / "report.txt"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--format",
                "detailed",
                "--output",
                str(out_file),
                "--show-all",
                "--",
                sys.executable,
                "-m",
                "pytest",
                str(test_file),
                "-q",
                "--no-header",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out_file.exists()
        content = out_file.read_text()
        assert "\033[" not in content, "file output should not contain ANSI codes"


class TestPytestFlags:
    @pytest.mark.skipif(
        os.name == "nt",
        reason="Path handling differs on Windows",
    )
    def test_pytest_x_stops_at_first_failure(self, tmp_path: Path):
        test_file = tmp_path / "test_xflag.py"
        test_file.write_text(
            "import warnings\n"
            "def test_first():\n"
            "    warnings.warn('first', UserWarning)\n"
            "    assert False\n"
            "def test_second():\n"
            "    warnings.warn('second', UserWarning)\n"
            "    assert True\n"
        )
        cmd = [
            sys.executable,
            "-m",
            "warntrace",
            "run",
            "--show-all",
            "--",
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-q",
            "--no-header",
            "-x",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0  # pytest -x failed
        # At least the first warning should be captured
        data = json.loads(_extract_json(result.stdout))
        assert data["summary"]["unique_warnings"] >= 1

    def test_pytest_k_filter_works(self, tmp_path: Path):
        test_file = tmp_path / "test_kflag.py"
        test_file.write_text(
            "import warnings\n"
            "def test_wanted():\n"
            "    warnings.warn('wanted', UserWarning)\n"
            "    assert True\n"
            "def test_other():\n"
            "    warnings.warn('other', UserWarning)\n"
            "    assert True\n"
        )
        cmd = [
            sys.executable,
            "-m",
            "warntrace",
            "run",
            "--show-all",
            "--",
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-q",
            "--no-header",
            "-k",
            "wanted",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        _assert_warning_count(result, 1)

    def test_pytest_ini_filterwarnings_respected(self, tmp_path: Path):
        pytest_ini = tmp_path / "pytest.ini"
        pytest_ini.write_text("[pytest]\nfilterwarnings = error::DeprecationWarning\n")
        test_file = tmp_path / "test_ini.py"
        test_file.write_text(
            "import warnings\n"
            "def test_dep():\n"
            "    warnings.warn('dep from ini', DeprecationWarning)\n"
            "    assert True\n"
            "def test_normal():\n"
            "    warnings.warn('normal', UserWarning)\n"
            "    assert True\n"
        )
        result = _run_warntrace_pytest(tmp_path, show_all=True)
        assert result.returncode != 0
        data = json.loads(_extract_json(result.stdout))
        # Both warnings captured (warn wrapper intercepts before filters)
        assert data["summary"]["unique_warnings"] == 2
        dep = [w for w in data["warnings"] if w["category"] == "DeprecationWarning"]
        assert len(dep) == 1
