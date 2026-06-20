"""Tests for utility functions."""

import traceback

from warntrace.models import FrameInfo
from warntrace.utils import (
    clean_stack,
    frame_to_frame_info,
    is_internal_warnings_frame,
    is_warntrace_frame,
    normalize_message,
    warning_fingerprint,
)


class TestInternalFrameDetection:
    def test_is_warntrace_frame_returns_true_for_own_file(self) -> None:
        """The utils module itself is inside warntrace, so its own path should match."""
        import warntrace.utils

        result = is_warntrace_frame(warntrace.utils.__file__)
        assert result is True

    def test_is_warntrace_frame_returns_false_for_other(self) -> None:
        assert is_warntrace_frame("/some/other/path.py") is False

    def test_is_warntrace_frame_returns_false_for_empty(self) -> None:
        assert is_warntrace_frame("") is False

    def test_is_internal_warnings_frame(self) -> None:
        assert is_internal_warnings_frame("/usr/lib/python3.12/warnings.py") is True
        assert is_internal_warnings_frame("/usr/lib/python3.12/other.py") is False
        assert is_internal_warnings_frame("") is False


class TestCleanStack:
    def test_empty_stack_returns_empty(self) -> None:
        assert clean_stack([]) == []

    def test_removes_warnings_frames_from_end(self) -> None:
        """traceback.extract_stack() puts innermost frames last.
        Internal frames at the end should be removed."""
        frames = [
            ("/app/main.py", 10, "main", "run()"),
            ("/usr/lib/python3.12/warnings.py", 112, "_showwarnmsg", "sw()"),
        ]
        result = clean_stack(frames)
        assert len(result) == 1
        assert result[0][0] == "/app/main.py"

    def test_keeps_at_least_one_frame(self) -> None:
        """If the entire stack is internal, keep at least one frame."""
        frames = [
            ("/src/warntrace/capture.py", 50, "custom_showwarning", "capture()"),
            ("/usr/lib/python3.12/warnings.py", 112, "_showwarnmsg", "sw()"),
        ]
        result = clean_stack(frames)
        assert len(result) >= 1

    def test_no_internal_frames_unchanged(self) -> None:
        frames = [
            ("/app/main.py", 10, "main", "run()"),
            ("/app/helper.py", 20, "helper", "do()"),
        ]
        result = clean_stack(frames)
        assert len(result) == 2

    def test_handles_framesummary_objects(self) -> None:
        """Test with real traceback.FrameSummary objects."""
        try:
            import warnings

            def inner():
                warnings.warn("test", DeprecationWarning, stacklevel=2)

            def outer():
                inner()

            outer()
        except Exception:
            pass

        stack = traceback.extract_stack()
        # Should not crash
        result = clean_stack(stack)
        assert isinstance(result, list)


class TestNormalizeMessage:
    def test_collapses_whitespace(self) -> None:
        assert normalize_message("hello   world") == "hello world"

    def test_strips_leading_trailing(self) -> None:
        assert normalize_message("  hello world  ") == "hello world"

    def test_empty_string(self) -> None:
        assert normalize_message("") == ""

    def test_preserves_semantic_content(self) -> None:
        """Numbers and paths should NOT be stripped."""
        msg = "deprecated in /usr/lib/lib.so, use /new/path instead (v2.0)"
        result = normalize_message(msg)
        assert "/usr/lib/lib.so" in result
        assert "/new/path" in result
        assert "v2.0" in result


class TestWarningFingerprint:
    def test_without_app_frame(self) -> None:
        fp = warning_fingerprint("DeprecationWarning", "msg", "a.py", 10)
        assert fp == ("DeprecationWarning", "msg", "a.py", 10)

    def test_with_app_frame(self) -> None:
        app = FrameInfo(filename="/app/main.py", lineno=42, function="run")
        fp = warning_fingerprint("DeprecationWarning", "msg", "a.py", 10, app)
        assert fp == ("DeprecationWarning", "msg", "a.py", 10, "/app/main.py", 42)

    def test_stable_same_inputs(self) -> None:
        fp1 = warning_fingerprint("DeprecationWarning", "hello world", "a.py", 5)
        fp2 = warning_fingerprint("DeprecationWarning", "hello world", "a.py", 5)
        assert fp1 == fp2

    def test_different_category_different_fingerprint(self) -> None:
        fp1 = warning_fingerprint("DeprecationWarning", "msg", "a.py", 1)
        fp2 = warning_fingerprint("UserWarning", "msg", "a.py", 1)
        assert fp1 != fp2


class TestFrameToFrameInfo:
    def test_with_tuple(self) -> None:
        result = frame_to_frame_info(("/app/main.py", 42, "run", "call()"))
        assert isinstance(result, FrameInfo)
        assert result.filename == "/app/main.py"
        assert result.lineno == 42
        assert result.function == "run"
        assert result.source_line == "call()"

    def test_without_source_line(self) -> None:
        result = frame_to_frame_info(("/app/main.py", 42, "run", None))
        assert result.source_line is None

    def test_with_distribution(self) -> None:
        dist = __import__("warntrace.models", fromlist=["DistributionInfo"]).DistributionInfo(
            name="dep", normalized_name="dep", version="1.0"
        )
        result = frame_to_frame_info(("/dep.py", 1, "helper"), distribution=dist)
        assert result.distribution is not None
        assert result.distribution.name == "dep"
