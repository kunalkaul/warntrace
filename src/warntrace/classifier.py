"""Warning classification logic."""

from __future__ import annotations

from pathlib import Path

from warntrace.dependencies import DependencyGraph, DistributionIndex
from warntrace.models import (
    CapturedWarning,
    DistributionInfo,
    FrameInfo,
    WarningOrigin,
    WarningReport,
)
from warntrace.ownership import OwnershipChecker


class WarningClassifier:
    """Enriches captured warnings with ownership and classification metadata.

    Uses an ``OwnershipChecker`` to determine filesystem ownership, a
    ``DistributionIndex`` to map file paths to installed distributions, and
    an optional ``DependencyGraph`` to classify dependency warnings as
    direct or transitive.

    This is a post-processing step — the classifier does not modify the
    capture or aggregation flow.
    """

    def __init__(
        self,
        ownership: OwnershipChecker,
        distribution_index: DistributionIndex,
        dependency_graph: DependencyGraph | None = None,
    ) -> None:
        self._ownership = ownership
        self._distribution_index = distribution_index
        self._graph = dependency_graph

    def classify_warning(self, warning: CapturedWarning) -> None:
        """Classify a single captured warning, enriching it in place."""
        emission_path = Path(warning.filename).resolve()

        # Annotate frames with distribution info
        warning.stack = [self._annotate_frame(f) for f in warning.stack]

        # Determine who emitted the warning
        warning.emitted_by = self._distribution_index.owner_for_path(emission_path)

        # Find the first meaningful application frame
        warning.application_frame = self._find_first_application_frame(warning.stack)

        # Assign the origin classification
        warning.origin = self._classify_origin(emission_path, warning.emitted_by)

        # Attach dependency path when applicable
        if (
            warning.origin
            in (
                WarningOrigin.DIRECT_DEPENDENCY,
                WarningOrigin.TRANSITIVE_DEPENDENCY,
            )
            and warning.emitted_by is not None
        ):
            warning.dependency_path = self._build_dependency_path(warning.emitted_by)

        # Detect if triggered directly by application code
        warning.triggered_directly_by_application = self._check_triggered_by_app(
            warning.origin,
            warning.emitted_by,
            warning.application_frame,
        )

    def _annotate_frame(self, frame: FrameInfo) -> FrameInfo:
        if frame.distribution is not None:
            return frame
        path = Path(frame.filename).resolve()
        dist = self._distribution_index.owner_for_path(path)
        if dist is not None:
            return FrameInfo(
                filename=frame.filename,
                lineno=frame.lineno,
                function=frame.function,
                source_line=frame.source_line,
                module_name=frame.module_name,
                distribution=dist,
            )
        return frame

    def _find_first_application_frame(
        self,
        stack: list[FrameInfo],
    ) -> FrameInfo | None:
        for frame in stack:
            path = Path(frame.filename).resolve()
            if self._ownership.is_application_path(path):
                return frame
        return None

    def _classify_origin(
        self,
        emission_path: Path,
        emitted_by: DistributionInfo | None,
    ) -> WarningOrigin:
        if self._ownership.is_warntrace_path(emission_path):
            return WarningOrigin.UNKNOWN
        if self._ownership.is_application_path(emission_path):
            return WarningOrigin.APPLICATION
        if emitted_by is not None:
            return self._classify_dependency(emitted_by)
        if self._ownership.is_stdlib_path(emission_path):
            return WarningOrigin.STANDARD_LIBRARY
        return WarningOrigin.UNKNOWN

    def _classify_dependency(self, emitted_by: DistributionInfo) -> WarningOrigin:
        if self._graph is None:
            return WarningOrigin.UNKNOWN
        root = self._graph.find_root()
        if root is None:
            return WarningOrigin.UNKNOWN
        if self._graph.is_direct_dependency(root, emitted_by.name):
            return WarningOrigin.DIRECT_DEPENDENCY
        if self._graph.dependency_path_to_root(root, emitted_by.name) is not None:
            return WarningOrigin.TRANSITIVE_DEPENDENCY
        return WarningOrigin.UNKNOWN

    def _build_dependency_path(self, emitted_by: DistributionInfo) -> list[DistributionInfo]:
        if self._graph is None:
            return []
        root = self._graph.find_root()
        if root is None:
            return []
        path = self._graph.dependency_path_to_root(root, emitted_by.name)
        return path or []

    @staticmethod
    def _check_triggered_by_app(
        origin: WarningOrigin,
        emitted_by: DistributionInfo | None,
        application_frame: FrameInfo | None,
    ) -> bool:
        return (
            origin != WarningOrigin.APPLICATION
            and emitted_by is not None
            and application_frame is not None
        )

    def classify_report(self, report: WarningReport) -> None:
        """Classify all warnings in a report in place."""
        for warning in report.warnings:
            self.classify_warning(warning)
