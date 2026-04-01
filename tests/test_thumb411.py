"""Tests for .411 Mavica thumbnail decoder."""

import os
import tempfile

import pytest

PIL = pytest.importorskip("PIL")

from mavica_tools.thumb411 import (
    THUMB_HEIGHT,
    THUMB_SIZE,
    THUMB_WIDTH,
    convert_411,
    decode_411,
    decode_411_to_image,
)


def make_411(directory: str, name: str = "MVC-001.411") -> str:
    """Create a fake .411 file with valid size (4608 bytes)."""
    path = os.path.join(directory, name)
    # Generate synthetic YCbCr 4:1:1 data:
    # 6 bytes per 4-pixel group, 64*48/4 = 768 groups
    data = bytearray()
    for i in range(768):
        # Y0, Y1, Y2, Y3, Cb, Cr — mid-gray with neutral chroma
        data.extend([128, 128, 128, 128, 128, 128])
    with open(path, "wb") as f:
        f.write(data)
    return path


class TestDecode411:
    def test_decode_correct_pixel_count(self):
        data = bytes([128] * THUMB_SIZE)
        pixels = decode_411(data)
        assert len(pixels) == THUMB_WIDTH * THUMB_HEIGHT

    def test_decode_wrong_size_raises(self):
        with pytest.raises(ValueError, match="Expected 4608"):
            decode_411(b"\x00" * 100)

    def test_decode_black(self):
        # Y=0, Cb=128, Cr=128 → black (R=0, G=0, B=0)
        data = bytearray()
        for _ in range(768):
            data.extend([0, 0, 0, 0, 128, 128])
        pixels = decode_411(bytes(data))
        assert pixels[0] == (0, 0, 0)

    def test_decode_white(self):
        # Y=255, Cb=128, Cr=128 → white (R=255, G=255, B=255)
        data = bytearray()
        for _ in range(768):
            data.extend([255, 255, 255, 255, 128, 128])
        pixels = decode_411(bytes(data))
        assert pixels[0] == (255, 255, 255)

    def test_pixel_values_clamped(self):
        # Extreme chroma values should still produce valid 0-255 pixels
        data = bytearray()
        for _ in range(768):
            data.extend([200, 200, 200, 200, 0, 255])
        pixels = decode_411(bytes(data))
        for r, g, b in pixels:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255


class TestDecode411ToImage:
    def test_returns_pil_image(self):
        with tempfile.TemporaryDirectory() as d:
            path = make_411(d)
            img = decode_411_to_image(path)
            assert img.size == (THUMB_WIDTH, THUMB_HEIGHT)
            assert img.mode == "RGB"


class TestConvert411:
    def test_convert_to_png(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_411(d)
            out = convert_411(src, fmt="PNG")
            assert out.endswith(".png")
            assert os.path.exists(out)
            from PIL import Image

            img = Image.open(out)
            assert img.size == (64, 48)
            img.close()

    def test_convert_to_jpeg(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_411(d)
            out = convert_411(src, fmt="JPEG")
            assert out.endswith(".jpeg")
            assert os.path.exists(out)

    def test_convert_custom_dest(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_411(d)
            dest = os.path.join(d, "output", "thumb.png")
            os.makedirs(os.path.dirname(dest))
            out = convert_411(src, dest=dest, fmt="PNG")
            assert out == dest
            assert os.path.exists(dest)


class TestGatherMavicaFiles:
    def test_gathers_411_files(self):
        from mavica_tools.utils import gather_mavica_files

        with tempfile.TemporaryDirectory() as d:
            make_411(d, "MVC-001.411")
            # Also create a JPEG
            from PIL import Image

            img = Image.new("RGB", (10, 10))
            img.save(os.path.join(d, "MVC-001.JPG"), "JPEG")

            files = gather_mavica_files(d)
            extensions = {os.path.splitext(f)[1].lower() for f in files}
            assert ".411" in extensions
            assert ".jpg" in extensions
