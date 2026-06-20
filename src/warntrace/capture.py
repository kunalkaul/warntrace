"""Warning capture hook for intercepting Python warnings.

This module provides the core mechanism for intercepting warnings
emitted through Python's ``warnings`` module by replacing
``warnings.showwarning`` with a custom handler.
"""

from __future__ import annotations

import traceback
import warnings
from collections.abc import Callable
from typing import Any

from warntrace.models import CapturedWarning, FrameInfo
from warntrace.report import WarningAggregator
from warntrace.utils import (
    _frame_filename,
    clean_stack,
    frame_to_frame_info,
    is_warntrace_frame,
)

# Module-level state
_aggregator = WarningAggregator()
_original_showwarning: Callable[..., Any] | None = None
_hook_installed: bool = False
_passthrough_enabled: bool = True


def _make_warning_record(
    message: str,
    category: type[Warning],
    filename: str,
    lineno: int,
    stack: list[Any],
) -> None:
    """Capture a warning into the aggregator."""
    cleaned = clean_stack(stack)

    # Find the first application frame (first non-internal frame)
    application_frame: FrameInfo | None = None
    for frame in cleaned:
        fname = _frame_filename(frame)
        if fname and not is_warntrace_frame(fname):
            application_frame = frame_to_frame_info(frame)
            break

    _aggregator.add_warning(
        category_name=category.__name__,
        message=str(message),
        filename=filename,
        lineno=lineno,
        stack=cleaned,
        application_frame=application_frame,
    )


def custom_showwarning(
    message: warnings.WarningMessage | str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: Any = None,
    line: str | None = None,
) -> None:
    """Custom warning handler that captures warning details and the call stack.

    This replaces ``warnings.showwarning``. It:
    1. Captures the current call stack via ``traceback.extract_stack()``
    2. Builds a structured warning record
    3. Stores it in the module-level captured warnings list
    4. Passes the warning to the original handler (passthrough)
    """
    # Handle both new-style (WarningMessage) and old-style arguments
    if isinstance(message, warnings.WarningMessage):
        msg = message.message
        cat = message.category
        fn = message.filename
        ln = message.lineno
    else:
        msg = message
        cat = category
        fn = filename
        ln = lineno

    # Capture the current stack and record the warning.
    # Guard against re-entrancy: when the warn wrapper (_intercept_warn)
    # dispatches to the real warnings.warn, that calls this function.
    # We skip capture here in that case to avoid double-capture.
    if not _capturing_from_warn:
        raw_stack = traceback.extract_stack()
        _make_warning_record(
            message=str(msg),
            category=cat,
            filename=fn,
            lineno=ln,
            stack=raw_stack,
        )

    # Passthrough to original handler
    global _original_showwarning
    if _original_showwarning is not None and _passthrough_enabled:
        try:
            if isinstance(message, warnings.WarningMessage):
                _original_showwarning(message)
            else:
                _original_showwarning(message, category, filename, lineno, file, line)
        except Exception:
            pass  # Don't let a passthrough failure break capture


def install_hook() -> None:
    """Install the custom warning hook.

    Saves the current ``warnings.showwarning`` and replaces it.
    Idempotent: safe to call multiple times.
    """
    global _original_showwarning, _hook_installed
    if _hook_installed:
        return
    _original_showwarning = warnings.showwarning
    warnings.showwarning = custom_showwarning  # type: ignore[assignment]
    _hook_installed = True


def uninstall_hook() -> None:
    """Restore the original warning hook.

    Safe to call multiple times. Silently does nothing if the hook
    is not currently installed.
    """
    global _original_showwarning, _hook_installed
    if _hook_installed and _original_showwarning is not None:
        warnings.showwarning = _original_showwarning
        _original_showwarning = None
        _hook_installed = False


def get_captured_warnings() -> list[CapturedWarning]:
    """Return the list of captured warning records from the aggregator."""
    return _aggregator.get_warnings()


def clear_captured_warnings() -> None:
    """Clear all captured warnings from the aggregator."""
    _aggregator.clear()


def get_aggregator() -> WarningAggregator:
    """Return the module-level aggregator instance."""
    return _aggregator


def is_hook_installed() -> bool:
    """Check if the custom hook is currently installed."""
    return _hook_installed


def set_passthrough_enabled(enabled: bool) -> None:
    """Enable or disable passthrough of captured warnings to the original handler.

    When disabled, captured warnings are silently consumed instead of being
    forwarded to the original ``warnings.showwarning``. The default is enabled.
    """
    global _passthrough_enabled
    _passthrough_enabled = enabled


def get_passthrough_enabled() -> bool:
    """Return whether passthrough is currently enabled."""
    return _passthrough_enabled


# Warn-wrapping state
_original_warn: Callable[..., Any] | None = None
_warn_replacement_active: bool = False
_capturing_from_warn: bool = False


def _intercept_warn(
    message: Warning | str,
    category: type[Warning] = Warning,
    stacklevel: int = 1,
    source: Any = None,
) -> None:
    """Replacement for ``warnings.warn`` that captures before dispatching.

    Uses a re-entrancy guard so that when the real ``warnings.warn``
    internally calls ``custom_showwarning``, we do not capture twice.
    """
    global _capturing_from_warn, _original_warn

    if not _capturing_from_warn:
        _capturing_from_warn = True
        try:
            raw_stack = traceback.extract_stack()
            # Extract the caller's filename/lineno from the stack.
            # raw_stack[-1] is _intercept_warn; raw_stack[-2] is the
            # user code that called warnings.warn.
            caller_frame = raw_stack[-2] if len(raw_stack) >= 2 else None
            caller_fn = _frame_filename(caller_frame) if caller_frame else ""
            caller_ln = (
                int(caller_frame.lineno) if caller_frame and caller_frame.lineno is not None else 0
            )
            _make_warning_record(
                message=str(message),
                category=category if category is not Warning else UserWarning,
                filename=caller_fn,
                lineno=caller_ln,
                stack=raw_stack[:-1],
            )
            if _original_warn is not None and get_passthrough_enabled():
                # stacklevel+1 accounts for the extra wrapper frame
                _original_warn(message, category, stacklevel + 1, source)
        finally:
            _capturing_from_warn = False
    else:
        if _original_warn is not None and get_passthrough_enabled():
            _original_warn(message, category, stacklevel + 1, source)


def enable_warn_wrapping() -> None:
    """Replace ``warnings.warn`` with the interception wrapper.

    Idempotent: safe to call multiple times.
    """
    global _original_warn, _warn_replacement_active
    if _warn_replacement_active:
        return
    _original_warn = warnings.warn
    warnings.warn = _intercept_warn  # type: ignore[assignment]
    _warn_replacement_active = True


def disable_warn_wrapping() -> None:
    """Restore the original ``warnings.warn``.

    Idempotent: safe to call multiple times.
    """
    global _original_warn, _warn_replacement_active
    if _warn_replacement_active and _original_warn is not None:
        warnings.warn = _original_warn
        _original_warn = None
        _warn_replacement_active = False
