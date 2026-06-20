"""Filesystem ownership classification."""

from __future__ import annotations

import sysconfig
from pathlib import Path

from warntrace.utils import get_warntrace_package_root

_VENV_NAMES = frozenset({".venv", "venv"})


class OwnershipChecker:
    """Classifies filesystem paths as application, standard-library,
    or Warntrace-owned.

    Application root defaults to the current working directory. Paths inside
    virtual environments (``.venv``, ``venv``) or ``site-packages`` are
    excluded from application ownership even if they fall under the root.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root).resolve() if root else Path.cwd().resolve()
        self._stdlib_paths = self._detect_stdlib_paths()
        self._warntrace_root = get_warntrace_package_root()

    @staticmethod
    def _detect_stdlib_paths() -> tuple[Path, ...]:
        paths = sysconfig.get_paths()
        result: list[Path] = []
        for key in ("stdlib", "platstdlib"):
            val = paths.get(key, "")
            if val:
                result.append(Path(val).resolve())
        return tuple(result)

    @property
    def root(self) -> Path:
        return self._root

    def is_warntrace_path(self, path: str | Path) -> bool:
        resolved = Path(path).resolve()
        return self._warntrace_root in resolved.parents or resolved == self._warntrace_root

    def is_application_path(self, path: str | Path) -> bool:
        resolved = Path(path).resolve()
        if not (self._root in resolved.parents or resolved == self._root):
            return False
        for part in resolved.parts:
            if part in _VENV_NAMES or part == "site-packages":
                return False
        return not self.is_warntrace_path(resolved)

    def is_stdlib_path(self, path: str | Path) -> bool:
        resolved = Path(path).resolve()
        return any(
            stdlib in resolved.parents or resolved == stdlib for stdlib in self._stdlib_paths
        )

    def is_known_path(self, path: str | Path) -> bool:
        resolved = Path(path).resolve()
        return (
            self.is_warntrace_path(resolved)
            or self.is_application_path(resolved)
            or self.is_stdlib_path(resolved)
        )
