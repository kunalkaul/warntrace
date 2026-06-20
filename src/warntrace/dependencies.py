"""Dependency graph and distribution ownership."""

from __future__ import annotations

from pathlib import Path

from warntrace.models import DistributionInfo


class DistributionIndex:
    """Lazily-built index mapping installed file paths to distributions.

    Uses :func:`importlib.metadata.distributions` to enumerate installed
    packages and maps their installed file paths to ``DistributionInfo``.
    The index is built once per process lifetime.

    **Ownership resolution order:**

    1. Exact installed-file match
    2. Longest matching distribution directory
    3. Top-level import-to-distribution mapping
    """

    def __init__(self) -> None:
        self._path_index: dict[Path, DistributionInfo] = {}
        self._import_to_dist: dict[str, list[DistributionInfo]] = {}
        self._distributions_by_normalized: dict[str, DistributionInfo] = {}
        self._built = False

    def _ensure_built(self) -> None:
        if self._built:
            return
        self._built = True
        self._build_index()

    def _build_index(self) -> None:
        from importlib.metadata import distributions, packages_distributions

        # Primary strategy: exact installed-file ownership
        for dist in distributions():
            name = dist.metadata.get("Name", "")  # type: ignore[attr-defined]
            if not name:
                continue
            version = dist.metadata.get("Version", "")  # type: ignore[attr-defined]
            normalized = self._normalize_name(name)
            info = DistributionInfo(
                name=name,
                normalized_name=normalized,
                version=version or None,
            )
            self._distributions_by_normalized[normalized] = info

            if dist.files is not None:
                for file in dist.files:
                    try:
                        installed_path = dist.locate_file(file)
                        resolved = Path(str(installed_path)).resolve()
                    except (RuntimeError, OSError):
                        continue
                    self._path_index[resolved] = info

        # Fallback: top-level import name -> distribution
        for import_name, dist_names in packages_distributions().items():
            for dist_name in dist_names:
                normalized = self._normalize_name(dist_name)
                matched = self._distributions_by_normalized.get(normalized)
                if matched is not None:
                    self._import_to_dist.setdefault(import_name, []).append(matched)

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.lower().replace("-", "_").replace(".", "_").replace(" ", "_")

    def owner_for_path(self, path: str | Path) -> DistributionInfo | None:
        """Return the ``DistributionInfo`` owning *path*, or ``None``."""
        self._ensure_built()
        resolved = Path(path).resolve()

        # 1. Exact file match
        info = self._path_index.get(resolved)
        if info is not None:
            return info

        # 2. Longest directory match
        best: DistributionInfo | None = None
        best_len = 0
        for installed_path, dist_info in self._path_index.items():
            parent = installed_path.parent
            if parent in resolved.parents:
                depth = len(parent.parts)
                if depth > best_len:
                    best_len = depth
                    best = dist_info

        if best is not None:
            return best

        # 3. Module-name fallback
        module_name = self._module_name_from_path(resolved)
        if module_name:
            dists = self._import_to_dist.get(module_name, [])
            if len(dists) == 1:
                return dists[0]

        return None

    @staticmethod
    def _module_name_from_path(path: Path) -> str | None:
        for parent in path.parents:
            if parent.name == "site-packages":
                try:
                    relative = path.relative_to(parent)
                    top_level = relative.parts[0]
                    return top_level.replace(".py", "").replace("/", "").replace("\\", "")
                except (ValueError, IndexError):
                    return None
        return None

    def get_distribution(self, name: str) -> DistributionInfo | None:
        """Return the ``DistributionInfo`` for a given normalized name."""
        self._ensure_built()
        return self._distributions_by_normalized.get(name)

    @property
    def distribution_names(self) -> frozenset[str]:
        """Return all known distribution normalized names."""
        self._ensure_built()
        return frozenset(self._distributions_by_normalized.keys())

    @property
    def is_built(self) -> bool:
        return self._built


