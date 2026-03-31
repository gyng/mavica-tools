"""Tests for the EXIF metadata stamper."""

import os
import tempfile
from io import BytesIO

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from mavica_tools.stamp import (
    stamp_jpeg, stamp_files, MAVICA_MODELS, MAVICA_SPECS,
    TAG_MODEL, TAG_MAKE, TAG_DATETIME, TAG_EXIF_IFD,
    TAG_FOCAL_LENGTH, TAG_FOCAL_LENGTH_35MM, TAG_FNUMBER, TAG_ISO,
    TAG_COLOR_SPACE, TAG_PIXEL_X, TAG_PIXEL_Y, TAG_FLASH,
)


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

    def test_stamp_writes_camera_specs_exif(self, tmp_dir):
        """Stamping with a known model should write focal length, aperture, ISO."""
        path = make_jpeg(tmp_dir)
        out = os.path.join(tmp_dir, "specs.jpg")

        ok, _, _ = stamp_jpeg(path, out, model="fd7")
        assert ok is True

        img = Image.open(out)
        exif = img.getexif()
        exif_ifd = exif.get_ifd(TAG_EXIF_IFD)

        # FD7 specs: f=4.2mm, F2.0, ISO 100, 640x480
        assert TAG_FOCAL_LENGTH in exif_ifd
        fl = exif_ifd[TAG_FOCAL_LENGTH]
        assert fl[0] / fl[1] == pytest.approx(4.2, abs=0.1)

        assert exif_ifd[TAG_FOCAL_LENGTH_35MM] == 47
        assert TAG_FNUMBER in exif_ifd
        fn = exif_ifd[TAG_FNUMBER]
        assert fn[0] / fn[1] == pytest.approx(2.0, abs=0.1)

        assert exif_ifd[TAG_ISO] == 100
        assert exif_ifd[TAG_COLOR_SPACE] == 1  # sRGB
        assert exif_ifd[TAG_PIXEL_X] == 640
        assert exif_ifd[TAG_PIXEL_Y] == 480

    def test_stamp_specs_vary_by_model(self, tmp_dir):
        """Different models should produce different EXIF specs."""
        path = make_jpeg(tmp_dir)
        out7 = os.path.join(tmp_dir, "fd7.jpg")
        out200 = os.path.join(tmp_dir, "fd200.jpg")

        stamp_jpeg(path, out7, model="fd7")
        stamp_jpeg(path, out200, model="fd200")

        exif7 = Image.open(out7).getexif().get_ifd(TAG_EXIF_IFD)
        exif200 = Image.open(out200).getexif().get_ifd(TAG_EXIF_IFD)

        # FD7: 47mm equiv, FD200: 37mm equiv
        assert exif7[TAG_FOCAL_LENGTH_35MM] == 47
        assert exif200[TAG_FOCAL_LENGTH_35MM] == 37

        # FD7: 640x480, FD200: 1600x1200
        assert exif7[TAG_PIXEL_X] == 640
        assert exif200[TAG_PIXEL_X] == 1600

    def test_mavica_specs_completeness(self):
        """All MAVICA_SPECS entries should have required fields."""
        required = {"model", "focal_length_mm", "focal_length_35mm", "aperture_max", "iso", "resolution"}
        for key, specs in MAVICA_SPECS.items():
            for field in required:
                assert field in specs, f"{key} missing {field}"


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
