"""Tests for the CLI (warntrace run / warntrace version)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from warntrace._bootstrap import make_bootstrap_script
from warntrace.cli import (
    _EXIT_POLICY,
    _EXIT_SUCCESS,
    _EXIT_USAGE,
    _build_child_env,
    _check_fail_on_policy,
    _get_version,
    _warntrace_install_dir,
    build_parser,
    handle_run,
)


@pytest.fixture
def parser():
    return build_parser()


class TestArgparse:
    def test_version_command(self, parser):
        args = parser.parse_args(["version"])
        assert args.command == "version"

    def test_run_command_basic(self, parser):
        args = parser.parse_args(["run", "python", "-c", "pass"])
        assert args.command == "run"
        assert args.cmd_args == ["python", "-c", "pass"]

    def test_run_with_double_dash(self, parser):
        args = parser.parse_args(["run", "--", "python", "-c", "pass"])
        assert args.command == "run"
        assert args.cmd_args == ["--", "python", "-c", "pass"]

    def test_run_with_flags(self, parser):
        args = parser.parse_args(["run", "--show-all", "--no-passthrough", "python", "-c", "pass"])
        assert args.show_all is True
        assert args.no_passthrough is True

    def test_run_with_root(self, parser):
        args = parser.parse_args(["run", "--root", "/tmp", "python", "-c", "pass"])
        assert args.root == "/tmp"

    def test_run_with_fail_on(self, parser):
        args = parser.parse_args(
            ["run", "--fail-on", "application", "unknown", "--", "python", "-c", "pass"]
        )
        assert args.fail_on == ["application", "unknown"]

    def test_run_with_format(self, parser):
        args = parser.parse_args(["run", "--format", "json", "python", "-c", "pass"])
        assert args.format == "json"

    def test_run_with_output(self, parser):
        args = parser.parse_args(["run", "--output", "/tmp/report.json", "python", "-c", "pass"])
        assert args.output == "/tmp/report.json"

    def test_run_with_max_frames(self, parser):
        args = parser.parse_args(["run", "--max-frames", "5", "python", "-c", "pass"])
        assert args.max_frames == 5

    def test_run_with_no_color(self, parser):
        args = parser.parse_args(["run", "--no-color", "python", "-c", "pass"])
        assert args.no_color is True

    def test_version_invalid_subcommand(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["invalid"])


class TestVersion:
    def test_version_string(self):
        version = _get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_handle_version(self):
        from warntrace.cli import handle_version

        assert handle_version() == _EXIT_SUCCESS


class TestBootstrapScript:
    def test_script_contains_key_patterns(self):
        script = make_bootstrap_script()
        assert "WARNTRACE_REPORT_PATH" in script
        assert "WARNTRACE_SHOW_ALL" in script
        assert "WARNTRACE_PASSTHROUGH" in script
        assert "install_hook" in script
        assert "atexit.register" in script
        assert "_finalize_warntrace" in script
        assert "os.replace" in script
        assert "report.to_dict()" in script
        assert "WarningClassifier" in script

    def test_script_is_valid_python(self):
        script = make_bootstrap_script()
        compile(script, "<bootstrap>", "exec")


class TestBuildChildEnv:
    def test_sets_report_path(self):
        env = _build_child_env(
            sitecustomize_dir="/tmp/wt",
            report_path="/tmp/wt/report.json",
            root=None,
            show_all=False,
            passthrough=True,
        )
        assert env["WARNTRACE_REPORT_PATH"] == "/tmp/wt/report.json"

    def test_sets_show_all_flag(self):
        env = _build_child_env(
            sitecustomize_dir="/tmp/wt",
            report_path="/tmp/wt/report.json",
            root=None,
            show_all=True,
            passthrough=True,
        )
        assert env["WARNTRACE_SHOW_ALL"] == "1"

        env2 = _build_child_env(
            sitecustomize_dir="/tmp/wt",
            report_path="/tmp/wt/report.json",
            root=None,
            show_all=False,
            passthrough=True,
        )
        assert env2["WARNTRACE_SHOW_ALL"] == "0"

    def test_sets_passthrough_flag(self):
        env = _build_child_env(
            sitecustomize_dir="/tmp/wt",
            report_path="/tmp/wt/report.json",
            root=None,
            show_all=False,
            passthrough=True,
        )
        assert env["WARNTRACE_PASSTHROUGH"] == "1"

        env2 = _build_child_env(
            sitecustomize_dir="/tmp/wt",
            report_path="/tmp/wt/report.json",
            root=None,
            show_all=False,
            passthrough=False,
        )
        assert env2["WARNTRACE_PASSTHROUGH"] == "0"

    def test_sets_root(self):
        env = _build_child_env(
            sitecustomize_dir="/tmp/wt",
            report_path="/tmp/wt/report.json",
            root="/my/app",
            show_all=False,
            passthrough=True,
        )
        assert env["WARNTRACE_ROOT"] == "/my/app"

    def test_pythonpath_includes_sitecustomize_and_warntrace(self):
        env = _build_child_env(
            sitecustomize_dir="/tmp/wt",
            report_path="/tmp/wt/report.json",
            root=None,
            show_all=False,
            passthrough=True,
        )
        parts = env["PYTHONPATH"].split(os.pathsep)
        assert "/tmp/wt" in parts
        assert _warntrace_install_dir() in parts

    def test_pythonpath_preserves_existing(self):
        old = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = "/existing/path"
        try:
            env = _build_child_env(
                sitecustomize_dir="/tmp/wt",
                report_path="/tmp/wt/report.json",
                root=None,
                show_all=False,
                passthrough=True,
            )
            assert "/existing/path" in env["PYTHONPATH"]
        finally:
            if old is not None:
                os.environ["PYTHONPATH"] = old
            else:
                del os.environ["PYTHONPATH"]


def _extract_json(stdout: str) -> str:
    """Find the JSON object in potentially mixed stdout."""
    idx = stdout.find("{")
    return stdout[idx:] if idx >= 0 else stdout


class TestRunBasic:
    def test_run_simple_warning_produces_json_report(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('hello cli', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(_extract_json(result.stdout))
        assert data["schema_version"] == "0.1"
        assert data["summary"]["unique_warnings"] >= 1
        assert data["warnings"][0]["message"] == "hello cli"

    def test_run_no_warnings_empty_report(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                sys.executable,
                "-c",
                "pass",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(_extract_json(result.stdout))
        assert data["summary"]["unique_warnings"] == 0

    def test_run_show_all_captures_suppressed(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--",
                sys.executable,
                "-W",
                "ignore::DeprecationWarning",
                "-c",
                "import warnings; warnings.warn('suppressed', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(_extract_json(result.stdout))
        assert data["summary"]["unique_warnings"] >= 1

    def test_run_no_passthrough_suppresses_child_output(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--no-passthrough",
                "--show-all",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('silent', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(_extract_json(result.stdout))
        assert data["summary"]["unique_warnings"] >= 1

    def test_run_captures_warning_when_showwarning_replaced(self):
        """Verify that warn wrapping captures warnings even when
        the child process replaces showwarning (like pytest does)."""
        script = (
            "import warnings\n"
            "original = warnings.showwarning\n"
            "warnings.showwarning = lambda *a, **kw: None\n"
            "warnings.warn('hidden', DeprecationWarning)\n"
            "warnings.showwarning = original\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--",
                sys.executable,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(_extract_json(result.stdout))
        assert data["summary"]["unique_warnings"] >= 1
        assert data["warnings"][0]["message"] == "hidden"

    def test_run_detailed_format_output(self):
        """Verify --format detailed produces human-readable output."""
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
                "-c",
                "import warnings; warnings.warn('detailed test', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "detailed test" in result.stdout
        assert "DeprecationWarning" in result.stdout
        assert "Location:" in result.stdout

    def test_run_summary_format_output(self):
        """Verify --format summary produces concise output."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--format",
                "summary",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('summary test', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "unique warning" in result.stdout
        assert "total occurrence" in result.stdout

    def test_run_output_file_detailed(self, tmp_path):
        """Verify --output works with terminal format (no ANSI in file)."""
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
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('file test', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out_file.exists()
        content = out_file.read_text()
        assert "file test" in content
        assert "\033[" not in content, "file output should not contain ANSI codes"

    def test_run_max_frames_limits_output(self):
        """Verify --max-frames limits stack trace length in detailed output."""
        script = (
            "import warnings\n"
            "import sys\n"
            "def level4():\n"
            "    warnings.warn('deep', DeprecationWarning, stacklevel=2)\n"
            "def level3():\n"
            "    level4()\n"
            "def level2():\n"
            "    level3()\n"
            "level2()\n"
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
                "1",
                "--show-all",
                "--",
                sys.executable,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "and 1 more frames" in result.stdout or "more frames" in result.stdout


class TestRunWithArgs:
    def test_command_with_args(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                sys.executable,
                "-c",
                "import sys; sys.exit(42)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 42

    def test_command_with_double_dash(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--",
                sys.executable,
                "-c",
                "print('double dash works')",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"


class TestExitCode:
    def test_child_exit_0(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                sys.executable,
                "-c",
                "pass",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_child_exit_1(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                sys.executable,
                "-c",
                "exit(1)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_child_exit_42(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                sys.executable,
                "-c",
                "exit(42)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 42


class TestFailOn:
    def test_fail_on_application_matches_exits_3(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "application",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('app warning', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == _EXIT_POLICY, f"stderr: {result.stderr}"
        assert "policy matched" in result.stderr

    def test_fail_on_no_match_exits_0(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "direct_dependency",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('app warning', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "policy matched" not in result.stderr

    def test_fail_on_direct_level_matches(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "direct",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('app warning', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == _EXIT_POLICY, f"stderr: {result.stderr}"
        assert "policy matched" in result.stderr

    def test_fail_on_all_level_matches(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "all",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('any warning', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == _EXIT_POLICY, f"stderr: {result.stderr}"
        assert "policy matched" in result.stderr

    def test_fail_on_none_never_fails(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "none",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('harmless', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "policy matched" not in result.stderr

    def test_child_failure_takes_priority(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "all",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('failing', DeprecationWarning); exit(42)",
            ],
            capture_output=True,
            text=True,
        )
        # Child exited 42, policy would match, but child takes priority
        assert result.returncode == 42, f"stderr: {result.stderr}"
        assert "policy matched" not in result.stderr

    def test_fail_on_mixed_level_and_origin_errors(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "application",
                "transitive_dependency",
                "--",
                sys.executable,
                "-c",
                "pass",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == _EXIT_USAGE, f"stderr: {result.stderr}"
        assert "Cannot mix" in result.stderr

    def test_fail_on_individual_origins_no_error(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "warntrace",
                "run",
                "--show-all",
                "--fail-on",
                "standard_library",
                "unknown",
                "--",
                sys.executable,
                "-c",
                "import warnings; warnings.warn('multi origin', DeprecationWarning)",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # No error about mixed usage; just no policy match (warning is 'application')


class TestHandleRun:
    def test_missing_command_returns_usage(self, parser):
        args = parser.parse_args(["run"])
        exit_code = handle_run(args)
        assert exit_code == _EXIT_USAGE

    def test_all_dash_command_stripped(self, parser):
        args = parser.parse_args(["run", "--"])
        exit_code = handle_run(args)
        assert exit_code == _EXIT_USAGE

    def test_format_detailed(self, parser):
        args = parser.parse_args(
            [
                "run",
                "--format",
                "detailed",
                sys.executable,
                "-c",
                "pass",
            ]
        )
        exit_code = handle_run(args)
        assert exit_code == 0

    def test_format_summary(self, parser):
        args = parser.parse_args(
            [
                "run",
                "--format",
                "summary",
                sys.executable,
                "-c",
                "pass",
            ]
        )
        exit_code = handle_run(args)
        assert exit_code == 0


class TestWarntraceInstallDir:
    def test_returns_existing_directory(self):
        install_dir = _warntrace_install_dir()
        path = Path(install_dir)
        assert path.is_dir()
        assert (path / "warntrace").is_dir()


class TestCheckFailOnPolicy:
    def test_application_level_matches_app_origin(self):
        report = {
            "warnings": [
                {"origin": "application", "triggered_directly_by_application": False},
            ]
        }
        matched = _check_fail_on_policy(report, ["application"])
        assert len(matched) == 1

    def test_application_level_matches_triggered_directly(self):
        report = {
            "warnings": [
                {"origin": "direct_dependency", "triggered_directly_by_application": True},
            ]
        }
        matched = _check_fail_on_policy(report, ["application"])
        assert len(matched) == 1

    def test_application_level_skips_untouched_dep(self):
        report = {
            "warnings": [
                {"origin": "direct_dependency", "triggered_directly_by_application": False},
            ]
        }
        matched = _check_fail_on_policy(report, ["application"])
        assert len(matched) == 0

    def test_direct_level_matches_app_and_direct(self):
        report = {
            "warnings": [
                {"origin": "application", "triggered_directly_by_application": False},
                {"origin": "direct_dependency", "triggered_directly_by_application": False},
            ]
        }
        matched = _check_fail_on_policy(report, ["direct"])
        assert len(matched) == 2

    def test_all_level_matches_any_origin(self):
        report = {
            "warnings": [
                {"origin": "application"},
                {"origin": "transitive_dependency"},
            ]
        }
        matched = _check_fail_on_policy(report, ["all"])
        assert len(matched) == 2

    def test_none_level_never_matches(self):
        report = {"warnings": [{"origin": "application"}]}
        matched = _check_fail_on_policy(report, ["none"])
        assert len(matched) == 0

    def test_individual_origins_match_directly(self):
        report = {
            "warnings": [
                {"origin": "direct_dependency", "triggered_directly_by_application": False},
                {"origin": "standard_library", "triggered_directly_by_application": False},
            ]
        }
        matched = _check_fail_on_policy(report, ["direct_dependency"])
        assert len(matched) == 1

    def test_mixed_level_and_origin_raises(self):
        report = {"warnings": [{"origin": "application"}]}
        with pytest.raises(ValueError, match="Cannot mix policy levels"):
            _check_fail_on_policy(report, ["application", "transitive_dependency"])
