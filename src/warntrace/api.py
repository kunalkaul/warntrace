"""Public Python API for warning capture."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from warntrace.capture import (
    clear_captured_warnings,
    disable_warn_wrapping,
    enable_warn_wrapping,
    get_aggregator,
    install_hook,
    is_hook_installed,
    set_passthrough_enabled,
    uninstall_hook,
)
from warntrace.classifier import WarningClassifier
from warntrace.dependencies import DependencyGraph, DistributionIndex
from warntrace.models import WarningReport
from warntrace.ownership import OwnershipChecker


class WarningTracer:
    """High-level API for capturing and classifying Python warnings.

    Manages the full lifecycle: install the capture hook, configure passthrough
    and show-all modes, classify captured warnings, and build the final report.

    Args:
        root: Application root directory (default: CWD).
        show_all: If True, set ``warnings.simplefilter("always")`` to capture
            normally-suppressed warnings.
        passthrough: If True (default), forward captured warnings to the
            original warning handler. If False, silently consume them.
    """

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        show_all: bool = False,
        passthrough: bool = True,
    ) -> None:
        self._root = root
        self._show_all = show_all
        self._passthrough = passthrough
        self._started: bool = False
        self._saved_filters: list[Any] = []
        self._classifier: WarningClassifier | None = None
        self._report: WarningReport | None = None

    def start(self) -> None:
        """Install the capture hook and prepare the environment.

        Raises ``RuntimeError`` if already started or the hook is already
        installed by another caller.
        """
        if self._started:
            raise RuntimeError("WarningTracer is already started")
        if is_hook_installed():
            raise RuntimeError("Warntrace hook is already installed")

        if self._show_all:
            self._saved_filters = list(warnings.filters[:])
            warnings.simplefilter("always")

        clear_captured_warnings()
        set_passthrough_enabled(self._passthrough)
        install_hook()
        enable_warn_wrapping()
        self._started = True

    def stop(self) -> WarningReport:
        """Uninstall the hook, restore the environment, and return the report.

        Idempotent: subsequent calls return the same report.
        Raises ``RuntimeError`` if ``start()`` was never called.
        """
        if self._report is not None:
            return self._report
        if not self._started:
            raise RuntimeError("WarningTracer is not started")

        disable_warn_wrapping()
        uninstall_hook()
        set_passthrough_enabled(True)

        if self._saved_filters:
            warnings.filters[:] = self._saved_filters  # type: ignore[index]
            self._saved_filters = []

        self._started = False

        report = get_aggregator().build_report()
        self._get_classifier().classify_report(report)
        self._report = report
        return report

    def report(self) -> WarningReport:
        """Return a classified snapshot without stopping the tracer.

        Raises ``RuntimeError`` if not started.
        """
        if not self._started:
            raise RuntimeError("WarningTracer is not started")
        report = get_aggregator().build_report()
        self._get_classifier().classify_report(report)
        return report

    @property
    def is_started(self) -> bool:
        """Whether the tracer is currently capturing."""
        return self._started

    def _get_classifier(self) -> WarningClassifier:
        if self._classifier is not None:
            return self._classifier
        ownership = OwnershipChecker(root=self._root)
        dist_index = DistributionIndex()
        dep_graph = DependencyGraph(dist_index)
        self._classifier = WarningClassifier(
            ownership=ownership,
            distribution_index=dist_index,
            dependency_graph=dep_graph,
        )
        return self._classifier


@contextmanager
def capture_warnings(
    *,
    root: str | Path | None = None,
    show_all: bool = False,
    passthrough: bool = True,
) -> Iterator[WarningTracer]:
    """Context manager for capturing Python warnings.

    Args:
        root: Application root directory (default: CWD).
        show_all: If True, capture normally-suppressed warnings.
        passthrough: If True (default), forward warnings to the original handler.

    Yields:
        A :class:`WarningTracer` that provides ``report()`` and ``stop()``.

    Example::

        with capture_warnings() as tracer:
            import warnings
            warnings.warn("hello", DeprecationWarning)
        report = tracer.stop()
        print(report.to_dict())
    """
    tracer = WarningTracer(root=root, show_all=show_all, passthrough=passthrough)
    tracer.start()
    try:
        yield tracer
    finally:
        tracer.stop()
