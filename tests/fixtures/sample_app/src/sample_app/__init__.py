"""Fixture: sample application that triggers warnings through its dependency chain."""

from direct_dependency import call_transitive, direct_warning


def run() -> None:
    direct_warning()
    call_transitive()
