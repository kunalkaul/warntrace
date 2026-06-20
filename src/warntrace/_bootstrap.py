"""Child-process bootstrap script generation.

Generates the ``sitecustomize.py`` script that is injected into child
processes via ``PYTHONPATH``. The script installs the warntrace capture
hook at import time and registers an ``atexit`` handler that writes the
classified report as JSON.
"""

from __future__ import annotations


def make_bootstrap_script() -> str:
    """Return the Python source code for the child bootstrap script.

    The returned script is intended to be written to a ``sitecustomize.py``
    file in a temporary directory that is prepended to ``PYTHONPATH``.
    """
    return '''"""Warntrace bootstrap — installed by ``warntrace run``."""
import atexit
import json
import os
import sys


def _install_warntrace() -> None:
    # Import lazily to avoid interfering with Python startup
    from warntrace.capture import (
        clear_captured_warnings,
        enable_warn_wrapping,
        install_hook,
        set_passthrough_enabled,
    )

    root = os.environ.get("WARNTRACE_ROOT")
    show_all = os.environ.get("WARNTRACE_SHOW_ALL") == "1"
    passthrough = os.environ.get("WARNTRACE_PASSTHROUGH", "1") != "0"

    if show_all:
        import warnings  # noqa: PLC0415

        warnings.resetwarnings()
        warnings.simplefilter("always")

    set_passthrough_enabled(passthrough)
    clear_captured_warnings()
    install_hook()
    enable_warn_wrapping()


def _finalize_warntrace() -> None:
    from warntrace.capture import get_aggregator, uninstall_hook
    from warntrace.classifier import WarningClassifier
    from warntrace.dependencies import DependencyGraph, DistributionIndex
    from warntrace.ownership import OwnershipChecker

    report_path = os.environ.get("WARNTRACE_REPORT_PATH")
    if not report_path:
        return

    root = os.environ.get("WARNTRACE_ROOT")

    uninstall_hook()

    report = get_aggregator().build_report()
    classifier = WarningClassifier(
        ownership=OwnershipChecker(root=root),
        distribution_index=DistributionIndex(),
        dependency_graph=DependencyGraph(),
    )
    classifier.classify_report(report)

    tmp = report_path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        os.replace(tmp, report_path)
    except Exception:
        pass


_install_warntrace()
atexit.register(_finalize_warntrace)
'''
