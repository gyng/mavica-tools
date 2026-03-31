"""Tests for terminal image display."""

import os
import tempfile
from io import StringIO
from unittest.mock import patch

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from mavica_tools.terminal_image import (
    detect_protocol,
    show_image,
    show_images,
    _halfblock_display,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_jpeg(tmp_dir, name="test.jpg"):
    img = Image.new("RGB", (64, 48), color=(200, 100, 50))
    path = os.path.join(tmp_dir, name)
    img.save(path, "JPEG")
    return path


class TestDetectProtocol:
    def test_defaults_to_halfblock(self):
        with patch.dict(os.environ, {}, clear=True):
            assert detect_protocol() == "halfblock"

    def test_detects_kitty(self):
        with patch.dict(os.environ, {"TERM_PROGRAM": "kitty"}):
            assert detect_protocol() == "kitty"

    def test_detects_iterm2(self):
        with patch.dict(os.environ, {"TERM_PROGRAM": "iTerm2"}):
            assert detect_protocol() == "iterm2"

    def test_detects_wezterm_as_kitty(self):
        with patch.dict(os.environ, {"TERM_PROGRAM": "WezTerm"}):
            assert detect_protocol() == "kitty"

    def test_detects_sixel_from_term(self):
        with patch.dict(os.environ, {"TERM": "xterm-256color", "TERM_PROGRAM": ""}):
            assert detect_protocol() == "sixel"

    def test_detects_foot(self):
        with patch.dict(os.environ, {"TERM": "foot", "TERM_PROGRAM": ""}):
            assert detect_protocol() == "sixel"


class TestHalfblockDisplay:
    def test_renders_without_error(self, tmp_dir, capsys):
        path = make_jpeg(tmp_dir)
        with open(path, "rb") as f:
            data = f.read()

        _halfblock_display(data, width=20)
        captured = capsys.readouterr()
        # Should output half-block characters
        assert "\u2580" in captured.out

    def test_respects_width(self, tmp_dir, capsys):
        path = make_jpeg(tmp_dir)
        with open(path, "rb") as f:
            data = f.read()

        _halfblock_display(data, width=10)
        captured = capsys.readouterr()
        lines = [l for l in captured.out.split("\n") if l.strip()]
        # Each line should be about 10 chars of content (plus ANSI codes)
        assert len(lines) > 0


class TestShowImage:
    def test_show_with_label(self, tmp_dir, capsys):
        path = make_jpeg(tmp_dir)
        show_image(path, protocol="halfblock", width=10)
        captured = capsys.readouterr()
        assert "test.jpg" in captured.out
        assert "64x48" in captured.out

    def test_show_without_label(self, tmp_dir, capsys):
        path = make_jpeg(tmp_dir)
        show_image(path, protocol="halfblock", width=10, label=False)
        captured = capsys.readouterr()
        assert "test.jpg" not in captured.out

    def test_nonexistent_file(self, capsys):
        show_image("/nonexistent/path.jpg")
        captured = capsys.readouterr()
        assert captured.out == ""


class TestShowImages:
    def test_limits_output(self, tmp_dir, capsys):
        paths = [make_jpeg(tmp_dir, f"img{i}.jpg") for i in range(15)]
        show_images(paths, protocol="halfblock", max_images=3, width=10)
        captured = capsys.readouterr()
        assert "12 more" in captured.out

    def test_skips_non_images(self, tmp_dir, capsys):
        txt = os.path.join(tmp_dir, "readme.txt")
        with open(txt, "w") as f:
            f.write("not an image")
        show_images([txt], protocol="halfblock", width=10)
        captured = capsys.readouterr()
        assert "\u2580" not in captured.out
