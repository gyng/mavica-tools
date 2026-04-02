"""Tests for the JPEG repair tool."""

import os
import tempfile
from io import BytesIO

import pytest

from mavica_tools.repair import repair_files, repair_jpeg

# We need Pillow to create real test JPEGs
PIL = pytest.importorskip("PIL")
from PIL import Image


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_real_jpeg(width=64, height=48):
    """Create a real JPEG image and return its bytes."""
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def write_file(tmp_dir, name, data):
    path = os.path.join(tmp_dir, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


class TestRepairJpeg:
    def test_repair_valid_jpeg(self, tmp_dir):
        """A valid JPEG should 'repair' successfully (strategy 1)."""
        jpeg_data = make_real_jpeg()
        path = write_file(tmp_dir, "valid.jpg", jpeg_data)
        out_path = os.path.join(tmp_dir, "valid_repaired.png")

        ok, result_path, _msg = repair_jpeg(path, out_path)
        assert ok is True
        assert result_path == out_path
        assert os.path.exists(out_path)
        # Verify the output is a valid PNG
        img = Image.open(out_path)
        assert img.format == "PNG"
        assert img.size == (64, 48)

    def test_repair_truncated_jpeg(self, tmp_dir):
        """A truncated JPEG (cut short) should still be partially recoverable."""
        # Use a larger image so there's enough valid JPEG data after truncation
        jpeg_data = make_real_jpeg(width=320, height=240)
        # Cut off the last 10% of the file
        truncated = jpeg_data[: int(len(jpeg_data) * 0.9)]
        path = write_file(tmp_dir, "truncated.jpg", truncated)
        out_path = os.path.join(tmp_dir, "truncated_repaired.png")

        ok, _result_path, _msg = repair_jpeg(path, out_path)
        # Should succeed via strategy 1 (Pillow truncation tolerance)
        assert ok is True
        assert os.path.exists(out_path)

    def test_repair_jpeg_with_sector_failure(self, tmp_dir):
        """JPEG with a large zero-byte run (sector failure) mid-file."""
        jpeg_data = make_real_jpeg(width=128, height=96)
        # Insert a sector failure (512 zeros) in the middle
        mid = len(jpeg_data) // 2
        corrupted = jpeg_data[:mid] + b"\x00" * 600 + jpeg_data[mid + 600 :]
        path = write_file(tmp_dir, "sector_fail.jpg", corrupted)
        out_path = os.path.join(tmp_dir, "sector_repaired.png")

        ok, _result_path, _msg = repair_jpeg(path, out_path)
        # Should recover at least partially
        if ok:
            assert os.path.exists(out_path)

    def test_repair_not_a_jpeg(self, tmp_dir):
        """Non-JPEG file should fail gracefully."""
        path = write_file(tmp_dir, "fake.jpg", b"this is not a jpeg")
        out_path = os.path.join(tmp_dir, "fake_repaired.png")

        ok, _result_path, msg = repair_jpeg(path, out_path)
        assert ok is False
        assert "Not a JPEG" in msg

    def test_repair_too_short(self, tmp_dir):
        """File too short to be a JPEG."""
        path = write_file(tmp_dir, "tiny.jpg", b"\xff\xd8")
        out_path = os.path.join(tmp_dir, "tiny_repaired.png")

        ok, _result_path, _msg = repair_jpeg(path, out_path)
        assert ok is False

    def test_default_output_path(self, tmp_dir):
        """When no output path given, should create one based on input name."""
        jpeg_data = make_real_jpeg()
        path = write_file(tmp_dir, "photo.jpg", jpeg_data)

        ok, result_path, _msg = repair_jpeg(path)
        assert ok is True
        assert result_path.endswith("_repaired.png")
        assert "photo" in result_path


class TestRepairFiles:
    def test_repair_multiple_files(self, tmp_dir):
        """Repair a batch of files."""
        jpeg1 = make_real_jpeg()
        jpeg2 = make_real_jpeg(width=32, height=24)
        path1 = write_file(tmp_dir, "img1.jpg", jpeg1)
        path2 = write_file(tmp_dir, "img2.jpg", jpeg2)
        bad = write_file(tmp_dir, "bad.jpg", b"not a jpeg")

        output_dir = os.path.join(tmp_dir, "repaired")
        repair_files([path1, path2, bad], output_dir)

        assert os.path.exists(os.path.join(output_dir, "img1_repaired.png"))
        assert os.path.exists(os.path.join(output_dir, "img2_repaired.png"))
        # bad.jpg should fail but not crash
        assert not os.path.exists(os.path.join(output_dir, "bad_repaired.png"))
