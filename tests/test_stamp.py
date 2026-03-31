"""Tests for the EXIF metadata stamper."""

import os
import tempfile
from io import BytesIO

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from mavica_tools.stamp import stamp_jpeg, stamp_files, MAVICA_MODELS, TAG_MODEL, TAG_MAKE, TAG_DATETIME


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_jpeg(tmp_dir, name="test.jpg", width=64, height=48):
    """Create a real JPEG file."""
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    path = os.path.join(tmp_dir, name)
    img.save(path, "JPEG")
    return path


class TestStampJpeg:
    def test_stamp_model_shorthand(self, tmp_dir):
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "stamped.jpg")

        ok, result_path, msg = stamp_jpeg(path, out, model="fd7")
        assert ok is True
        assert os.path.exists(out)

        # Verify EXIF
        img = Image.open(out)
        exif = img.getexif()
        assert exif[TAG_MAKE] == "Sony"
        assert exif[TAG_MODEL] == "Sony Mavica MVC-FD7"

    def test_stamp_model_full_name(self, tmp_dir):
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "stamped.jpg")

        ok, _, _ = stamp_jpeg(path, out, model="My Custom Camera")
        assert ok is True

        img = Image.open(out)
        exif = img.getexif()
        assert exif[TAG_MODEL] == "My Custom Camera"

    def test_stamp_date(self, tmp_dir):
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "stamped.jpg")

        ok, _, _ = stamp_jpeg(path, out, date="2001-03-15")
        assert ok is True

        img = Image.open(out)
        exif = img.getexif()
        assert exif[TAG_DATETIME] == "2001:03:15 00:00:00"

    def test_stamp_date_with_time(self, tmp_dir):
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "stamped.jpg")

        ok, _, _ = stamp_jpeg(path, out, date="2001-03-15 14:30:00")
        assert ok is True

        img = Image.open(out)
        exif = img.getexif()
        assert exif[TAG_DATETIME] == "2001:03:15 14:30:00"

    def test_stamp_auto_date(self, tmp_dir):
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "stamped.jpg")

        ok, _, msg = stamp_jpeg(path, out, date="auto")
        assert ok is True
        assert "date=" in msg

        img = Image.open(out)
        exif = img.getexif()
        assert TAG_DATETIME in exif

    def test_stamp_model_and_date(self, tmp_dir):
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "stamped.jpg")

        ok, _, _ = stamp_jpeg(path, out, model="fd88", date="1999-12-25")
        assert ok is True

        img = Image.open(out)
        exif = img.getexif()
        assert exif[TAG_MODEL] == "Sony Mavica MVC-FD88"
        assert exif[TAG_DATETIME] == "1999:12:25 00:00:00"

    def test_stamp_description(self, tmp_dir):
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "stamped.jpg")

        ok, _, _ = stamp_jpeg(path, out, description="Test photo from Mavica FD7")
        assert ok is True

        img = Image.open(out)
        exif = img.getexif()
        assert exif[0x010E] == "Test photo from Mavica FD7"  # ImageDescription

    def test_default_output_path(self, tmp_dir):
        path = make_jpeg(tmp_dir, "photo.jpg")

        ok, result_path, _ = stamp_jpeg(path, model="fd7")
        assert ok is True
        assert result_path.endswith("photo_stamped.jpg")
        assert os.path.exists(result_path)

    def test_overwrite_mode(self, tmp_dir):
        path = make_jpeg(tmp_dir)

        ok, result_path, _ = stamp_jpeg(path, model="fd7", overwrite=True)
        assert ok is True
        assert result_path == path

        img = Image.open(path)
        exif = img.getexif()
        assert exif[TAG_MODEL] == "Sony Mavica MVC-FD7"

    def test_not_a_jpeg(self, tmp_dir):
        path = os.path.join(tmp_dir, "fake.jpg")
        with open(path, "wb") as f:
            f.write(b"not a jpeg")

        ok, _, msg = stamp_jpeg(path, model="fd7")
        assert ok is False

    def test_all_model_shorthands_resolve(self):
        """All shorthand keys should map to valid model names."""
        for key, full_name in MAVICA_MODELS.items():
            assert full_name.startswith("Sony Mavica MVC-")


class TestStampFiles:
    def test_stamp_multiple(self, tmp_dir):
        paths = [
            make_jpeg(tmp_dir, "img1.jpg"),
            make_jpeg(tmp_dir, "img2.jpg"),
        ]
        output_dir = os.path.join(tmp_dir, "stamped")

        stamp_files(paths, output_dir=output_dir, model="fd7", date="2000-01-01")

        assert os.path.exists(os.path.join(output_dir, "img1.jpg"))
        assert os.path.exists(os.path.join(output_dir, "img2.jpg"))
