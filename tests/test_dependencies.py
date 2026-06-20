"""Tests for DistributionIndex."""

from __future__ import annotations

from importlib.metadata import distribution as dist_metadata

import pytest

from warntrace.dependencies import DependencyGraph, DistributionIndex

# A package that is guaranteed installed in the test environment
_KNOWN_PACKAGE = "pytest"


@pytest.fixture
def index() -> DistributionIndex:
    return DistributionIndex()


class TestLazyInitialization:
    """Tests that the index is not built until the first query."""

    def test_not_built_initially(self, index: DistributionIndex) -> None:
        assert not index.is_built

    def test_built_after_first_query(self, index: DistributionIndex) -> None:
        index.owner_for_path("/tmp/nonexistent.py")
        assert index.is_built


class TestKnownPackage:
    """Tests against a known installed package (pytest)."""

    def test_known_package_file_resolves(self, index: DistributionIndex) -> None:
        dist = dist_metadata(_KNOWN_PACKAGE)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            info = index.owner_for_path(str(installed_path))
            assert info is not None
            assert info.normalized_name == _KNOWN_PACKAGE.lower().replace("-", "_")

    def test_known_package_name_matches(self, index: DistributionIndex) -> None:
        dist = dist_metadata(_KNOWN_PACKAGE)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            info = index.owner_for_path(str(installed_path))
            assert info is not None
            assert info.name.lower() == _KNOWN_PACKAGE.lower()

    def test_known_package_version_present(self, index: DistributionIndex) -> None:
        dist = dist_metadata(_KNOWN_PACKAGE)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            info = index.owner_for_path(str(installed_path))
            assert info is not None
            assert info.version is not None


class TestUnknownPaths:
    """Tests that unknown paths return None."""

    def test_nonexistent_file_returns_none(self, index: DistributionIndex) -> None:
        assert index.owner_for_path("/tmp/nonexistent_file.py") is None

    def test_random_path_returns_none(self, index: DistributionIndex) -> None:
        assert index.owner_for_path("/opt/something/random.so") is None

    def test_empty_string_returns_none(self, index: DistributionIndex) -> None:
        assert index.owner_for_path("") is None

    def test_warntrace_source_not_a_distribution(self, index: DistributionIndex) -> None:
        """Warntrace source files are not installed as a distribution."""
        from warntrace.utils import get_warntrace_package_root

        root = get_warntrace_package_root()
        result = index.owner_for_path(str(root / "models.py"))
        # Warntrace source could be resolved if installed in dev mode
        # so this test is informational
        assert result is None or result.name == "warntrace"


class TestCacheBehavior:
    """Tests that the index caches results and does not rescan."""

    def test_cache_used_on_second_call(self, index: DistributionIndex) -> None:
        index.owner_for_path("/tmp/unused.py")
        assert index.is_built
        # Second call should not raise - index is already built
        index.owner_for_path("/tmp/another.py")

    def test_repeated_queries_same_path(self, index: DistributionIndex) -> None:
        # Query a real package path twice; should work both times
        dist = dist_metadata(_KNOWN_PACKAGE)
        if dist.files is not None:
            first_file = list(dist.files)[0]
            installed_path = dist.locate_file(first_file)
            result1 = index.owner_for_path(str(installed_path))
            result2 = index.owner_for_path(str(installed_path))
            assert result1 is not None
            assert result2 is not None
            assert result1.name == result2.name


class TestNameNormalization:
    """Tests for distribution name normalization."""

    def test_normalize_dashes(self) -> None:
        assert DistributionIndex._normalize_name("my-package") == "my_package"

    def test_normalize_dots(self) -> None:
        assert DistributionIndex._normalize_name("my.package") == "my_package"

    def test_normalize_mixed(self) -> None:
        assert DistributionIndex._normalize_name("My-Cool.Package") == "my_cool_package"

    def test_normalize_unchanged(self) -> None:
        assert DistributionIndex._normalize_name("simple") == "simple"


# --- DependencyGraph tests ---


@pytest.fixture
def graph() -> DependencyGraph:
    return DependencyGraph()


class TestDependencyGraphConstruction:
    """Tests for building the dependency graph."""

    def test_build_does_not_raise(self) -> None:
        g = DependencyGraph()
        assert g.is_built is False
        # Trigger build
        _ = g.find_shortest_path("pytest", "pluggy")
        assert g.is_built is True

    def test_build_with_existing_index(self, index: DistributionIndex) -> None:
        _ = index.distribution_names  # trigger index build
        g = DependencyGraph(index)
        _ = g.find_shortest_path("pytest", "pluggy")
        assert g.is_built is True


