"""Tests for the terminal and JSON renderer."""

from __future__ import annotations

import json
from io import StringIO

from warntrace.renderer import (
    Renderer,
    _shorten_path,
    _sort_warnings,
    _truncate,
    _wrap_message,
    supports_color,
)


def _sample_report(**overrides: dict) -> dict:
    report = {
        "schema_version": "0.1",
        "summary": {
            "unique_warnings": 2,
            "total_occurrences": 5,
            "application": 1,
            "direct_dependency": 1,
            "transitive_dependency": 0,
            "standard_library": 0,
            "unknown": 0,
        },
        "warnings": [
            {
                "category": "DeprecationWarning",
                "message": "This is a test warning message",
                "origin": "application",
                "triggered_directly_by_application": False,
                "occurrences": 3,
                "emitted_from": {
                    "filename": "/home/user/project/src/app.py",
                    "lineno": 42,
                    "distribution": None,
                },
                "application_frame": {
                    "filename": "/home/user/project/src/app.py",
                    "lineno": 42,
                    "function": "main",
                    "source_line": '    warnings.warn("test")',
                    "module_name": "app",
                    "distribution": None,
                },
                "dependency_path": [],
                "stack": [
                    {
                        "filename": "/home/user/project/src/app.py",
                        "lineno": 42,
                        "function": "main",
                        "source_line": '    warnings.warn("test")',
                        "module_name": "app",
                        "distribution": None,
                    },
                    {
                        "filename": "/home/user/project/src/helper.py",
                        "lineno": 15,
                        "function": "do_thing",
                        "source_line": "    app()",
                        "module_name": "helper",
                        "distribution": None,
                    },
                ],
            },
            {
                "category": "UserWarning",
                "message": "A dependency warning",
                "origin": "direct_dependency",
                "triggered_directly_by_application": True,
                "occurrences": 2,
                "emitted_from": {
                    "filename": "/home/user/project/.venv/lib/site-packages/requests/api.py",
                    "lineno": 88,
                    "distribution": {
                        "name": "requests",
                        "normalized_name": "requests",
                        "version": "2.31.0",
                    },
                },
                "application_frame": {
                    "filename": "/home/user/project/src/app.py",
                    "lineno": 55,
                    "function": "fetch_data",
                    "source_line": "    requests.get('http://example.com')",
                    "module_name": "app",
                    "distribution": None,
                },
                "dependency_path": [
                    {"name": "myapp", "normalized_name": "myapp", "version": "0.1.0"},
                    {"name": "requests", "normalized_name": "requests", "version": "2.31.0"},
                ],
                "stack": [
                    {
                        "filename": "/home/user/project/.venv/lib/site-packages/requests/api.py",
                        "lineno": 88,
                        "function": "get",
                        "source_line": "    return request('get', url)",
                        "module_name": "requests.api",
                        "distribution": {
                            "name": "requests",
                            "normalized_name": "requests",
                            "version": "2.31.0",
                        },
                    },
                    {
                        "filename": "/home/user/project/src/app.py",
                        "lineno": 55,
                        "function": "fetch_data",
                        "source_line": "    requests.get('http://example.com')",
                        "module_name": "app",
                        "distribution": None,
                    },
                ],
            },
        ],
    }
    report.update(overrides)
    return report


class TestSortWarnings:
    def test_sort_application_before_direct_dep(self):
        warnings = _sample_report()["warnings"]
        sorted_w = _sort_warnings(warnings)
        assert sorted_w[0]["origin"] == "application"
        assert sorted_w[1]["origin"] == "direct_dependency"

    def test_sort_higher_count_first(self):
        warnings = [
            {"category": "A", "message": "x", "origin": "application", "occurrences": 1},
            {"category": "A", "message": "y", "origin": "application", "occurrences": 5},
        ]
        sorted_w = _sort_warnings(warnings)
        assert sorted_w[0]["occurrences"] == 5
        assert sorted_w[1]["occurrences"] == 1

    def test_sort_unknown_ranked_last(self):
        warnings = [
            {"category": "A", "message": "a", "origin": "unknown", "occurrences": 1},
            {"category": "A", "message": "b", "origin": "application", "occurrences": 1},
        ]
        sorted_w = _sort_warnings(warnings)
        assert sorted_w[0]["origin"] == "application"
        assert sorted_w[1]["origin"] == "unknown"


