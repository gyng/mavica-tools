"""Tests for the JPEG health checker."""

import os
import tempfile

import pytest

from mavica_tools.check import check_files, check_jpeg_structure


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def write_file(tmp_dir, name, data):
    path = os.path.join(tmp_dir, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


class TestCheckJpegStructure:
    def test_valid_jpeg_with_markers(self, tmp_dir):
        """A file with proper SOI and EOI markers should pass structural checks."""
        # Minimal valid-ish JPEG structure: SOI + JFIF APP0 + some data + EOI
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 2000 + b"\xff\xd9"
        path = write_file(tmp_dir, "good.jpg", data)
        result = check_jpeg_structure(path)
        assert result["has_soi"] is True
        assert result["has_eoi"] is True
        assert result["size"] == len(data)

    def test_empty_file(self, tmp_dir):
        path = write_file(tmp_dir, "empty.jpg", b"")
        result = check_jpeg_structure(path)
        assert result["valid"] is False
        assert any("empty" in issue.lower() for issue in result["issues"])

    def test_not_a_jpeg(self, tmp_dir):
        path = write_file(tmp_dir, "fake.jpg", b"this is not a jpeg at all")
        result = check_jpeg_structure(path)
        assert result["valid"] is False
        assert result["has_soi"] is False
        assert any("Missing SOI" in issue for issue in result["issues"])

    def test_missing_eoi(self, tmp_dir):
        """JPEG with SOI but no EOI should warn about truncation."""
        data = b"\xff\xd8\xff\xe0" + b"\xab" * 2000
        path = write_file(tmp_dir, "truncated.jpg", data)
        result = check_jpeg_structure(path)
        assert result["has_soi"] is True
        assert result["has_eoi"] is False
        assert any("Missing EOI" in issue for issue in result["issues"])

    def test_zero_byte_run_detection(self, tmp_dir):
        """Large runs of zero bytes (sector failures) should be flagged."""
        data = b"\xff\xd8\xff\xe0" + b"\xab" * 100 + b"\x00" * 600 + b"\xab" * 100 + b"\xff\xd9"
        path = write_file(tmp_dir, "sector_fail.jpg", data)
        result = check_jpeg_structure(path)
        assert any("zero-byte run" in issue for issue in result["issues"])

    def test_small_zero_run_not_flagged(self, tmp_dir):
        """Small runs of zeros (normal in JPEG data) should not be flagged."""
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xab" * 1000 + b"\xff\xd9"
        path = write_file(tmp_dir, "normal.jpg", data)
        result = check_jpeg_structure(path)
        zero_issues = [i for i in result["issues"] if "zero-byte run" in i]
        assert zero_issues == []

    def test_suspiciously_small_file(self, tmp_dir):
        """Files under 1KB should be flagged as suspicious."""
        data = b"\xff\xd8\xff\xe0" + b"\xab" * 50 + b"\xff\xd9"
        path = write_file(tmp_dir, "tiny.jpg", data)
        result = check_jpeg_structure(path)
        assert any("small" in issue.lower() for issue in result["issues"])

    def test_unusual_byte_after_soi(self, tmp_dir):
        """If the byte after SOI isn't FF, it should be noted."""
        data = b"\xff\xd8\x00" + b"\xab" * 2000 + b"\xff\xd9"
        path = write_file(tmp_dir, "odd.jpg", data)
        result = check_jpeg_structure(path)
        assert any("Unusual byte" in issue for issue in result["issues"])

    def test_nonexistent_file(self):
        result = check_jpeg_structure("/nonexistent/path/fake.jpg")
        assert result["valid"] is False
        assert any("Cannot read" in issue for issue in result["issues"])


class TestCheckFiles:
    def test_mixed_files(self, tmp_dir):
        """Check a mix of good and bad files."""
        good = write_file(tmp_dir, "good.jpg", b"\xff\xd8\xff\xe0" + b"\xab" * 2000 + b"\xff\xd9")
        bad = write_file(tmp_dir, "bad.jpg", b"not a jpeg")
        warn = write_file(tmp_dir, "warn.jpg", b"\xff\xd8\xff\xe0" + b"\xab" * 2000)  # no EOI

        results = check_files([good, bad, warn])
        assert len(results) == 3

        # Find each result by path
        good_r = next(r for r in results if r["path"] == good)
        bad_r = next(r for r in results if r["path"] == bad)
        warn_r = next(r for r in results if r["path"] == warn)

        assert good_r["issues"] == [] or good_r["valid"] is True
        assert bad_r["valid"] is False
        # warn file has issues but may still be considered "valid" structurally
        assert len(warn_r["issues"]) > 0
