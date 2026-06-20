"""Utility functions for path inspection and frame filtering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from warntrace.models import FrameInfo


def get_warntrace_package_root() -> Path:
    """Return the absolute path to the warntrace package directory."""
    return Path(__file__).resolve().parent


def is_internal_warnings_frame(filename: str) -> bool:
    """Check if a frame belongs to Python's warnings module internals."""
    if not filename:
        return False
    path = Path(filename)
    return path.name == "warnings.py"


def is_warntrace_frame(filename: str) -> bool:
    """Check if a frame belongs to the warntrace package itself."""
    if not filename:
        return False
    try:
        warntrace_root = get_warntrace_package_root()
        frame_path = Path(filename).resolve()
        return warntrace_root in frame_path.parents or frame_path == warntrace_root
    except (RuntimeError, ValueError, OSError):
        return False


def is_traceback_internal(filename: str) -> bool:
    """Check if a frame belongs to traceback module internals."""
    if not filename:
        return False
    path = Path(filename)
    return path.name in ("traceback.py", "tracemalloc.py")


def _frame_filename(frame: Any) -> str:
    """Extract filename from a frame, handling FrameSummary and tuple types."""
    if isinstance(frame, (list, tuple)):
        return str(frame[0]) if len(frame) > 0 else ""
    return str(getattr(frame, "filename", ""))


def _frame_lineno(frame: Any) -> int:
    """Extract line number from a frame."""
    if isinstance(frame, (list, tuple)):
        return int(frame[1]) if len(frame) > 1 else 0
    return int(getattr(frame, "lineno", 0))


def _frame_function(frame: Any) -> str:
    """Extract function name from a frame."""
    if isinstance(frame, (list, tuple)):
        return str(frame[2]) if len(frame) > 2 else ""
    return str(getattr(frame, "name", ""))


def _frame_source_line(frame: Any) -> str | None:
    """Extract source line text from a frame."""
    if isinstance(frame, (list, tuple)):
        if len(frame) > 3 and frame[3] is not None:
            return str(frame[3])
        return None
    line = getattr(frame, "line", None)
    return str(line) if line is not None else None


def _frame_module_name(frame: Any) -> str | None:
    """Extract module name from a frame, if available."""
    if isinstance(frame, (list, tuple)):
        return None  # tuples don't carry module info
    return str(getattr(frame, "module", None)) if hasattr(frame, "module") else None


def frame_to_frame_info(frame: Any, distribution: Any = None) -> FrameInfo:
    """Convert a raw stack frame (FrameSummary or tuple) to a FrameInfo.

    Args:
        frame: A ``traceback.FrameSummary`` or a 4-tuple.
        distribution: Optional ``DistributionInfo`` to attach.

    Returns:
        A ``FrameInfo`` instance.
    """
    from warntrace.models import DistributionInfo as DI

    dist: DI | None = distribution
    return FrameInfo(
        filename=_frame_filename(frame),
        lineno=_frame_lineno(frame),
        function=_frame_function(frame),
        source_line=_frame_source_line(frame),
        module_name=_frame_module_name(frame),
        distribution=dist,
    )


def normalize_message(message: str) -> str:
    """Normalize a warning message for stable fingerprinting.

    Strips leading/trailing whitespace and collapses internal
    whitespace. Does NOT remove numbers, paths, or other
    semantically important content (see §15 of the PLAN).
    """
    return " ".join(message.split())


def warning_fingerprint(
    category_name: str,
    message: str,
    filename: str,
    lineno: int,
    application_frame: FrameInfo | None = None,
) -> tuple[Any, ...]:
    """Compute a stable fingerprint for warning deduplication.

    The fingerprint includes:
    - warning category name
    - normalized message
    - emission filename and line number
    - first application call site filename and line number (if available)

    Returns:
        A hashable tuple.
    """
    norm_msg = normalize_message(message)
    if application_frame is not None:
        return (
            category_name,
            norm_msg,
            filename,
            lineno,
            application_frame.filename,
            application_frame.lineno,
        )
    return (
        category_name,
        norm_msg,
        filename,
        lineno,
    )


def clean_stack(
    stack: list[Any],
) -> list[Any]:
    """Remove warntrace, warnings-dispatch, and traceback-internal frames
    from the captured stack.

    ``traceback.extract_stack()`` returns frames from outermost (index 0)
    to innermost (last index). Internal frames (hook, warnings dispatch)
    are at the end of the list, so we trim from the tail.

    Args:
        stack: A list of frame entries (FrameSummary objects or tuples).

    Returns:
        A new list with internal frames removed from the end.
    """
    if not stack:
        return stack

    # Find the first internal frame from the end, then trim at that point.
    # Walk from the end backward. When we find a non-internal frame,
    # set end_idx to include it (i + 1). When we find an internal one,
    # set end_idx to exclude it (i). Stop searching once we've passed
    # the internal section.
    end_idx = len(stack)
    for i in range(len(stack) - 1, -1, -1):
        frame = stack[i]
        filename = _frame_filename(frame)
        if not filename:
            end_idx = i
            break
        if (
            is_warntrace_frame(filename)
            or is_internal_warnings_frame(filename)
            or is_traceback_internal(filename)
        ):
            end_idx = i  # exclude this internal frame
        else:
            # This is a non-internal frame — include it
            end_idx = i + 1
            break

    # Keep at least one frame
    if end_idx <= 0 and len(stack) > 0:
        end_idx = 1

    return stack[:end_idx]
