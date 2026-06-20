"""Tests for WarningClassifier."""

from __future__ import annotations

import sysconfig
from pathlib import Path

import pytest

from warntrace.classifier import WarningClassifier
from warntrace.dependencies import DependencyGraph, DistributionIndex
from warntrace.models import (
    CapturedWarning,
    FrameInfo,
    WarningOrigin,
    WarningReport,
)
from warntrace.ownership import OwnershipChecker
from warntrace.utils import get_warntrace_package_root


@pytest.fixture
def ownership() -> OwnershipChecker:
    return OwnershipChecker()


@pytest.fixture
def dist_index() -> DistributionIndex:
    return DistributionIndex()


@pytest.fixture
def graph() -> DependencyGraph:
    return DependencyGraph()


@pytest.fixture
def classifier(
    ownership: OwnershipChecker,
    dist_index: DistributionIndex,
    graph: DependencyGraph,
) -> WarningClassifier:
    return WarningClassifier(
        ownership=ownership,
        distribution_index=dist_index,
        dependency_graph=graph,
    )


@pytest.fixture
def classifier_no_graph(
    ownership: OwnershipChecker,
    dist_index: DistributionIndex,
) -> WarningClassifier:
    return WarningClassifier(ownership=ownership, distribution_index=dist_index)


def _make_frame(
    filename: str,
    lineno: int = 1,
    function: str = "func",
) -> FrameInfo:
    return FrameInfo(filename=filename, lineno=lineno, function=function)


def _make_warning(
    filename: str,
    stack: list[FrameInfo] | None = None,
    lineno: int = 10,
    category: str = "DeprecationWarning",
    message: str = "test warning",
) -> CapturedWarning:
    return CapturedWarning(
        category_name=category,
        message=message,
        filename=filename,
        lineno=lineno,
        stack=stack or [],
    )


