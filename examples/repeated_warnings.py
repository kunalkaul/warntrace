"""Example: the same warning emitted multiple times.

This verifies that each warning event is captured individually
(rather than being deduplicated at capture time) and that the
aggregator correctly reports occurrence counts.

Works both standalone and under ``warntrace run``.

Usage::

    uv run python examples/repeated_warnings.py
"""

from __future__ import annotations

import json
import warnings

from warntrace import capture_warnings, is_hook_installed


def emit_warning() -> None:
    warnings.warn("repeated deprecation warning", DeprecationWarning, stacklevel=2)


def main() -> None:
    if is_hook_installed():
        for _ in range(5):
            emit_warning()
        return

    with capture_warnings(passthrough=False) as tracer:
        for _ in range(5):
            emit_warning()

    report = tracer.stop()
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
