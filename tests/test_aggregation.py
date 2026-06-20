"""Tests for warning aggregation and deduplication."""

from warntrace.models import FrameInfo
from warntrace.report import WarningAggregator


class TestWarningAggregator:
    def test_add_single_warning(self) -> None:
        agg = WarningAggregator()
        agg.add_warning(
            category_name="DeprecationWarning",
            message="old API",
            filename="/app/code.py",
            lineno=42,
            stack=[("/app/main.py", 10, "main", "run()")],
        )
        warnings = agg.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].category_name == "DeprecationWarning"
        assert warnings[0].occurrence_count == 1

    def test_identical_warnings_grouped(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("DeprecationWarning", "old API", "/app/code.py", 42, stack)
        agg.add_warning("DeprecationWarning", "old API", "/app/code.py", 42, stack)
        warnings = agg.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].occurrence_count == 2

    def test_different_emission_location_separate_groups(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("DeprecationWarning", "msg", "/app/code.py", 42, stack)
        agg.add_warning("DeprecationWarning", "msg", "/app/other.py", 99, stack)
        warnings = agg.get_warnings()
        assert len(warnings) == 2

    def test_different_app_frames_separate_groups(self) -> None:
        agg = WarningAggregator()
        stack1 = [("/app/main.py", 10, "main", "run()")]
        stack2 = [("/app/other.py", 20, "other", "do()")]
        app1 = FrameInfo(filename="/app/main.py", lineno=10, function="main")
        app2 = FrameInfo(filename="/app/other.py", lineno=20, function="other")
        agg.add_warning(
            "DeprecationWarning", "msg", "/app/code.py", 42, stack1, application_frame=app1
        )
        agg.add_warning(
            "DeprecationWarning", "msg", "/app/code.py", 42, stack2, application_frame=app2
        )
        warnings = agg.get_warnings()
        assert len(warnings) == 2

    def test_different_category_separate_groups(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("DeprecationWarning", "msg", "/app/code.py", 42, stack)
        agg.add_warning("UserWarning", "msg", "/app/code.py", 42, stack)
        warnings = agg.get_warnings()
        assert len(warnings) == 2

    def test_three_call_sites_limit(self) -> None:
        """Same fingerprint (same app frame) groups together, up to 3 call sites."""
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        app = FrameInfo(filename="/app/main.py", lineno=10, function="main")

        # Same fingerprint, same app frame → should all group together
        for _ in range(5):
            agg.add_warning(
                "DeprecationWarning",
                "msg",
                "/app/code.py",
                42,
                stack,
                application_frame=app,
            )

        warnings = agg.get_warnings()
        assert len(warnings) == 1
        assert warnings[0].occurrence_count == 5
        assert len(warnings[0].application_call_sites) == 1  # same site, only stored once

    def test_insertion_order_deterministic(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("B", "second", "/app/b.py", 2, stack)
        agg.add_warning("A", "first", "/app/a.py", 1, stack)

        warnings = agg.get_warnings()
        assert warnings[0].category_name == "B"
        assert warnings[1].category_name == "A"

    def test_build_report_timestamps(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("DeprecationWarning", "msg", "/app/code.py", 42, stack)
        report = agg.build_report()
        assert report.started_at <= report.finished_at
        assert report.total_occurrences == 1
        assert len(report.warnings) == 1

    def test_build_report_tracks_total_occurrences(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("A", "msg", "/app/a.py", 1, stack)
        agg.add_warning("A", "msg", "/app/a.py", 1, stack)
        agg.add_warning("B", "msg", "/app/b.py", 2, stack)
        report = agg.build_report()
        assert report.total_occurrences == 3

    def test_clear_resets_aggregator(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("DeprecationWarning", "msg", "/app/code.py", 42, stack)
        agg.clear()
        warnings = agg.get_warnings()
        assert len(warnings) == 0

    def test_get_warnings_before_build(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        agg.add_warning("DeprecationWarning", "msg", "/app/code.py", 42, stack)
        warnings = agg.get_warnings()
        assert len(warnings) == 1

    def test_same_call_site_not_duplicated(self) -> None:
        agg = WarningAggregator()
        stack = [("/app/main.py", 10, "main", "run()")]
        app = FrameInfo(filename="/app/main.py", lineno=10, function="main")
        agg.add_warning(
            "DeprecationWarning", "msg", "/app/code.py", 42, stack, application_frame=app
        )
        agg.add_warning(
            "DeprecationWarning", "msg", "/app/code.py", 42, stack, application_frame=app
        )
        warnings = agg.get_warnings()
        assert len(warnings[0].application_call_sites) == 1
