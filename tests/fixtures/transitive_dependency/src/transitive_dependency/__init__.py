"""Fixture: transitive dependency that emits a DeprecationWarning."""

import warnings


def transitive_warning() -> None:
    warnings.warn("transitive dep is deprecated", DeprecationWarning, stacklevel=2)
