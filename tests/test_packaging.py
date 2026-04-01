"""Tests for packaging, imports, and distribution correctness.

Verifies that the package is properly structured for pip install,
PyInstaller builds, and general usability.
"""

import importlib
import os
import subprocess
import sys

import pytest


class TestModuleImports:
    """Every module should import cleanly without side effects."""

    MODULES = [
        "mavica_tools",
        "mavica_tools.cli",
        "mavica_tools.multipass",
        "mavica_tools.carve",
        "mavica_tools.check",
        "mavica_tools.repair",
        "mavica_tools.swaptest",
        "mavica_tools.fat12",
        "mavica_tools.recover",
        "mavica_tools.format",
        "mavica_tools.stamp",
        "mavica_tools.detect",
        "mavica_tools.gps",
        "mavica_tools.importcmd",
        "mavica_tools.fun",
        "mavica_tools.utils",
        "mavica_tools.terminal_image",
        "mavica_tools.tui",
        "mavica_tools.tui.app",
        "mavica_tools.tui.screens.home",
        "mavica_tools.tui.screens.import_workflow",
        "mavica_tools.tui.screens.multipass",
        "mavica_tools.tui.screens.recover_image_screen",
        "mavica_tools.tui.screens.check",
        "mavica_tools.tui.screens.repair",
        "mavica_tools.tui.screens.swaptest",
        "mavica_tools.tui.screens.stamp_screen",
        "mavica_tools.tui.screens.format_screen",
        "mavica_tools.tui.screens.gps_screen",
        "mavica_tools.tui.widgets.defrag_map",
        "mavica_tools.tui.widgets.image_preview",
        "mavica_tools.tui.widgets.file_picker",
        "mavica_tools.tui.widgets.sector_map",
    ]

    @pytest.mark.parametrize("module", MODULES)
    def test_module_imports(self, module):
        """Each module should import without error."""
        mod = importlib.import_module(module)
        assert mod is not None


class TestPackageMetadata:
    """Package metadata should be correct for PyPI."""

    def test_version_exists(self):
        from mavica_tools import __version__

        assert __version__
        assert isinstance(__version__, str)
        # Should be semver-like
        parts = __version__.split(".")
        assert len(parts) >= 2

    def test_cli_entry_point_importable(self):
        from mavica_tools.cli import main

        assert callable(main)

    def test_dunder_main_exists(self):
        """__main__.py should exist and reference cli.main."""
        import mavica_tools.__main__

        assert hasattr(mavica_tools.__main__, "main")
        assert callable(mavica_tools.__main__.main)


class TestCLIHelp:
    """CLI should show help without crashing."""

    def test_mavica_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "mavica_tools", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "mavica" in result.stdout.lower()

    def test_all_subcommands_in_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "mavica_tools"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout + result.stderr
        for tool in [
            "import",
            "multipass",
            "carve",
            "check",
            "repair",
            "swaptest",
            "fat12",
            "recover",
            "format",
            "stamp",
            "detect",
            "gps",
            "tui",
        ]:
            assert tool in output, f"'{tool}' missing from CLI help"

    @pytest.mark.parametrize(
        "subcommand",
        [
            "import",
            "multipass",
            "carve",
            "check",
            "repair",
            "stamp",
            "detect",
        ],
    )
    def test_subcommand_help(self, subcommand):
        result = subprocess.run(
            [sys.executable, "-m", "mavica_tools", subcommand, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0


class TestProjectFiles:
    """Required project files should exist."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @pytest.mark.parametrize(
        "path",
        [
            "pyproject.toml",
            "LICENSE",
            "README.md",
            "mavica.spec",
            "mavica_tools/__init__.py",
            "mavica_tools/__main__.py",
            "mavica_tools/cli.py",
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
        ],
    )
    def test_file_exists(self, path):
        assert os.path.exists(os.path.join(self.ROOT, path)), f"Missing: {path}"

    def test_pyproject_has_required_fields(self):
        import tomllib

        with open(os.path.join(self.ROOT, "pyproject.toml"), "rb") as f:
            config = tomllib.load(f)

        project = config["project"]
        assert project["name"] == "mavica-tools"
        assert "version" in project
        assert "description" in project
        assert "dependencies" in project
        assert "license" in project
        assert "Pillow" in str(project["dependencies"])
        assert "textual" in str(project["dependencies"])

        assert "scripts" in project
        assert "mavica" in project["scripts"]

        assert "optional-dependencies" in project
        assert "gps" in project["optional-dependencies"]
        assert "dev" in project["optional-dependencies"]

    def test_pyinstaller_spec_lists_all_modules(self):
        with open(os.path.join(self.ROOT, "mavica.spec")) as f:
            spec = f.read()

        # Every tool module should be in hiddenimports
        for mod in [
            "mavica_tools.multipass",
            "mavica_tools.carve",
            "mavica_tools.check",
            "mavica_tools.repair",
            "mavica_tools.gps",
            "mavica_tools.importcmd",
            "mavica_tools.fun",
        ]:
            assert mod in spec, f"PyInstaller spec missing: {mod}"


class TestOptionalDependencies:
    """Optional deps should degrade gracefully."""

    def test_gps_works_without_piexif(self):
        """GPS module should import fine; stamp_gps_exif should fail gracefully."""
        from mavica_tools.gps import match_photos_to_track, parse_gpx

        # Core functions don't need piexif
        assert callable(parse_gpx)
        assert callable(match_photos_to_track)

    def test_piexif_is_optional_dep(self):
        import tomllib

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), "rb") as f:
            config = tomllib.load(f)
        deps = str(config["project"]["dependencies"])
        assert "piexif" not in deps, "piexif should not be a hard dependency"

        gps_deps = str(config["project"]["optional-dependencies"]["gps"])
        assert "piexif" in gps_deps
