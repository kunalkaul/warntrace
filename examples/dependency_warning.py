"""Example: a warning emitted from simulated dependency code.

This mimics a dependency module emitting a warning that the
application triggers via a call chain.

Works both standalone and under ``warntrace run``.

Usage::

    uv run python examples/dependency_warning.py
"""

from __future__ import annotations

import json
import warnings

from warntrace import capture_warnings, is_hook_installed


class _helper:
    """Simulates a third-party helper."""

    @staticmethod
    def do_something() -> None:
        warnings.warn(
            "deprecated_function() is deprecated; use new_function() instead",
            DeprecationWarning,
            stacklevel=2,
        )


def run() -> None:
    _helper.do_something()


def main() -> None:
    if is_hook_installed():
        run()
        return

    with capture_warnings(passthrough=False) as tracer:
        run()

    report = tracer.stop()
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
