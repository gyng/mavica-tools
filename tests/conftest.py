"""Shared test fixtures and configuration."""

import glob
import os

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixture_dir():
    """Path to the tests/fixtures/ directory."""
    return FIXTURES_DIR


@pytest.fixture
def fixture_jpegs():
    """Sorted list of real Mavica JPEG paths from fixtures."""
    return sorted(glob.glob(os.path.join(FIXTURES_DIR, "*.JPG")))


@pytest.fixture
def fixture_thumbnails():
    """Sorted list of real .411 thumbnail paths from fixtures."""
    return sorted(glob.glob(os.path.join(FIXTURES_DIR, "*.411")))


@pytest.fixture
def fixture_disk_image():
    """Path to the good FAT12 disk image with 5 JPEGs + 6 .411s."""
    return os.path.join(FIXTURES_DIR, "disk_with_photos.img")


# Prevent any test from triggering real floppy drive hardware.
# Mock subprocess.run in detect.py and os.path.isdir for A:\/B:\ at session level.

_original_isdir = os.path.isdir


def _safe_isdir(path):
    """os.path.isdir that never probes floppy drives A: or B:."""
    if isinstance(path, str):
        normalized = path.upper().replace("/", "\\")
        if normalized in ("A:\\", "B:\\", "A:", "B:"):
            return False
    return _original_isdir(path)


def pytest_configure(config):
    """Patch os.path.isdir globally to avoid probing floppy drives on Windows."""
    os.path.isdir = _safe_isdir
    os.environ["MAVICA_NO_FLOPPY_PROBE"] = "1"