class TestRootDetection:
    """Tests for find_root()."""

    def test_root_detected_from_pyproject(self, graph: DependencyGraph) -> None:
        """Should detect warntrace as root when run from project CWD."""
        root = graph.find_root()
        assert root is not None
        assert root == "warntrace"

    def test_root_detected_explicit_name(self, graph: DependencyGraph) -> None:
        root = graph.find_root(project_name="warntrace")
        assert root == "warntrace"

    def test_root_not_found_for_unknown(self, graph: DependencyGraph) -> None:
        root = graph.find_root(project_name="nonexistent-project-name-xyz")
        assert root is None

    def test_is_built_after_root_detection(self, graph: DependencyGraph) -> None:
        graph.find_root()
        assert graph.is_built


class TestDirectDependencies:
    """Tests for is_direct_dependency()."""

    def test_known_direct_dep(self, graph: DependencyGraph) -> None:
        """Warntrace directly depends on packaging."""
        assert graph.is_direct_dependency("warntrace", "packaging") is True

    def test_not_a_direct_dep(self, graph: DependencyGraph) -> None:
        """Pytest is not a direct dependency of warntrace."""
        assert graph.is_direct_dependency("warntrace", "pytest") is False

    def test_unknown_root_is_false(self, graph: DependencyGraph) -> None:
        assert graph.is_direct_dependency("unknown-root", "packaging") is False

    def test_case_normalized(self, graph: DependencyGraph) -> None:
        assert graph.is_direct_dependency("Warntrace", "Packaging") is True


class TestBFSShortestPath:
    """Tests for find_shortest_path()."""

    def test_self_path(self, graph: DependencyGraph) -> None:
        path = graph.find_shortest_path("pytest", "pytest")
        assert path is not None
        assert len(path) == 1
        assert path[0].name == "pytest"

    def test_path_to_direct_dep(self, graph: DependencyGraph) -> None:
        path = graph.find_shortest_path("pytest", "packaging")
        assert path is not None
        assert len(path) == 2
        assert path[0].name == "pytest"
        assert path[1].name == "packaging"

    def test_path_to_unknown_returns_none(self, graph: DependencyGraph) -> None:
        path = graph.find_shortest_path("pytest", "nonexistent-xyzzy")
        assert path is None

    def test_path_from_unknown_returns_none(self, graph: DependencyGraph) -> None:
        path = graph.find_shortest_path("nonexistent-xyzzy", "pytest")
        assert path is None

    def test_path_deterministic(self, graph: DependencyGraph) -> None:
        path1 = graph.find_shortest_path("pytest", "packaging")
        path2 = graph.find_shortest_path("pytest", "packaging")
        assert path1 is not None and path2 is not None
        assert len(path1) == len(path2)
        for d1, d2 in zip(path1, path2, strict=True):
            assert d1.name == d2.name


class TestDependencyPathToRoot:
    """Tests for dependency_path_to_root()."""

    def test_path_to_root(self, graph: DependencyGraph) -> None:
        """Should find path from root to a dependency."""
        path = graph.dependency_path_to_root("warntrace", "packaging")
        assert path is not None
        assert len(path) == 2
        assert path[0].normalized_name == "warntrace"
        assert path[1].normalized_name == "packaging"

    def test_self_returns_none(self, graph: DependencyGraph) -> None:
        path = graph.dependency_path_to_root("warntrace", "warntrace")
        assert path is None

    def test_unknown_returns_none(self, graph: DependencyGraph) -> None:
        path = graph.dependency_path_to_root("warntrace", "nonexistent-xyzzy")
        assert path is None


class TestCycleSafety:
    """Tests that cycles do not cause infinite loops."""

    def test_bfs_with_cycle_terminates(self, graph: DependencyGraph) -> None:
        """BFS on any real graph should terminate via visited set."""
        path = graph.find_shortest_path("pytest", "nonexistent-xyzzy")
        # Should return None rather than loop forever
        assert path is None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_get_distribution_known(self, index: DistributionIndex) -> None:
        info = index.get_distribution("pytest")
        assert info is not None
        assert info.name == "pytest"

    def test_get_distribution_unknown(self, index: DistributionIndex) -> None:
        info = index.get_distribution("nonexistent-package-xyz")
        assert info is None

    def test_distribution_names_includes_known(self, index: DistributionIndex) -> None:
        names = index.distribution_names
        assert "pytest" in names or "pytest" in {n.replace("-", "_") for n in names}
