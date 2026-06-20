"""Tests for the data models module."""

import pytest

from warntrace.models import (
    CapturedWarning,
    DistributionInfo,
    FrameInfo,
    WarningOrigin,
    WarningReport,
)


class TestWarningOrigin:
    def test_has_correct_values(self) -> None:
        assert WarningOrigin.APPLICATION.value == "application"
        assert WarningOrigin.DIRECT_DEPENDENCY.value == "direct_dependency"
        assert WarningOrigin.TRANSITIVE_DEPENDENCY.value == "transitive_dependency"
        assert WarningOrigin.STANDARD_LIBRARY.value == "standard_library"
        assert WarningOrigin.UNKNOWN.value == "unknown"

    def test_is_comparable_to_string(self) -> None:
        assert WarningOrigin.APPLICATION == "application"
        assert WarningOrigin.UNKNOWN == "unknown"

    def test_all_members_have_unique_values(self) -> None:
        values = [m.value for m in WarningOrigin]
        assert len(values) == len(set(values)), "All WarningOrigin values must be unique"


class TestDistributionInfo:
    def test_frozen_cannot_modify(self) -> None:
        d = DistributionInfo(name="pkg", normalized_name="pkg", version="1.0")
        with pytest.raises(AttributeError):  # type: ignore[name-defined]  # noqa: F821, PT012
            d.name = "other"  # type: ignore[misc]

    def test_to_dict_with_version(self) -> None:
        d = DistributionInfo(name="My-Pkg", normalized_name="my-pkg", version="2.0.1")
        result = d.to_dict()
        assert result == {
            "name": "My-Pkg",
            "normalized_name": "my-pkg",
            "version": "2.0.1",
        }

    def test_to_dict_without_version(self) -> None:
        d = DistributionInfo(name="lib", normalized_name="lib", version=None)
        result = d.to_dict()
        assert result == {"name": "lib", "normalized_name": "lib"}
        assert "version" not in result


class TestFrameInfo:
    def test_frozen_cannot_modify(self) -> None:
        f = FrameInfo(filename="a.py", lineno=1, function="foo")
        with pytest.raises(AttributeError):  # type: ignore[name-defined]  # noqa: F821, PT012
            f.filename = "b.py"  # type: ignore[misc]

    def test_to_dict_basic(self) -> None:
        f = FrameInfo(filename="app.py", lineno=42, function="run")
        result = f.to_dict()
        assert result == {
            "filename": "app.py",
            "lineno": 42,
            "function": "run",
        }

    def test_to_dict_with_all_optionals(self) -> None:
        dist = DistributionInfo(name="dep", normalized_name="dep", version="1.0")
        f = FrameInfo(
            filename="dep.py",
            lineno=10,
            function="helper",
            source_line="helper()",
            module_name="dep.helper",
            distribution=dist,
        )
        result = f.to_dict()
        assert result["source_line"] == "helper()"
        assert result["module_name"] == "dep.helper"
        assert result["distribution"] == dist.to_dict()

    def test_to_dict_excludes_none_optionals(self) -> None:
        f = FrameInfo(filename="app.py", lineno=1, function="main")
        result = f.to_dict()
        assert "source_line" not in result
        assert "module_name" not in result
        assert "distribution" not in result


