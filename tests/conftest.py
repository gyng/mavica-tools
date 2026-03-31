"""Shared test fixtures and configuration."""

import os
from unittest.mock import patch

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
