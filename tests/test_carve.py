"""Tests for the JPEG carver."""

import os
import tempfile

import pytest

from mavica_tools.carve import MIN_JPEG_SIZE, carve_jpegs, find_jpegs


def make_fake_jpeg(size=2048):
    """Create a fake JPEG byte sequence (valid markers, deterministic body).

    Uses 0xAB fill to avoid accidental FF D8 FF or FF D9 sequences in the body,
    which would confuse the carver.
    """
    body_size = size - 4  # account for SOI (2) + EOI (2), plus FF after SOI
    if body_size < 2:
        body_size = 2
    # FF D8 FF E0 ... FF D9
    return b"\xff\xd8\xff\xe0" + b"\xab" * (body_size - 2) + b"\xff\xd9"


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestFindJpegs:
    def test_no_jpegs_in_random_data(self):
        # Random data unlikely to contain FF D8 FF ... FF D9 with 1KB+ between
        data = bytes(range(256)) * 10
        result = find_jpegs(data)
        assert result == []

    def test_single_jpeg(self):
        padding = b"\x00" * 100
        jpeg = make_fake_jpeg(2048)
        data = padding + jpeg + padding
        results = find_jpegs(data)
        assert len(results) == 1
        offset, length, truncated = results[0]
        assert offset == 100
        assert length == 2048
        assert truncated is False

    def test_two_jpegs(self):
        jpeg1 = make_fake_jpeg(2048)
        gap = b"\x00" * 500
        jpeg2 = make_fake_jpeg(3000)
        data = jpeg1 + gap + jpeg2
        results = find_jpegs(data)
        assert len(results) == 2
        assert results[0][0] == 0
        assert results[0][1] == 2048
        assert results[1][0] == 2048 + 500
        assert results[1][1] == 3000

    def test_truncated_jpeg_no_eoi(self):
        # JPEG with SOI but no EOI (use 0xAB fill to avoid accidental markers)
        body = b"\xab" * 2000
        data = b"\xff\xd8\xff\xe0" + body
        results = find_jpegs(data)
        assert len(results) == 1
        offset, length, truncated = results[0]
        assert offset == 0
        assert truncated is True

    def test_too_small_jpeg_ignored(self):
        # JPEG smaller than MIN_JPEG_SIZE
        small_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"\xff\xd9"
        assert len(small_jpeg) < MIN_JPEG_SIZE
        data = b"\x00" * 100 + small_jpeg + b"\x00" * 100
        results = find_jpegs(data)
        assert results == []

    def test_jpeg_at_start_of_data(self):
        jpeg = make_fake_jpeg(2048)
        results = find_jpegs(jpeg)
        assert len(results) == 1
        assert results[0][0] == 0

    def test_empty_data(self):
        assert find_jpegs(b"") == []

    def test_just_markers(self):
        # Just SOI + EOI, too small
        data = b"\xff\xd8\xff\xd9"
        assert find_jpegs(data) == []


class TestCarveJpegs:
    def test_carve_single_jpeg(self, tmp_dir):
        # Create a disk image with one embedded JPEG
        jpeg = make_fake_jpeg(4096)
        disk_data = b"\x00" * 512 + jpeg + b"\x00" * 512
        img_path = os.path.join(tmp_dir, "disk.img")
        with open(img_path, "wb") as f:
            f.write(disk_data)

        output_dir = os.path.join(tmp_dir, "carved")
        extracted = carve_jpegs(img_path, output_dir)

        assert len(extracted) == 1
        assert os.path.exists(extracted[0])
        with open(extracted[0], "rb") as f:
            recovered = f.read()
        assert recovered == jpeg

    def test_carve_multiple_jpegs(self, tmp_dir):
        jpeg1 = make_fake_jpeg(2048)
        jpeg2 = make_fake_jpeg(3072)
        disk_data = jpeg1 + b"\x00" * 1024 + jpeg2
        img_path = os.path.join(tmp_dir, "disk.img")
        with open(img_path, "wb") as f:
            f.write(disk_data)

        output_dir = os.path.join(tmp_dir, "carved")
        extracted = carve_jpegs(img_path, output_dir)
        assert len(extracted) == 2

    def test_carve_empty_image(self, tmp_dir):
        img_path = os.path.join(tmp_dir, "empty.img")
        with open(img_path, "wb") as f:
            f.write(b"\x00" * 1024)

        output_dir = os.path.join(tmp_dir, "carved")
        extracted = carve_jpegs(img_path, output_dir)
        assert extracted == []

    def test_carve_truncated_jpeg(self, tmp_dir):
        # JPEG without EOI
        body = b"\xab" * 2000
        jpeg_no_eoi = b"\xff\xd8\xff\xe0" + body
        disk_data = b"\x00" * 100 + jpeg_no_eoi
        img_path = os.path.join(tmp_dir, "disk.img")
        with open(img_path, "wb") as f:
            f.write(disk_data)

        output_dir = os.path.join(tmp_dir, "carved")
        extracted = carve_jpegs(img_path, output_dir)
        assert len(extracted) == 1
        assert "TRUNCATED" in os.path.basename(extracted[0])

    def test_output_dir_created(self, tmp_dir):
        jpeg = make_fake_jpeg(2048)
        img_path = os.path.join(tmp_dir, "disk.img")
        with open(img_path, "wb") as f:
            f.write(jpeg)

        output_dir = os.path.join(tmp_dir, "new_dir", "nested")
        carve_jpegs(img_path, output_dir)
        assert os.path.isdir(output_dir)
