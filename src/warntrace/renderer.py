"""Terminal and JSON rendering for warning reports."""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import IO, Any

from warntrace.models import WarningOrigin


class _Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    BOLD_RED = "\033[1;31m"
    BOLD_YELLOW = "\033[1;33m"


_ORIGIN_STYLES: dict[str, tuple[str, str]] = {
    WarningOrigin.APPLICATION.value: ("app", _Style.BOLD_RED),
    WarningOrigin.DIRECT_DEPENDENCY.value: ("dir", _Style.BOLD_YELLOW),
    WarningOrigin.TRANSITIVE_DEPENDENCY.value: ("trans", _Style.CYAN),
    WarningOrigin.STANDARD_LIBRARY.value: ("std", _Style.BLUE),
    WarningOrigin.UNKNOWN.value: ("?", _Style.DIM),
}

_ORIGIN_SORT_ORDER: dict[str, int] = {
    WarningOrigin.APPLICATION.value: 0,
    WarningOrigin.DIRECT_DEPENDENCY.value: 1,
    WarningOrigin.TRANSITIVE_DEPENDENCY.value: 2,
    WarningOrigin.STANDARD_LIBRARY.value: 3,
    WarningOrigin.UNKNOWN.value: 4,
}

_SUMMARY_BADGE_WIDTH = 5
_SUMMARY_CATEGORY_WIDTH = 22
_SUMMARY_MESSAGE_WIDTH = 30
_SUMMARY_COUNT_WIDTH = 4
_WRAP_WIDTH = 78

# Unicode characters for terminal output (assigned to variables for
# Python 3.10/3.11 compatibility — f-strings cannot contain backslash
# escapes before Python 3.12).
_EM_DASH = "\u2014"
_BULLET = "\u2026"
_ARROW = "\u2192"
_HLINE = "\u2500"


def supports_color(*, no_color_flag: bool = False) -> bool:
    if no_color_flag:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _shorten_path(path_str: str) -> str:
    if not path_str:
        return ""
    p = Path(path_str).resolve()
    try:
        rel = p.relative_to(Path.cwd().resolve())
        return str(rel)
    except ValueError:
        pass
    home = Path.home().resolve()
    try:
        rel = p.relative_to(home)
        return f"~/{rel}"
    except ValueError:
        pass
    return str(p)


def _wrap_message(msg: str, width: int = _WRAP_WIDTH) -> str:
    return textwrap.fill(msg, width=width)


def _truncate(msg: str, width: int) -> str:
    if len(msg) <= width:
        return msg
    return msg[: width - 1] + _BULLET


def _sort_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(w: dict[str, Any]) -> tuple[Any, ...]:
        origin_rank = _ORIGIN_SORT_ORDER.get(w.get("origin", "unknown"), 99)
        occurrences = -w.get("occurrences", 0)
        category = w.get("category", "")
        message = w.get("message", "")
        return (origin_rank, occurrences, category, message)

    return sorted(warnings, key=key)


def _colorize(text: str, code: str, color: bool) -> str:
    if not color:
        return text
    return f"{code}{text}{_Style.RESET}"


def _format_location(filename: str, lineno: int) -> str:
    short = _shorten_path(filename)
    return f"{short}:{lineno}" if lineno else short


def _summary_line(report_data: dict[str, Any]) -> str:
    summary = report_data.get("summary", {})
    unique = summary.get("unique_warnings", 0)
    total = summary.get("total_occurrences", 0)
    u_str = f"{unique} unique warning" + ("s" if unique != 1 else "")
    t_str = f"{total} total occurrence" + ("s" if total != 1 else "")
    return f"{u_str}, {t_str}"