class TestApplicationWarnings:
    """Warnings emitted from application code should be APPLICATION."""

    def test_simple_application_warning(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        app_file = str(ownership.root / "app.py")
        warning = _make_warning(filename=app_file)
        classifier.classify_warning(warning)
        assert warning.origin == WarningOrigin.APPLICATION

    def test_application_warning_with_stack(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        app_file = str(ownership.root / "app.py")
        stack = [_make_frame(str(ownership.root / "main.py"))]
        warning = _make_warning(filename=app_file, stack=stack)
        classifier.classify_warning(warning)
        assert warning.origin == WarningOrigin.APPLICATION

    def test_not_triggered_by_app_flag(self, classifier: WarningClassifier) -> None:
        """Application warnings should not be flagged as triggered by app code."""
        app_file = str(Path.cwd() / "app.py")
        warning = _make_warning(filename=app_file)
        classifier.classify_warning(warning)
        assert not warning.triggered_directly_by_application


class TestStdlibWarnings:
    """Warnings emitted from stdlib code should be STANDARD_LIBRARY."""

    def test_stdlib_warning(self, classifier: WarningClassifier) -> None:
        stdlib = sysconfig.get_paths().get("stdlib", "")
        if stdlib:
            stdlib_file = str(Path(stdlib) / "os.py")
            warning = _make_warning(filename=stdlib_file)
            classifier.classify_warning(warning)
            assert warning.origin == WarningOrigin.STANDARD_LIBRARY

    def test_stdlib_with_application_stack(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        stdlib = sysconfig.get_paths().get("stdlib", "")
        if stdlib:
            stdlib_file = str(Path(stdlib) / "os.py")
            app_frame = _make_frame(str(ownership.root / "app.py"))
            warning = _make_warning(filename=stdlib_file, stack=[app_frame])
            classifier.classify_warning(warning)
            assert warning.origin == WarningOrigin.STANDARD_LIBRARY
            # Stdlib warning with app frame should not set triggered_by_app
            assert not warning.triggered_directly_by_application


class TestUnknownWarnings:
    """Warnings from unknown paths should be UNKNOWN."""

    def test_unknown_path(self, classifier: WarningClassifier) -> None:
        warning = _make_warning(filename="/nonexistent/path.py")
        classifier.classify_warning(warning)
        assert warning.origin == WarningOrigin.UNKNOWN

    def test_unknown_no_application_frame(self, classifier: WarningClassifier) -> None:
        warning = _make_warning(filename="/nonexistent/path.py")
        classifier.classify_warning(warning)
        assert warning.application_frame is None

    def test_unknown_not_triggered_by_app(self, classifier: WarningClassifier) -> None:
        warning = _make_warning(filename="/nonexistent/path.py")
        classifier.classify_warning(warning)
        assert not warning.triggered_directly_by_application


class TestDistributionAnnotation:
    """Tests that frames get annotated with distribution info."""

    def test_dependency_frame_annotated(
        self, classifier: WarningClassifier, dist_index: DistributionIndex
    ) -> None:
        # Use a known installed package file
        from importlib.metadata import distribution as dist_meta

        known = "pytest"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            frame = _make_frame(str(installed_path))
            warning = _make_warning(filename=str(installed_path), stack=[frame])
            classifier.classify_warning(warning)
            # The frame should have distribution info
            assert warning.stack[0].distribution is not None
            assert warning.stack[0].distribution.normalized_name == "pytest"

    def test_emitted_by_set_for_dependency(
        self, classifier: WarningClassifier, dist_index: DistributionIndex
    ) -> None:
        from importlib.metadata import distribution as dist_meta

        known = "pytest"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            warning = _make_warning(filename=str(installed_path))
            classifier.classify_warning(warning)
            assert warning.emitted_by is not None
            assert warning.emitted_by.name.lower() == known.lower()

    def test_dependency_origin_is_unknown(
        self, classifier: WarningClassifier, dist_index: DistributionIndex
    ) -> None:
        """Installed but unreachable packages get UNKNOWN origin."""
        from importlib.metadata import distribution as dist_meta

        known = "pytest"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            warning = _make_warning(filename=str(installed_path))
            classifier.classify_warning(warning)
            assert warning.origin == WarningOrigin.UNKNOWN


class TestApplicationFrameDetection:
    """Tests for finding the first application frame in the stack."""

    def test_app_frame_found(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        app_frame = _make_frame(str(ownership.root / "app.py"))
        stdlib_path = Path(sysconfig.get_paths().get("stdlib", ""))
        stdlib_frame = _make_frame(str(stdlib_path / "os.py"))
        warning = _make_warning(
            filename=str(ownership.root / "lib.py"),
            stack=[app_frame, stdlib_frame],
        )
        classifier.classify_warning(warning)
        assert warning.application_frame is not None
        assert "app.py" in warning.application_frame.filename

    def test_no_app_frame(self, classifier: WarningClassifier) -> None:
        stdlib_frame = _make_frame(str(Path(sysconfig.get_paths().get("stdlib", "")) / "os.py"))
        warning = _make_warning(
            filename=str(Path(sysconfig.get_paths().get("stdlib", "")) / "io.py"),
            stack=[stdlib_frame],
        )
        classifier.classify_warning(warning)
        assert warning.application_frame is None


class TestTriggeredDirectlyByApp:
    """Tests for the triggered_directly_by_application flag."""

    def test_dependency_warning_triggered_by_app(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        from importlib.metadata import distribution as dist_meta

        known = "pytest"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            # App frame is before the emission frame in the stack
            app_frame = _make_frame(str(ownership.root / "app.py"))
            warning = _make_warning(
                filename=str(installed_path),
                stack=[app_frame],
            )
            classifier.classify_warning(warning)
            assert warning.triggered_directly_by_application

    def test_stdlib_not_triggered_by_app(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        stdlib = sysconfig.get_paths().get("stdlib", "")
        if stdlib:
            stdlib_file = str(Path(stdlib) / "os.py")
            app_frame = _make_frame(str(ownership.root / "app.py"))
            warning = _make_warning(filename=stdlib_file, stack=[app_frame])
            classifier.classify_warning(warning)
            assert not warning.triggered_directly_by_application

    def test_app_warning_not_triggered_by_app(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        app_file = str(ownership.root / "app.py")
        warning = _make_warning(filename=app_file)
        classifier.classify_warning(warning)
        assert not warning.triggered_directly_by_application


class TestClassifyReport:
    """Tests for the classify_report method on WarningReport."""

    def test_classify_report_processes_all_warnings(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        app_file = str(ownership.root / "app.py")
        unknown_file = "/nonexistent/path.py"
        warnings = [
            _make_warning(filename=app_file),
            _make_warning(filename=unknown_file),
        ]
        report = WarningReport(
            warnings=warnings,
            total_occurrences=2,
            started_at=0.0,
            finished_at=0.0,
        )
        classifier.classify_report(report)
        assert report.warnings[0].origin == WarningOrigin.APPLICATION
        assert report.warnings[1].origin == WarningOrigin.UNKNOWN

    def test_classify_report_does_not_crash_on_empty(self, classifier: WarningClassifier) -> None:
        report = WarningReport(
            warnings=[],
            total_occurrences=0,
            started_at=0.0,
            finished_at=0.0,
        )
        classifier.classify_report(report)


class TestWarntraceInternal:
    """Tests that Warntrace-internal paths are handled correctly."""

    def test_warntrace_file_is_unknown(self, classifier: WarningClassifier) -> None:
        root = get_warntrace_package_root()
        warning = _make_warning(filename=str(root / "models.py"))
        classifier.classify_warning(warning)
        assert warning.origin == WarningOrigin.UNKNOWN

    def test_warntrace_file_not_application(
        self, classifier: WarningClassifier, ownership: OwnershipChecker
    ) -> None:
        root = get_warntrace_package_root()
        warning = _make_warning(filename=str(root / "models.py"))
        classifier.classify_warning(warning)
        assert not ownership.is_application_path(root)


class TestDirectDependency:
    """Tests that direct dependency warnings are classified correctly."""

    def test_packaging_is_direct_dependency(self, classifier: WarningClassifier) -> None:
        from importlib.metadata import distribution as dist_meta

        known = "packaging"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            warning = _make_warning(filename=str(installed_path))
            classifier.classify_warning(warning)
            assert warning.origin == WarningOrigin.DIRECT_DEPENDENCY

    def test_direct_dependency_not_triggered_by_app(self, classifier: WarningClassifier) -> None:
        """A direct dep warning without an app frame is not flagged."""
        from importlib.metadata import distribution as dist_meta

        known = "packaging"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            warning = _make_warning(filename=str(installed_path))
            classifier.classify_warning(warning)
            assert not warning.triggered_directly_by_application


class TestDependencyPath:
    """Tests that dependency_path is attached correctly."""

    def test_dependency_path_attached_for_direct(self, classifier: WarningClassifier) -> None:
        from importlib.metadata import distribution as dist_meta

        known = "packaging"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            warning = _make_warning(filename=str(installed_path))
            classifier.classify_warning(warning)
            assert len(warning.dependency_path) == 2
            assert warning.dependency_path[0].name == "warntrace"
            assert warning.dependency_path[1].name == "packaging"

    def test_dependency_path_empty_for_unknown(self, classifier: WarningClassifier) -> None:
        warning = _make_warning(filename="/nonexistent/path.py")
        classifier.classify_warning(warning)
        assert warning.dependency_path == []

    def test_no_graph_fallback(self, classifier_no_graph: WarningClassifier) -> None:
        """Without a DependencyGraph, all deps remain UNKNOWN."""
        from importlib.metadata import distribution as dist_meta

        known = "packaging"
        dist = dist_meta(known)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            warning = _make_warning(filename=str(installed_path))
            classifier_no_graph.classify_warning(warning)
            assert warning.origin == WarningOrigin.UNKNOWN
            assert warning.dependency_path == []