class DependencyGraph:
    """Builds and queries the installed dependency graph.

    Uses :func:`importlib.metadata.requires` and :mod:`packaging` to build an
    adjacency map of installed distributions and their core (non-extra,
    active-marker) dependencies.

    The graph is separate from ``DistributionIndex`` — it answers *who depends
    on whom* rather than *which file belongs to which package*.
    """

    def __init__(self, distribution_index: DistributionIndex | None = None) -> None:
        self._index = distribution_index or DistributionIndex()
        self._graph: dict[str, set[str]] = {}
        self._by_canonical: dict[str, DistributionInfo] = {}
        self._built = False

    def _ensure_built(self) -> None:
        if self._built:
            return
        self._built = True
        self._build()

    def _build(self) -> None:
        from importlib.metadata import requires

        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name

        # Ensure distribution index is populated
        _ = self._index.distribution_names

        # Build canonical-name index from DistributionIndex
        for norm_name in self._index.distribution_names:
            info = self._index.get_distribution(norm_name)
            if info is not None:
                canonical: str = str(canonicalize_name(info.name))
                self._by_canonical[canonical] = info

        # Build the adjacency graph from requires()
        for canonical, info in self._by_canonical.items():
            deps: set[str] = set()
            raw = requires(info.name)
            if raw is not None:
                for req_str in raw:
                    try:
                        req = Requirement(req_str)
                    except Exception:
                        continue
                    if req.extras:
                        continue
                    if req.marker is not None:
                        try:
                            if not req.marker.evaluate():
                                continue
                        except Exception:
                            continue
                    deps.add(canonicalize_name(req.name))
            self._graph[canonical] = deps

    @property
    def is_built(self) -> bool:
        return self._built

    def find_root(self, project_name: str | None = None) -> str | None:
        """Detect the root project (the project being developed).

        Attempts in order:

        1. Use *project_name* explicitly if provided
        2. Read ``pyproject.toml`` from CWD and look up ``[project].name``
        3. Return ``None``

        Returns the canonical name of the root project, or ``None``.
        """
        self._ensure_built()

        if project_name:
            from packaging.utils import canonicalize_name

            name = canonicalize_name(project_name)
            if name in self._graph:
                return name
            return None

        project_name_from_file = self._read_pyproject_name()
        if project_name_from_file:
            from packaging.utils import canonicalize_name

            cname: str = str(canonicalize_name(project_name_from_file))
            if cname in self._graph:
                return cname

        return None

    @staticmethod
    def _read_pyproject_name() -> str | None:
        import re

        pyproject = Path.cwd() / "pyproject.toml"
        if not pyproject.exists():
            return None
        try:
            text = pyproject.read_text(encoding="utf-8")
            match = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if match:
                return match.group(1)
        except Exception:
            pass
        return None

    def is_direct_dependency(self, root: str, name: str) -> bool:
        """Check if *name* is a direct dependency of *root*."""
        self._ensure_built()
        from packaging.utils import canonicalize_name

        root_deps = self._graph.get(canonicalize_name(root))
        if root_deps is None:
            return False
        return canonicalize_name(name) in root_deps

    def find_shortest_path(self, from_name: str, to_name: str) -> list[DistributionInfo] | None:
        """BFS to find the shortest dependency path between two distributions.

        Returns a list of ``DistributionInfo`` from *from_name* to *to_name*,
        or ``None`` if no path exists (or one of the names is unknown).
        """
        self._ensure_built()
        from collections import deque

        from packaging.utils import canonicalize_name

        from_norm = canonicalize_name(from_name)
        to_norm = canonicalize_name(to_name)

        if from_norm == to_norm:
            info = self._by_canonical.get(from_norm)
            return [info] if info else None

        visited: set[str] = {from_norm}
        queue: deque[tuple[str, list[str]]] = deque()
        queue.append((from_norm, [from_norm]))

        while queue:
            current, path = queue.popleft()
            for dep in self._graph.get(current, set()):
                if dep == to_norm:
                    return self._names_to_infos(path + [dep])
                if dep not in visited:
                    visited.add(dep)
                    queue.append((dep, path + [dep]))

        return None

    def dependency_path_to_root(self, root: str, name: str) -> list[DistributionInfo] | None:
        """Find the shortest path from *root* to *name*.

        Returns ``None`` if *name* is the root itself or no path exists.
        """
        from packaging.utils import canonicalize_name

        if canonicalize_name(root) == canonicalize_name(name):
            return None
        return self.find_shortest_path(root, name)

    def _names_to_infos(self, names: list[str]) -> list[DistributionInfo]:
        result: list[DistributionInfo] = []
        for name in names:
            info = self._by_canonical.get(name)
            if info is not None:
                result.append(info)
        return result