class TestShortenPath:
    def test_relative_to_cwd(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        src = project / "src"
        src.mkdir(parents=True)
        monkeypatch.chdir(str(project))
        result = _shorten_path(str(src / "app.py"))
        assert result == "src/app.py"

    def test_home_fallback(self, tmp_path):
        # Ensure path is not under CWD then falls to home
        outside = tmp_path / "outside" / "file.py"
        outside.parent.mkdir(parents=True)
        result = _shorten_path(str(outside))
        assert "outside/file.py" in result

    def test_empty_path(self):
        assert _shorten_path("") == ""

    def test_absolute_path_outside(self, tmp_path):
        outside = tmp_path / "somewhere" / "app.py"
        outside.parent.mkdir(parents=True)
        result = _shorten_path(str(outside))
        # Should contain the path
        assert "app.py" in result


class TestWrapMessage:
    def test_wraps_long_message(self):
        msg = (
            "this is a very long message that should be wrapped to"
            " multiple lines at the configured width of 78 characters"
        )
        result = _wrap_message(msg, width=40)
        lines = result.split("\n")
        assert len(lines) >= 2
        for line in lines[:-1]:
            assert len(line) <= 40

    def test_short_message_unchanged(self):
        short = "short message"
        result = _wrap_message(short, width=78)
        assert result == short


class TestTruncate:
    def test_truncates_long(self):
        result = _truncate("hello world", width=8)
        assert len(result) == 8
        assert result.endswith("\u2026")

    def test_short_unchanged(self):
        result = _truncate("hello", width=10)
        assert result == "hello"


def _lines(output: str) -> list[str]:
    return output.rstrip("\n").split("\n")


class TestRenderJson:
    def test_valid_json(self):
        renderer = Renderer()
        out = StringIO()
        report = _sample_report()
        renderer.render_json(report, out)
        parsed = json.loads(out.getvalue())
        assert parsed["schema_version"] == "0.1"
        assert len(parsed["warnings"]) == 2

    def test_no_ansi_codes(self):
        renderer = Renderer(color=True)
        out = StringIO()
        renderer.render_json(_sample_report(), out)
        assert "\033[" not in out.getvalue()


class TestRenderDetailed:
    def test_contains_message(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        assert "This is a test warning message" in text
        assert "A dependency warning" in text

    def test_contains_origin_labels(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        assert "application" in text
        assert "direct_dependency" in text

    def test_contains_app_frame(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        assert "Called from:" in text
        assert "main()" in text
        assert "fetch_data()" in text

    def test_contains_stack_frames(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        assert "Stack:" in text
        assert "do_thing()" in text

    def test_max_frames_limits_stack(self):
        renderer = Renderer(color=False, max_frames=1)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        # With max_frames=1, each warning shows frame 1 but not frame 2
        # First warning has 2 frames, so we expect "... and 1 more frames"
        assert "and 1 more frames" in text
        # No frame 2 should appear in the stack listings
        assert "do_thing()" not in text

    def test_no_color_no_ansi(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        assert "\033[" not in out.getvalue()

    def test_color_enabled_has_ansi(self):
        renderer = Renderer(color=True)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        assert "\033[" in out.getvalue()

    def test_contains_triggered_by_your_code(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        assert "triggered by your code" in text

    def test_contains_dependency_path(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        assert "Dependency:" in text
        assert "myapp" in text or "requests" in text

    def test_contains_package_info(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(_sample_report(), out)
        text = out.getvalue()
        assert "requests" in text
        assert "2.31.0" in text


class TestRenderSummary:
    def test_contains_counts(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_summary(_sample_report(), out)
        text = out.getvalue()
        assert "2 unique warnings" in text
        assert "5 total occurrences" in text

    def test_one_line_per_warning(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_summary(_sample_report(), out)
        lines = _lines(out.getvalue())
        data_lines = [ln for ln in lines if ln.strip() and not ln.startswith("\u2500")]
        data_lines = [ln for ln in data_lines if not ln.startswith("warntrace")]
        data_lines = [ln for ln in data_lines if not ln.startswith("  Summary")]
        assert len(data_lines) == 2

    def test_no_ansi_when_color_disabled(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_summary(_sample_report(), out)
        assert "\033[" not in out.getvalue()

    def test_empty_report_shows_no_error(self):
        renderer = Renderer(color=False)
        out = StringIO()
        empty = {"summary": {"unique_warnings": 0, "total_occurrences": 0}, "warnings": []}
        renderer.render_summary(empty, out)
        text = out.getvalue()
        assert "0 unique warnings" in text


class TestSupportsColor:
    def test_no_color_flag_disables(self):
        assert supports_color(no_color_flag=True) is False

    def test_no_color_env_disables(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert supports_color(no_color_flag=False) is False

    def test_no_color_env_empty_still_disables(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "")
        assert supports_color(no_color_flag=False) is False


class TestRendererEdgeCases:
    def test_empty_warnings_list(self):
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(
            {"summary": {"unique_warnings": 0, "total_occurrences": 0}, "warnings": []},
            out,
        )
        assert "0 unique warnings" in out.getvalue()

    def test_missing_emitted_from(self):
        warning = {
            "category": "Warning",
            "message": "no location",
            "origin": "unknown",
            "occurrences": 1,
            "emitted_from": {"filename": "", "lineno": 0, "distribution": None},
            "stack": [],
        }
        report = {
            "summary": {"unique_warnings": 1, "total_occurrences": 1, "unknown": 1},
            "warnings": [warning],
        }
        renderer = Renderer(color=False)
        out = StringIO()
        renderer.render_detailed(report, out)
        assert "no location" in out.getvalue()
