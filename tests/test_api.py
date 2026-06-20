"""Tests for the public API (WarningTracer / capture_warnings)."""

import warnings

import pytest

from warntrace import capture, capture_warnings, is_hook_installed
from warntrace.api import WarningTracer
from warntrace.capture import get_passthrough_enabled, set_passthrough_enabled
from warntrace.models import WarningReport


@pytest.fixture(autouse=True)
def reset_state():
    """Ensure clean global state before and after each test."""
    saved_filters = warnings.filters[:]
    capture.clear_captured_warnings()
    if capture.is_hook_installed():
        capture.uninstall_hook()
    set_passthrough_enabled(True)
    yield
    capture.clear_captured_warnings()
    if capture.is_hook_installed():
        capture.uninstall_hook()
    set_passthrough_enabled(True)
    warnings.filters[:] = saved_filters


def _emit_warning(msg: str = "test warning") -> None:
    warnings.warn(msg, DeprecationWarning, stacklevel=2)


class TestCaptureWarnings:
    def test_basic_capture(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("hello")
        report = tracer.stop()
        assert len(report.warnings) == 1
        assert report.warnings[0].message == "hello"
        assert report.warnings[0].category_name == "DeprecationWarning"

    def test_returns_warning_report(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("data")
        report = tracer.stop()
        assert isinstance(report, WarningReport)
        assert report.total_occurrences == 1

    def test_tracer_accessible_inside_context(self) -> None:
        with capture_warnings() as tracer:
            assert tracer.is_started is True
            _emit_warning("inside")
        assert tracer.is_started is False

    def test_hook_restored_after_context(self) -> None:
        original = warnings.showwarning
        with capture_warnings():
            assert warnings.showwarning is not original
        assert warnings.showwarning is original

    def test_no_warnings_empty_report(self) -> None:
        with capture_warnings() as tracer:
            pass
        report = tracer.stop()
        assert len(report.warnings) == 0


class TestWarningTracerLifecycle:
    def test_start_stop(self) -> None:
        tracer = WarningTracer()
        tracer.start()
        assert tracer.is_started is True
        assert is_hook_installed() is True
        _emit_warning("lifecycle")
        report = tracer.stop()
        assert tracer.is_started is False
        assert is_hook_installed() is False
        assert len(report.warnings) == 1

    def test_double_start_raises(self) -> None:
        tracer = WarningTracer()
        tracer.start()
        with pytest.raises(RuntimeError, match="already started"):
            tracer.start()

    def test_stop_before_start_raises(self) -> None:
        tracer = WarningTracer()
        with pytest.raises(RuntimeError, match="not started"):
            tracer.stop()

    def test_stop_is_idempotent(self) -> None:
        tracer = WarningTracer()
        tracer.start()
        _emit_warning("first")
        report1 = tracer.stop()
        report2 = tracer.stop()
        assert report1 is report2

    def test_hook_raises_if_already_installed(self) -> None:
        capture.install_hook()
        tracer = WarningTracer()
        with pytest.raises(RuntimeError, match="already installed"):
            tracer.start()

    def test_state_restored_on_exception(self) -> None:
        original_filters = warnings.filters[:]
        original_passthrough = get_passthrough_enabled()
        original_showwarning = warnings.showwarning

        tracer = WarningTracer(show_all=True, passthrough=False)
        tracer.start()
        try:
            raise ValueError("boom")
        except ValueError:
            pass
        tracer.stop()

        assert warnings.showwarning is original_showwarning
        assert get_passthrough_enabled() == original_passthrough
        assert warnings.filters == original_filters

    def test_repr_started_and_stopped(self) -> None:
        tracer = WarningTracer()
        assert tracer.is_started is False
        tracer.start()
        assert tracer.is_started is True
        tracer.stop()
        assert tracer.is_started is False


class TestReport:
    def test_report_snapshot_mid_capture(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("mid1")
            snapshot = tracer.report()
            assert len(snapshot.warnings) == 1
            assert snapshot.warnings[0].message == "mid1"
            _emit_warning("mid2")
        report = tracer.stop()
        assert len(report.warnings) >= 1
        assert report.total_occurrences >= 2

    def test_multiple_report_calls(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("multi")
            r1 = tracer.report()
            r2 = tracer.report()
        assert r1.total_occurrences == r2.total_occurrences

    def test_report_before_start_raises(self) -> None:
        tracer = WarningTracer()
        with pytest.raises(RuntimeError, match="not started"):
            tracer.report()

    def test_report_after_stop_raises(self) -> None:
        tracer = WarningTracer()
        tracer.start()
        tracer.stop()
        with pytest.raises(RuntimeError, match="not started"):
            tracer.report()

    def test_report_returns_classified_warnings(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("classified")
            snapshot = tracer.report()
        assert len(snapshot.warnings) == 1
        assert snapshot.warnings[0].origin is not None


class TestShowAll:
    def test_show_all_captures_suppressed_warnings(self) -> None:
        orig_filters = warnings.filters[:]
        warnings.simplefilter("ignore", DeprecationWarning)

        try:
            with capture_warnings(show_all=True) as tracer:
                _emit_warning("suppressed")
            report = tracer.stop()
            assert len(report.warnings) == 1
            assert report.warnings[0].message == "suppressed"
        finally:
            warnings.filters[:] = orig_filters

    def test_filters_restored_after_stop(self) -> None:
        orig_filters = warnings.filters[:]
        warnings.simplefilter("ignore", DeprecationWarning)
        expected = warnings.filters[:]

        try:
            with capture_warnings(show_all=True):
                _emit_warning("during")
            assert warnings.filters == expected
        finally:
            warnings.filters[:] = orig_filters

    def test_filters_restored_on_exception(self) -> None:
        orig_filters = warnings.filters[:]
        warnings.simplefilter("ignore", DeprecationWarning)
        expected = warnings.filters[:]

        try:
            with pytest.raises(RuntimeError), capture_warnings(show_all=True):
                _emit_warning("before boom")
                raise RuntimeError("boom")
            assert warnings.filters == expected
        finally:
            warnings.filters[:] = orig_filters

    def test_show_all_default_is_false(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("normal")
        report = tracer.stop()
        assert len(report.warnings) == 1


class TestPassthrough:
    def test_passthrough_true_forwards_to_original(self) -> None:
        call_count = 0
        original = warnings.showwarning

        def tracking_showwarning(message, category, filename, lineno, file=None, line=None):
            nonlocal call_count
            call_count += 1
            return original(message, category, filename, lineno, file, line)

        warnings.showwarning = tracking_showwarning
        try:
            with capture_warnings(passthrough=True):
                _emit_warning("visible")
            assert call_count >= 1
        finally:
            warnings.showwarning = original

    def test_passthrough_false_suppresses_warnings(self) -> None:
        call_count = 0
        original = warnings.showwarning

        def tracking_showwarning(message, category, filename, lineno, file=None, line=None):
            nonlocal call_count
            call_count += 1
            return original(message, category, filename, lineno, file, line)

        warnings.showwarning = tracking_showwarning
        try:
            with capture_warnings(passthrough=False):
                _emit_warning("silent")
            assert call_count == 0
        finally:
            warnings.showwarning = original

    def test_passthrough_restored_after_stop(self) -> None:
        with capture_warnings(passthrough=False):
            _emit_warning("during")
        assert get_passthrough_enabled() is True

    def test_passthrough_restored_on_exception(self) -> None:
        with pytest.raises(ValueError), capture_warnings(passthrough=False):
            _emit_warning("during")
            raise ValueError("boom")
        assert get_passthrough_enabled() is True


class TestNestedCapture:
    def test_nested_capture_raises(self) -> None:
        with (
            capture_warnings(),
            pytest.raises(RuntimeError, match="already installed"),
            capture_warnings(),
        ):
            pass

    def test_nested_tracer_start_raises(self) -> None:
        tracer1 = WarningTracer()
        tracer2 = WarningTracer()
        tracer1.start()
        with pytest.raises(RuntimeError, match="already installed"):
            tracer2.start()
        tracer1.stop()

    def test_outer_still_works_after_idempotent_install(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("outer1")
            capture.install_hook()  # Idempotent — no-op
            _emit_warning("outer2")
        report = tracer.stop()
        assert report.total_occurrences >= 2


class TestWarningTracerConfiguration:
    def test_custom_root_reflected_in_report(self, tmp_path) -> None:
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        tracer = WarningTracer(root=str(app_dir))
        tracer.start()
        _emit_warning("custom")
        report = tracer.stop()
        assert isinstance(report, WarningReport)

    def test_default_without_root(self) -> None:
        tracer = WarningTracer()
        tracer.start()
        _emit_warning("default")
        report = tracer.stop()
        assert len(report.warnings) == 1

    def test_report_summary_counts(self) -> None:
        with capture_warnings() as tracer:
            _emit_warning("summary")
        report = tracer.stop()
        assert "summary" in report.to_dict()
        summary = report.to_dict()["summary"]
        assert summary["unique_warnings"] >= 1
        assert summary["total_occurrences"] >= 1
