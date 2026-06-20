"""CLI entry point for the warntrace command."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import IO, Any

from warntrace._bootstrap import make_bootstrap_script
from warntrace.renderer import Renderer, supports_color

_EXIT_SUCCESS = 0
_EXIT_USAGE = 2
_EXIT_POLICY = 3

_FAIL_ON_LEVELS: dict[str, frozenset[str]] = {
    "none": frozenset(),
    "application": frozenset({"application"}),
    "direct": frozenset({"application", "direct_dependency"}),
    "all": frozenset(
        {
            "application",
            "direct_dependency",
            "transitive_dependency",
            "standard_library",
            "unknown",
        }
    ),
}
_FAIL_ON_INDIVIDUAL_ORIGINS: frozenset[str] = frozenset(
    {
        "application",
        "direct_dependency",
        "transitive_dependency",
        "standard_library",
        "unknown",
    }
)
_FAIL_ON_LEVEL_NAMES: frozenset[str] = frozenset(_FAIL_ON_LEVELS)


def _get_version() -> str:
    try:
        return _pkg_version("warntrace")
    except Exception:
        return "0.1.0"


def _warntrace_install_dir() -> str:
    import warntrace as _wt  # noqa: PLC0415

    return str(Path(_wt.__file__).resolve().parent.parent)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warntrace",
        description="Find which package caused a Python warning and where your code triggered it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Show version and exit")

    run = sub.add_parser("run", help="Run a command with warning capture")
    run.add_argument(
        "--root",
        type=str,
        default=None,
        help="Application root directory (default: child's CWD)",
    )
    run.add_argument(
        "--format",
        choices=["json", "detailed", "summary"],
        default="json",
        help="Output format: json, detailed, or summary (default: json)",
    )
    run.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write report to FILE instead of stdout",
    )
    run.add_argument(
        "--show-all",
        action="store_true",
        help="Capture warnings that would normally be suppressed",
    )
    run.add_argument(
        "--no-passthrough",
        action="store_true",
        help="Suppress original warning output from child process",
    )
    run.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output",
    )
    run.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Limit stack frames per warning in output (Phase 8)",
    )
    run.add_argument(
        "--fail-on",
        type=str,
        nargs="+",
        default=None,
        choices=list(_FAIL_ON_LEVEL_NAMES | _FAIL_ON_INDIVIDUAL_ORIGINS),
        metavar="POLICY",
        help="Exit with code 3 on matched warnings. "
        "Levels: none, application, direct, all. "
        "Or specify individual origins: "
        "direct_dependency, transitive_dependency, standard_library, unknown",
    )
    run.add_argument(
        "cmd_args",
        nargs=argparse.REMAINDER,
        help="Command to run (use -- to separate warntrace args from command args)",
    )
    return parser


def handle_run(args: argparse.Namespace) -> int:
    command = args.cmd_args or []
    if command and command[0] == "--":
        command = command[1:]

    if not command:
        print("warntrace: missing command after 'run'", file=sys.stderr)
        print("usage: warntrace run [options] -- <command> [args...]", file=sys.stderr)
        return _EXIT_USAGE

    with tempfile.TemporaryDirectory(prefix="warntrace_") as tmpdir:
        bootstrap_path = Path(tmpdir) / "sitecustomize.py"
        bootstrap_path.write_text(make_bootstrap_script())

        report_path = Path(tmpdir) / "report.json"

        env = _build_child_env(
            sitecustomize_dir=tmpdir,
            report_path=str(report_path),
            root=args.root,
            show_all=args.show_all,
            passthrough=not args.no_passthrough,
        )

        result = subprocess.run(command, env=env)

        if not report_path.exists():
            print(
                "warntrace: child process did not produce a report",
                file=sys.stderr,
            )
            return _EXIT_USAGE

        report_data: dict[str, Any] = json.loads(report_path.read_text())

        use_color = supports_color(no_color_flag=args.no_color)
        renderer = Renderer(color=use_color, max_frames=args.max_frames)

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if args.format == "json":
                output_path.write_text(json.dumps(report_data, indent=2) + "\n")
            else:
                no_color_renderer = Renderer(color=False, max_frames=args.max_frames)
                with open(output_path, "w") as f:
                    _render_report(no_color_renderer, args.format, report_data, f)
        else:
            _render_report(renderer, args.format, report_data, sys.stdout)

        child_exit = result.returncode
        if args.fail_on and child_exit == 0:
            try:
                matched = _check_fail_on_policy(report_data, args.fail_on)
            except ValueError as exc:
                print(f"warntrace: {exc}", file=sys.stderr)
                return _EXIT_USAGE
            if matched:
                n = len(matched)
                print(
                    f"warntrace: --fail-on policy matched {n} warning(s)",
                    file=sys.stderr,
                )
                return _EXIT_POLICY

        return child_exit


def _check_fail_on_policy(
    report_data: dict[str, Any],
    policies: list[str],
) -> list[dict[str, Any]]:
    policies_set = set(policies)
    has_level = bool(policies_set & _FAIL_ON_LEVEL_NAMES)
    has_origin = bool(policies_set & _FAIL_ON_INDIVIDUAL_ORIGINS - _FAIL_ON_LEVEL_NAMES)

    origins: frozenset[str] = frozenset()
    check_triggered: bool = False

    if has_level:
        if has_origin:
            level_names = ", ".join(sorted(policies_set & _FAIL_ON_LEVEL_NAMES))
            origin_names = ", ".join(
                sorted(policies_set & _FAIL_ON_INDIVIDUAL_ORIGINS - _FAIL_ON_LEVEL_NAMES)
            )
            raise ValueError(
                f"Cannot mix policy levels ({level_names}) with individual origins ({origin_names})"
            )
        if "none" in policies_set:
            return []
        for level in policies_set:
            origins |= _FAIL_ON_LEVELS.get(level, frozenset())
        check_triggered = "application" in policies_set
    else:
        origins = frozenset(p or "unknown" for p in policies)

    matched: list[dict[str, Any]] = []
    for warning in report_data.get("warnings", []):
        origin = warning.get("origin")
        if (
            origin in origins
            or check_triggered
            and warning.get("triggered_directly_by_application", False)
        ):
            matched.append(warning)
    return matched


def _render_report(
    renderer: Renderer,
    fmt: str,
    report_data: dict[str, Any],
    out: IO[str],
) -> None:
    if fmt == "detailed":
        renderer.render_detailed(report_data, out)
    elif fmt == "summary":
        renderer.render_summary(report_data, out)
    else:
        renderer.render_json(report_data, out)


def _build_child_env(
    sitecustomize_dir: str,
    report_path: str,
    root: str | None,
    show_all: bool,
    passthrough: bool,
) -> dict[str, str]:
    env = os.environ.copy()

    env["WARNTRACE_REPORT_PATH"] = report_path
    if root:
        env["WARNTRACE_ROOT"] = root
    env["WARNTRACE_SHOW_ALL"] = "1" if show_all else "0"
    env["WARNTRACE_PASSTHROUGH"] = "1" if passthrough else "0"

    warntrace_dir = _warntrace_install_dir()
    existing_pythonpath = env.get("PYTHONPATH", "")
    new_pythonpath_parts = [sitecustomize_dir, warntrace_dir]
    if existing_pythonpath:
        new_pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(new_pythonpath_parts)

    return env


def handle_version() -> int:
    print(f"warntrace {_get_version()}")
    return _EXIT_SUCCESS


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "version":
        sys.exit(handle_version())

    if args.command == "run":
        sys.exit(handle_run(args))
