"""Fixture: direct dependency that emits a UserWarning and calls transitive-dep."""

import warnings

from transitive_dependency import transitive_warning


def direct_warning() -> None:
    warnings.warn("direct dep is deprecated", UserWarning, stacklevel=2)


def call_transitive() -> None:
    transitive_warning()
