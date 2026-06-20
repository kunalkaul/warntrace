"""Tests for OwnershipChecker."""

from __future__ import annotations

import sysconfig

import pytest

from warntrace.ownership import OwnershipChecker
from warntrace.utils import get_warntrace_package_root


@pytest.fixture
def checker() -> OwnershipChecker:
    return OwnershipChecker()


class TestDefaults:
    """Tests with default CWD-based application root."""

    def test_cwd_is_application(self, checker: OwnershipChecker) -> None:
        assert checker.is_application_path(checker.root / "some_file.py")

    def test_subdirectory_is_application(self, checker: OwnershipChecker) -> None:
        assert checker.is_application_path(checker.root / "subdir" / "module.py")

    def test_outside_root_is_not_application(self, checker: OwnershipChecker) -> None:
        assert not checker.is_application_path("/tmp/outside.py")

    def test_path_in_venv_is_not_application(self, checker: OwnershipChecker) -> None:
        path = checker.root / ".venv" / "lib" / "site-packages" / "pkg" / "mod.py"
        assert not checker.is_application_path(path)

    def test_path_in_venv_dir_is_not_application(self, checker: OwnershipChecker) -> None:
        path = checker.root / "venv" / "lib" / "pkg" / "mod.py"
        assert not checker.is_application_path(path)

    def test_path_in_site_packages_is_not_application(self, checker: OwnershipChecker) -> None:
        path = checker.root / "lib" / "site-packages" / "pkg" / "mod.py"
        assert not checker.is_application_path(path)


class TestStdlib:
    """Tests for standard-library detection via sysconfig."""

    def test_stdlib_path_is_detected(self, checker: OwnershipChecker) -> None:
        stdlib = sysconfig.get_paths().get("stdlib", "")
        if stdlib:
            assert checker.is_stdlib_path(stdlib)

    def test_stdlib_module_is_detected(self, checker: OwnershipChecker) -> None:
        stdlib = sysconfig.get_paths().get("stdlib", "")
        if stdlib:
            path = f"{stdlib}/os.py"
            assert checker.is_stdlib_path(path)

    def test_platstdlib_path_is_detected(self, checker: OwnershipChecker) -> None:
        platstdlib = sysconfig.get_paths().get("platstdlib", "")
        if platstdlib:
            assert checker.is_stdlib_path(platstdlib)

    def test_application_path_is_not_stdlib(self, checker: OwnershipChecker) -> None:
        assert not checker.is_stdlib_path(checker.root / "app.py")


class TestWarntrace:
    """Tests for Warntrace internal path detection."""

    def test_warntrace_root_is_detected(self, checker: OwnershipChecker) -> None:
        root = get_warntrace_package_root()
        assert checker.is_warntrace_path(root)

    def test_warntrace_file_is_detected(self, checker: OwnershipChecker) -> None:
        root = get_warntrace_package_root()
        assert checker.is_warntrace_path(root / "models.py")

    def test_warntrace_subpackage_is_detected(self, checker: OwnershipChecker) -> None:
        root = get_warntrace_package_root()
        assert checker.is_warntrace_path(root / "sub" / "mod.py")

    def test_application_path_is_not_warntrace(self, checker: OwnershipChecker) -> None:
        assert not checker.is_warntrace_path(checker.root / "app.py")


class TestKnownPath:
    """Tests for is_known_path."""

    def test_application_path_is_known(self, checker: OwnershipChecker) -> None:
        assert checker.is_known_path(checker.root / "app.py")

    def test_stdlib_path_is_known(self, checker: OwnershipChecker) -> None:
        stdlib = sysconfig.get_paths().get("stdlib", "")
        if stdlib:
            assert checker.is_known_path(stdlib)

    def test_warntrace_path_is_known(self, checker: OwnershipChecker) -> None:
        root = get_warntrace_package_root()
        assert checker.is_known_path(root)

    def test_unknown_path_is_not_known(self, checker: OwnershipChecker) -> None:
        assert not checker.is_known_path("/nonexistent/path.py")


class TestCustomRoot:
    """Tests with a custom application root."""

    def test_custom_root_used(self) -> None:
        custom = OwnershipChecker(root="/my/project")
        assert custom.root == __import__("pathlib").Path("/my/project").resolve()

    def test_path_inside_custom_root(self) -> None:
        checker = OwnershipChecker(root="/my/project")
        assert checker.is_application_path("/my/project/src/app.py")

    def test_cwd_not_application_with_custom_root(self) -> None:
        from pathlib import Path

        checker = OwnershipChecker(root="/other/project")
        cwd_file = Path.cwd() / "file.py"
        assert not checker.is_application_path(cwd_file)


class PropertyTests:
    """Tests for OwnershipChecker properties."""

    def test_root_property(self, checker: OwnershipChecker) -> None:
        from pathlib import Path

        assert checker.root == Path.cwd().resolve()

    def test_stdlib_detected(self, checker: OwnershipChecker) -> None:
        stdlib = sysconfig.get_paths().get("stdlib", "")
        assert checker.is_stdlib_path(stdlib)
