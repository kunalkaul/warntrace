"""Core data models for warning reports.

All models use standard-library dataclasses to avoid runtime
dependencies on Pydantic or attrs.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class WarningOrigin(str, enum.Enum):
    """Classification of where a warning originates from."""

    APPLICATION = "application"
    DIRECT_DEPENDENCY = "direct_dependency"
    TRANSITIVE_DEPENDENCY = "transitive_dependency"
    STANDARD_LIBRARY = "standard_library"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DistributionInfo:
    """Information about an installed Python distribution (package)."""

    name: str
    normalized_name: str
    version: str | None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "normalized_name": self.normalized_name}
        if self.version is not None:
            d["version"] = self.version
        return d


@dataclass(frozen=True, slots=True)
class FrameInfo:
    """A single stack frame with ownership metadata."""

    filename: str
    lineno: int
    function: str
    source_line: str | None = None
    module_name: str | None = None
    distribution: DistributionInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "filename": self.filename,
            "lineno": self.lineno,
            "function": self.function,
        }
        if self.source_line is not None:
            d["source_line"] = self.source_line
        if self.module_name is not None:
            d["module_name"] = self.module_name
        if self.distribution is not None:
            d["distribution"] = self.distribution.to_dict()
        return d


@dataclass(slots=True)
class CapturedWarning:
    """A group of one or more identical warning occurrences."""

    category_name: str
    message: str
    filename: str
    lineno: int
    stack: list[FrameInfo]
    emitted_by: DistributionInfo | None = None
    application_frame: FrameInfo | None = None
    origin: WarningOrigin = WarningOrigin.UNKNOWN
    dependency_path: list[DistributionInfo] = field(default_factory=list)
    triggered_directly_by_application: bool = False
    occurrence_count: int = 1
    application_call_sites: list[FrameInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "category": self.category_name,
            "message": self.message,
            "origin": self.origin.value,
            "triggered_directly_by_application": self.triggered_directly_by_application,
            "occurrences": self.occurrence_count,
            "emitted_from": {
                "filename": self.filename,
                "lineno": self.lineno,
                "distribution": self.emitted_by.to_dict() if self.emitted_by else None,
            },
            "application_frame": self.application_frame.to_dict()
            if self.application_frame
            else None,
            "dependency_path": [d.to_dict() for d in self.dependency_path],
            "stack": [f.to_dict() for f in self.stack],
        }
        return d


@dataclass(slots=True)
class WarningReport:
    """Complete warning report for one session."""

    warnings: list[CapturedWarning]
    total_occurrences: int
    started_at: float
    finished_at: float
    schema_version: str = "0.1"

    def to_dict(self) -> dict[str, Any]:
        summary_counts: dict[str, int] = {
            "application": 0,
            "direct_dependency": 0,
            "transitive_dependency": 0,
            "standard_library": 0,
            "unknown": 0,
        }
        for w in self.warnings:
            key = w.origin.value
            if key in summary_counts:
                summary_counts[key] += 1

        return {
            "schema_version": self.schema_version,
            "summary": {
                "unique_warnings": len(self.warnings),
                "total_occurrences": self.total_occurrences,
                **summary_counts,
            },
            "warnings": [w.to_dict() for w in self.warnings],
        }
