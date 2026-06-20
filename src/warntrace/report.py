"""Warning report aggregation and deduplication."""

from __future__ import annotations

import time
from typing import Any

from warntrace.models import CapturedWarning, FrameInfo, WarningReport
from warntrace.utils import frame_to_frame_info, warning_fingerprint


class WarningAggregator:
    """Aggregates raw warning records and groups duplicates by fingerprint.

    Maintains an internal dict of fingerprint -> CapturedWarning,
    merging identical warnings by incrementing ``occurrence_count``
    and storing up to three distinct application call sites.
    """

    def __init__(self) -> None:
        self._groups: dict[tuple[Any, ...], CapturedWarning] = {}
        self._order: list[tuple[Any, ...]] = []  # insertion order for deterministic output
        self._started_at: float = time.time()

    def add_warning(
        self,
        category_name: str,
        message: str,
        filename: str,
        lineno: int,
        stack: list[Any],
        application_frame: FrameInfo | None = None,
    ) -> None:
        """Add a raw warning record to the aggregator.

        Args:
            category_name: The warning class name (e.g. ``"DeprecationWarning"``).
            message: The warning message text.
            filename: The file where the warning was emitted.
            lineno: The line number where the warning was emitted.
            stack: The cleaned stack of raw frame objects.
            application_frame: The first meaningful application frame, if known.
        """
        # Convert raw stack frames to FrameInfo instances
        frame_infos = [frame_to_frame_info(f) for f in stack]

        # Build the initial CapturedWarning
        warning = CapturedWarning(
            category_name=category_name,
            message=message,
            filename=filename,
            lineno=lineno,
            stack=frame_infos,
            application_frame=application_frame,
        )

        fp = warning_fingerprint(
            category_name=category_name,
            message=message,
            filename=filename,
            lineno=lineno,
            application_frame=application_frame,
        )

        if fp in self._groups:
            # Merge with existing group
            existing = self._groups[fp]
            existing.occurrence_count += 1

            # Store up to 3 distinct application call sites
            if application_frame is not None:
                # Check if this call site is already stored
                already_stored = any(
                    _same_call_site(a, application_frame) for a in existing.application_call_sites
                )
                if not already_stored and len(existing.application_call_sites) < 3:
                    existing.application_call_sites.append(application_frame)
                    # Update the main application_frame if it was None
                    if existing.application_frame is None:
                        existing.application_frame = application_frame
        else:
            self._groups[fp] = warning
            self._order.append(fp)

            # Store the first application call site
            if application_frame is not None:
                warning.application_call_sites.append(application_frame)

    def build_report(self) -> WarningReport:
        """Build and return the final ``WarningReport``."""
        finished_at = time.time()
        warnings_list = [self._groups[fp] for fp in self._order]
        total_occurrences = sum(w.occurrence_count for w in warnings_list)
        return WarningReport(
            warnings=warnings_list,
            total_occurrences=total_occurrences,
            started_at=self._started_at,
            finished_at=finished_at,
        )

    def get_warnings(self) -> list[CapturedWarning]:
        """Return the captured warnings in insertion order."""
        return [self._groups[fp] for fp in self._order]

    def clear(self) -> None:
        """Reset the aggregator, clearing all groups."""
        self._groups.clear()
        self._order.clear()
        self._started_at = time.time()


def _same_call_site(a: FrameInfo, b: FrameInfo) -> bool:
    """Check if two FrameInfo instances refer to the same call site."""
    return a.filename == b.filename and a.lineno == b.lineno
