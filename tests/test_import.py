"""Tests for the quick import command."""

import os
import tempfile

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
        assert exif.get(0x0110) == "Sony Mavica MVC-FD7"  # Model

    def test_import_with_contact_sheet(self, tmp_dir):
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        for i in range(4):
            make_jpeg(src, f"MVC-{i:03d}.JPG")
        out = os.path.join(tmp_dir, "photos")

        result = quick_import(src, out, contact_sheet=True)
        assert result["imported"] == 4
        assert result["contact_sheet"] is not None
        assert os.path.exists(result["contact_sheet"])

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
        """Import + tag + contact sheet in one call."""
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        make_jpeg(src, "MVC-002.JPG")
        out = os.path.join(tmp_dir, "photos")

        result = quick_import(src, out, model="fd88", contact_sheet=True)
        assert result["imported"] == 2
        assert result["tagged"] is True
        assert result["contact_sheet"] is not None