class Renderer:
    def __init__(
        self,
        *,
        color: bool = True,
        max_frames: int | None = None,
    ) -> None:
        self._color = color
        self._max_frames = max_frames

    def render_json(self, report_data: dict[str, Any], out: IO[str]) -> None:
        json.dump(report_data, out, indent=2)
        out.write("\n")

    def render_detailed(self, report_data: dict[str, Any], out: IO[str]) -> None:
        warnings_list = _sort_warnings(report_data.get("warnings", []))
        total = len(warnings_list)

        line = f"warntrace report {_EM_DASH} {_summary_line(report_data)}"
        header = _colorize(line, _Style.BOLD, self._color)
        out.write(header + "\n\n")

        for i, w in enumerate(warnings_list, 1):
            self._write_detailed_warning(w, i, total, out)
            if i < total:
                out.write("\n")

    def render_summary(self, report_data: dict[str, Any], out: IO[str]) -> None:
        warnings_list = _sort_warnings(report_data.get("warnings", []))
        total = len(warnings_list)

        line = f"warntrace report {_EM_DASH} {_summary_line(report_data)}"
        header = _colorize(line, _Style.BOLD, self._color)
        out.write(header + "\n\n")

        for w in warnings_list:
            self._write_summary_line(w, out)

        if total > 0:
            self._write_summary_divider(out)
            self._write_summary_footer(report_data, out)

    def _write_detailed_warning(
        self,
        w: dict[str, Any],
        index: int,
        total: int,
        out: IO[str],
    ) -> None:
        badge_label, badge_code = _ORIGIN_STYLES.get(w.get("origin", "unknown"), ("?", _Style.DIM))
        origin_display = _colorize(badge_label, badge_code, self._color)

        sep = f"{_HLINE * 3} Warning {index} of {total} {_HLINE}"
        sep += _HLINE * max(40, 78 - len(sep))
        out.write(_colorize(sep + "\n", _Style.BOLD, self._color))

        out.write(f"  Origin:        {origin_display}  {w.get('origin', '?')}")
        if w.get("triggered_directly_by_application"):
            out.write(_colorize(" (triggered by your code)", _Style.BOLD, self._color))
        out.write("\n")

        out.write(f"  Category:      {w.get('category', '?')}\n")

        message = w.get("message", "")
        wrapped = _wrap_message(message)
        for line in wrapped.split("\n"):
            out.write(f"  Message:       {line}\n")

        emitted = w.get("emitted_from", {})
        loc = _format_location(emitted.get("filename", ""), emitted.get("lineno", 0))
        if loc:
            out.write(f"  Location:      {loc}\n")

        out.write(f"  Occurrences:   {w.get('occurrences', 1)}\n")

        app_frame = w.get("application_frame")
        if app_frame:
            fn = _shorten_path(app_frame.get("filename", ""))
            func = app_frame.get("function", "")
            line_no = app_frame.get("lineno", 0)
            called = f"{fn}:{line_no}"
            if func:
                called += f" in {func}()"
            out.write(f"  Called from:   {called}\n")

        dep_path = w.get("dependency_path", [])
        if dep_path:
            names = [d.get("name", "?") for d in dep_path]
            dep_str = f"  Dependency:    {_ARROW.join(names)}"
            out.write(dep_str + "\n")

        dist = emitted.get("distribution") if emitted else None
        if dist:
            pkg = f"  Package:       {dist.get('name', '?')}"
            ver = dist.get("version", "") or ""
            out.write(f"{pkg} {ver}\n")

        stack = w.get("stack", [])
        if stack:
            out.write("  Stack:\n")
            frames_shown = stack[: self._max_frames] if self._max_frames else stack
            for j, frame in enumerate(frames_shown, 1):
                fn = _shorten_path(frame.get("filename", ""))
                func = frame.get("function", "?")
                line_no = frame.get("lineno", 0)
                out.write(f"    {j:2d}  {fn}:{line_no}  {func}()\n")
            if self._max_frames and len(stack) > self._max_frames:
                remaining = len(stack) - self._max_frames
                out.write(f"    {_BULLET} and {remaining} more frames\n")

    def _write_summary_line(self, w: dict[str, Any], out: IO[str]) -> None:
        badge_label, badge_code = _ORIGIN_STYLES.get(w.get("origin", "unknown"), ("?", _Style.DIM))
        badge = _colorize(f" {badge_label} ", badge_code, self._color)
        category = _truncate(w.get("category", ""), _SUMMARY_CATEGORY_WIDTH)
        message = _truncate(w.get("message", ""), _SUMMARY_MESSAGE_WIDTH)
        count = str(w.get("occurrences", 1))
        count_padded = count.rjust(_SUMMARY_COUNT_WIDTH)

        app_frame = w.get("application_frame")
        if app_frame:
            loc = _shorten_path(app_frame.get("filename", ""))
            func = app_frame.get("function", "")
            if func:
                loc += f":{app_frame.get('lineno', 0)}"
        else:
            emitted = w.get("emitted_from", {})
            loc = _shorten_path(emitted.get("filename", ""))

        line = (
            f"{badge}  "
            f"{category:<{_SUMMARY_CATEGORY_WIDTH}}  "
            f"{message:<{_SUMMARY_MESSAGE_WIDTH}}  "
            f"{count_padded}  {loc}"
        )
        out.write(line + "\n")

    def _write_summary_divider(self, out: IO[str]) -> None:
        out.write(_HLINE * 78 + "\n")

    def _write_summary_footer(self, report_data: dict[str, Any], out: IO[str]) -> None:
        summary = report_data.get("summary", {})
        unique = summary.get("unique_warnings", 0)
        total = summary.get("total_occurrences", 0)
        u_str = f"{unique} unique warning" + ("s" if unique != 1 else "")
        t_str = f"{total} total occurrence" + ("s" if total != 1 else "")
        out.write(f"  Summary: {u_str}, {t_str}\n")
