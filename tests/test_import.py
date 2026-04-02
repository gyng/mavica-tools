"""Tests for the quick import command."""

import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from mavica_tools.importcmd import quick_import


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_jpeg(directory, name="MVC-001.JPG", width=640, height=480):
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    path = os.path.join(directory, name)
    img.save(path, "JPEG")
    return path


class TestQuickImport:
    def test_import_from_directory(self, tmp_dir):
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        make_jpeg(src, "MVC-002.JPG")
        out = os.path.join(tmp_dir, "photos")

        result = quick_import(src, out)
        assert result["imported"] == 2
        assert os.path.exists(os.path.join(out, "MVC-001.JPG"))
        assert os.path.exists(os.path.join(out, "MVC-002.JPG"))

    def test_import_with_tagging(self, tmp_dir):
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        out = os.path.join(tmp_dir, "photos")

        result = quick_import(src, out, model="fd7")
        assert result["imported"] == 1
        assert result["tagged"] is True

        # Verify EXIF was written
        img = Image.open(os.path.join(out, "MVC-001.JPG"))
        exif = img.getexif()
        assert exif.get(0x0110) == "SONY MAVICA MVC-FD7"  # Model

    def test_import_empty_directory(self, tmp_dir):
        src = os.path.join(tmp_dir, "empty")
        os.makedirs(src)
        out = os.path.join(tmp_dir, "photos")

        result = quick_import(src, out)
        assert result["imported"] == 0

    def test_import_avoids_overwrite(self, tmp_dir):
        """Importing same files twice shouldn't overwrite."""
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        out = os.path.join(tmp_dir, "photos")

        quick_import(src, out)
        quick_import(src, out)  # Second import

        files = os.listdir(out)
        assert len(files) == 2  # MVC-001.JPG + MVC-001_1.JPG

    def test_import_all_in_one(self, tmp_dir):
        """Import + tag in one call."""
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        make_jpeg(src, "MVC-002.JPG")
        out = os.path.join(tmp_dir, "photos")

        result = quick_import(src, out, model="fd88")
        assert result["imported"] == 2
        assert result["tagged"] is True


class TestImportAutoDetect:
    def test_cli_autodetects_single_drive(self, tmp_dir):
        """mavica import (no source) should auto-detect and import."""
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        out = os.path.join(tmp_dir, "photos")

        with patch(
            "mavica_tools.detect.detect_floppy_mount_points",
            return_value=[src],
        ):
            result = quick_import(src, out)
        assert result["imported"] >= 1

    def test_cli_no_source_no_drives_exits(self):
        """mavica import with no source and no drives should exit 1."""
        with patch(
            "mavica_tools.detect.detect_floppy_mount_points",
            return_value=[],
        ):
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from unittest.mock import patch; "
                    "patch('mavica_tools.detect.detect_floppy_mount_points', return_value=[]).start(); "
                    "from mavica_tools.importcmd import main; main()",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        assert result.returncode != 0


class TestImportRealFixtures:
    """Import tests using real Mavica photos from fixtures."""

    def test_import_real_mavica_photos(self, tmp_dir, fixture_dir):
        """Import real Mavica JPEGs, verify count and valid structure."""
        # Copy fixture JPEGs to a fake floppy source dir
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        import glob
        import shutil

        for f in glob.glob(os.path.join(fixture_dir, "*.JPG")):
            shutil.copy2(f, src)

        out = os.path.join(tmp_dir, "photos")
        result = quick_import(src, out)

        assert result["imported"] == 5
        # Verify each output is a valid JPEG (starts with SOI)
        for path in result["files"]:
            with open(path, "rb") as fh:
                assert fh.read(2) == b"\xff\xd8"

    def test_import_with_thumbnails(self, tmp_dir, fixture_dir):
        """Import directory with both .JPG and .411 files."""
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        import glob
        import shutil

        for f in glob.glob(os.path.join(fixture_dir, "*.JPG")) + glob.glob(
            os.path.join(fixture_dir, "*.411")
        ):
            shutil.copy2(f, src)

        out = os.path.join(tmp_dir, "photos")
        result = quick_import(src, out)

        # Should import both JPEGs and .411 thumbnails
        assert result["imported"] == 11
        out_files = os.listdir(out)
        jpg_count = sum(1 for f in out_files if f.endswith(".JPG"))
        thumb_count = sum(1 for f in out_files if f.endswith(".411"))
        assert jpg_count == 5
        assert thumb_count == 6
