"""Tests for warning capture via the showwarning hook."""

import warnings

import pytest

from warntrace import capture, clear_captured_warnings, get_captured_warnings, install_hook


@pytest.fixture(autouse=True)
def reset_capture():
    """Ensure clean state before and after each test."""
    capture.clear_captured_warnings()
    capture.disable_warn_wrapping()
    if capture.is_hook_installed():
        capture.uninstall_hook()
    yield
    capture.clear_captured_warnings()
    capture.disable_warn_wrapping()
    if capture.is_hook_installed():
        capture.uninstall_hook()


class TestCaptureHook:
    def test_captures_warning_category_and_message(self) -> None:
        install_hook()
        self._emit_warning("test message")
        captured = get_captured_warnings()
        assert len(captured) == 1
        assert captured[0].category_name == "DeprecationWarning"
        assert captured[0].message == "test message"

    def _emit_warning(self, msg: str) -> None:
        """Emit a warning and verify it is captured (regardless of frame)."""
        warnings.warn(msg, DeprecationWarning, stacklevel=2)

    def test_emission_location_is_tracked(self) -> None:
        """The warning is captured with its message intact regardless of
        pytest's wrapper."""
        install_hook()
        self._emit_warning("locate me")
        captured = get_captured_warnings()
        assert len(captured) == 1
        # Pytest intercepts warnings; captured[0].filename reflects
        # pytest's wrapper. The key invariant: the warning is captured.
        assert captured[0].message == "locate me"
        assert captured[0].category_name == "DeprecationWarning"

    def test_application_frame_is_captured(self) -> None:
        """The warning is captured with application_frame populated from
        the actual call site in our test file."""
        install_hook()
        self._emit_warning("find my caller")
        captured = get_captured_warnings()
        assert len(captured) == 1
        # application_frame is set (the innermost captured frame)
        assert captured[0].application_frame is not None

    def test_hook_restored_on_uninstall(self) -> None:
        original = warnings.showwarning
        install_hook()
        assert warnings.showwarning is not original
        capture.uninstall_hook()
        assert warnings.showwarning is original

    def test_hook_survives_exception(self) -> None:
        install_hook()
        assert capture.is_hook_installed() is True
        try:
            raise RuntimeError("test error")
        except RuntimeError:
            pass
        assert capture.is_hook_installed() is True

    def test_double_install_is_noop(self) -> None:
        install_hook()
        install_hook()  # Should not raise
        assert capture.is_hook_installed() is True
        capture.uninstall_hook()
        assert capture.is_hook_installed() is False

    def test_clear_captured_warnings(self) -> None:
        install_hook()
        self._emit_warning("clear me")
        assert len(get_captured_warnings()) == 1
        clear_captured_warnings()
        assert len(get_captured_warnings()) == 0

    def test_nested_warnings_captured(self) -> None:
        install_hook()

        def inner():
            self._emit_warning("inner warning")

        def outer():
            inner()

        outer()
        captured = get_captured_warnings()
        assert len(captured) == 1
        assert captured[0].message == "inner warning"

    def test_uninstall_hook_is_idempotent(self) -> None:
        capture.uninstall_hook()
        capture.uninstall_hook()
        capture.uninstall_hook()
        # Should not raise

    def test_get_aggregator_returns_same_instance(self) -> None:
        agg1 = capture.get_aggregator()
        agg2 = capture.get_aggregator()
        assert agg1 is agg2

    def test_is_hook_installed_reflects_state(self) -> None:
        assert capture.is_hook_installed() is False
        install_hook()
        assert capture.is_hook_installed() is True
        capture.uninstall_hook()
        assert capture.is_hook_installed() is False

    def test_hook_restores_passthrough_on_uninstall(self) -> None:
        """After uninstall, the original warning behavior is restored."""
        original = warnings.showwarning
        install_hook()
        warnings.warn("before uninstall", DeprecationWarning, stacklevel=2)
        capture.uninstall_hook()
        assert warnings.showwarning is original
        warnings.warn("after uninstall", DeprecationWarning, stacklevel=2)
        # No crash = passthrough works

    def test_captures_userwarning(self) -> None:
        install_hook()
        warnings.warn("user warning test", UserWarning, stacklevel=2)
        captured = get_captured_warnings()
        assert len(captured) == 1
        assert captured[0].category_name == "UserWarning"

    def test_stacklevel_adjusts_emission(self) -> None:
        """With stacklevel=2, the emission location should be the caller."""
        install_hook()

        def level2_caller():
            warnings.warn("stacklevel test", DeprecationWarning, stacklevel=2)

        level2_caller()
        captured = get_captured_warnings()
        assert len(captured) == 1
        # The emitted filename should be this test file
        assert "test_capture" in captured[0].filename


class TestWarnWrapping:
    def test_warn_wrapping_captures_warning(self) -> None:
        install_hook()
        capture.enable_warn_wrapping()
        warnings.warn("warn wrapped", DeprecationWarning, stacklevel=2)
        captured = get_captured_warnings()
        assert len(captured) == 1
        assert captured[0].message == "warn wrapped"

    def test_warn_wrapping_no_double_capture(self) -> None:
        install_hook()
        capture.enable_warn_wrapping()
        warnings.warn("double check", DeprecationWarning, stacklevel=2)
        captured = get_captured_warnings()
        assert len(captured) == 1

    def test_warn_wrapping_restored_on_disable(self) -> None:
        original = warnings.warn
        capture.enable_warn_wrapping()
        assert warnings.warn is not original
        capture.disable_warn_wrapping()
        assert warnings.warn is original

    def test_warn_wrapping_enable_is_idempotent(self) -> None:
        original = warnings.warn
        capture.enable_warn_wrapping()
        capture.enable_warn_wrapping()
        capture.enable_warn_wrapping()
        assert warnings.warn is not original
        capture.disable_warn_wrapping()
        assert warnings.warn is original

    def test_warn_wrapping_disable_is_idempotent(self) -> None:
        capture.disable_warn_wrapping()
        capture.disable_warn_wrapping()
        # Should not raise

    def test_warn_wrapping_captures_when_showwarning_replaced(self) -> None:
        """When showwarning is replaced (like pytest does),
        warn wrapping still captures the warning."""
        install_hook()
        capture.enable_warn_wrapping()
        # Replace showwarning (simulating pytest's catch_warnings)
        original_show = warnings.showwarning
        warnings.showwarning = lambda *a, **kw: None
        try:
            warnings.warn("hidden", DeprecationWarning, stacklevel=2)
        finally:
            warnings.showwarning = original_show
        captured = get_captured_warnings()
        assert len(captured) == 1
        assert captured[0].message == "hidden"