class TestCapturedWarning:
    def test_default_origin_is_unknown(self) -> None:
        w = CapturedWarning(
            category_name="DeprecationWarning",
            message="test",
            filename="a.py",
            lineno=1,
            stack=[],
        )
        assert w.origin == WarningOrigin.UNKNOWN

    def test_occurrence_count_defaults_to_one(self) -> None:
        w = CapturedWarning(
            category_name="DeprecationWarning",
            message="test",
            filename="a.py",
            lineno=1,
            stack=[],
        )
        assert w.occurrence_count == 1

    def test_triggered_directly_defaults_to_false(self) -> None:
        w = CapturedWarning(
            category_name="DeprecationWarning",
            message="test",
            filename="a.py",
            lineno=1,
            stack=[],
        )
        assert w.triggered_directly_by_application is False

    def test_to_dict_basic(self) -> None:
        w = CapturedWarning(
            category_name="DeprecationWarning",
            message="old API is deprecated",
            filename="/app/code.py",
            lineno=42,
            stack=[],
        )
        result = w.to_dict()
        assert result["category"] == "DeprecationWarning"
        assert result["message"] == "old API is deprecated"
        assert result["origin"] == "unknown"
        assert result["occurrences"] == 1
        assert result["triggered_directly_by_application"] is False
        assert result["emitted_from"]["filename"] == "/app/code.py"
        assert result["emitted_from"]["lineno"] == 42
        assert result["emitted_from"]["distribution"] is None
        assert result["application_frame"] is None
        assert result["dependency_path"] == []

    def test_to_dict_with_origin_and_path(self) -> None:
        dist = DistributionInfo(name="dep", normalized_name="dep", version="1.0")
        app_frame = FrameInfo(
            filename="/app/main.py", lineno=10, function="start", source_line="run()"
        )
        w = CapturedWarning(
            category_name="DeprecationWarning",
            message="test",
            filename="/site-packages/dep/utils.py",
            lineno=88,
            stack=[],
            emitted_by=dist,
            application_frame=app_frame,
            origin=WarningOrigin.DIRECT_DEPENDENCY,
            dependency_path=[
                DistributionInfo(name="app", normalized_name="app", version="0.1"),
                dist,
            ],
            triggered_directly_by_application=True,
            occurrence_count=3,
        )
        result = w.to_dict()
        assert result["origin"] == "direct_dependency"
        assert result["occurrences"] == 3
        assert result["triggered_directly_by_application"] is True
        assert result["emitted_from"]["distribution"] == dist.to_dict()
        assert result["application_frame"] is not None
        assert len(result["dependency_path"]) == 2


class TestWarningReport:
    def test_empty_report(self) -> None:
        report = WarningReport(
            warnings=[],
            total_occurrences=0,
            started_at=100.0,
            finished_at=101.0,
        )
        result = report.to_dict()
        assert result["schema_version"] == "0.1"
        assert result["summary"]["unique_warnings"] == 0
        assert result["summary"]["total_occurrences"] == 0
        assert result["warnings"] == []

    def test_report_with_warnings(self) -> None:
        w1 = CapturedWarning(
            category_name="DeprecationWarning",
            message="old API",
            filename="a.py",
            lineno=1,
            stack=[],
            origin=WarningOrigin.APPLICATION,
        )
        w2 = CapturedWarning(
            category_name="UserWarning",
            message="direct dep warning",
            filename="b.py",
            lineno=2,
            stack=[],
            origin=WarningOrigin.DIRECT_DEPENDENCY,
        )
        report = WarningReport(
            warnings=[w1, w2],
            total_occurrences=3,
            started_at=100.0,
            finished_at=102.0,
        )
        result = report.to_dict()
        assert result["summary"]["unique_warnings"] == 2
        assert result["summary"]["total_occurrences"] == 3
        assert result["summary"]["application"] == 1
        assert result["summary"]["direct_dependency"] == 1
        assert result["summary"]["transitive_dependency"] == 0
        assert result["summary"]["standard_library"] == 0
        assert result["summary"]["unknown"] == 0
        assert len(result["warnings"]) == 2

    def test_deterministic_ordering(self) -> None:
        w1 = CapturedWarning(
            category_name="A", message="first", filename="a.py", lineno=1, stack=[]
        )
        w2 = CapturedWarning(
            category_name="B", message="second", filename="b.py", lineno=2, stack=[]
        )
        report = WarningReport(
            warnings=[w1, w2],
            total_occurrences=2,
            started_at=0.0,
            finished_at=1.0,
        )
        result_a = report.to_dict()
        result_b = report.to_dict()
        assert result_a == result_b  # deterministic
