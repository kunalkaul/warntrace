"""Example: a simple warning emitted from application code.

Shows how to use the ``capture_warnings()`` context manager to capture
warnings emitted during a function call.

Works both standalone and under ``warntrace run``.

Usage::

    uv run python examples/application_warning.py
"""

from __future__ import annotations

import json
import warnings

from warntrace import capture_warnings, is_hook_installed


def inner() -> None:
    warnings.warn("example warning", DeprecationWarning, stacklevel=2)


def outer() -> None:
    inner()


def main() -> None:
    if is_hook_installed():
        # Running under warntrace run — capture is automatic
        outer()
        return

    with capture_warnings(passthrough=False) as tracer:
        outer()

    report = tracer.stop()
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
