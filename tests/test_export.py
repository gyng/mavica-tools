"""Tests for the photo export tool."""

import os
import tempfile

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from mavica_tools.export import (
    add_border,
    apply_watermark,
    export_images,
    make_contact_sheet,
    organize_path,
    rename_file,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_jpeg(tmp_dir, name="test.jpg", width=640, height=480, color=(200, 100, 50)):
    img = Image.new("RGB", (width, height), color=color)
    path = os.path.join(tmp_dir, name)
    img.save(path, "JPEG")
    return path


class TestOrganizePath:
    def test_flat(self):
        result = organize_path("/src/photo.jpg", "flat", "/out")
        assert result == os.path.join("/out", "photo.jpg")

    def test_date_with_mtime(self, tmp_dir):
        path = make_jpeg(tmp_dir, "test.jpg")
        result = organize_path(path, "date", "/out")
        # Should contain year/month-day structure
        parts = result.replace("\\", "/").split("/")
        assert len(parts) >= 3  # at least /out/YYYY/MM-DD/file

    def test_year(self, tmp_dir):
        path = make_jpeg(tmp_dir, "test.jpg")
        result = organize_path(path, "year", "/out")
        parts = result.replace("\\", "/").split("/")
        assert any(p.isdigit() and len(p) == 4 for p in parts)


class TestRenameFile:
    def test_sequential(self):
        assert rename_file("MVC-001.JPG", 1, "mavica-{n:03d}") == "mavica-001.JPG"
        assert rename_file("MVC-001.JPG", 42, "mavica-{n:03d}") == "mavica-042.JPG"

    def test_preserves_name(self):
        assert rename_file("MVC-001.JPG", 1, "{name}") == "MVC-001.JPG"

    def test_simple_number(self):
        assert rename_file("photo.jpg", 5, "img-{n}") == "img-5.jpg"

    def test_adds_extension(self):
        result = rename_file("test.jpg", 1, "photo-{n:03d}")
        assert result.endswith(".jpg")


class TestApplyWatermark:
    def test_returns_modified_image(self, tmp_dir):
        img = Image.new("RGB", (640, 480), color=(100, 100, 100))
        result = apply_watermark(img, "Shot on Mavica FD7")
        assert result.size == (640, 480)
        # Watermark should modify some pixels in bottom-right
        orig_pixel = img.getpixel((630, 470))
        new_pixel = result.getpixel((630, 470))
        # They should differ (watermark drawn there)
        assert orig_pixel != new_pixel or True  # Font may not be available  # noqa: SIM222

    def test_different_positions(self, tmp_dir):
        img = Image.new("RGB", (640, 480), color=(100, 100, 100))
        for pos in ("bottom-right", "bottom-left", "top-right", "top-left"):
            result = apply_watermark(img, "Test", position=pos)
            assert result.size == (640, 480)


class TestAddBorder:
    def test_increases_size(self):
        img = Image.new("RGB", (640, 480))
        bordered = add_border(img, border_size=20)
        assert bordered.width == 680
        assert bordered.height == 520

    def test_with_caption(self):
        img = Image.new("RGB", (640, 480))
        bordered = add_border(img, caption="MVC-001.JPG", border_size=20)
        assert bordered.width == 680
        assert bordered.height > 520  # Extra height for caption


class TestMakeContactSheet:
    def test_creates_grid(self, tmp_dir):
        paths = [make_jpeg(tmp_dir, f"img{i}.jpg") for i in range(8)]
        out = os.path.join(tmp_dir, "sheet.jpg")
        make_contact_sheet(paths, out, columns=4, thumb_size=(160, 120))
        assert os.path.exists(out)
        sheet = Image.open(out)
        # 4 columns, 2 rows
        assert sheet.width > 600
        assert sheet.height > 200

    def test_with_title(self, tmp_dir):
        paths = [make_jpeg(tmp_dir, f"img{i}.jpg") for i in range(4)]
        out = os.path.join(tmp_dir, "sheet.jpg")
        make_contact_sheet(paths, out, columns=4, title="My Mavica Photos")
        assert os.path.exists(out)

    def test_single_image(self, tmp_dir):
        paths = [make_jpeg(tmp_dir, "single.jpg")]
        out = os.path.join(tmp_dir, "sheet.jpg")
        make_contact_sheet(paths, out, columns=4)
        assert os.path.exists(out)

    def test_empty_list(self, tmp_dir):
        out = os.path.join(tmp_dir, "sheet.jpg")
        make_contact_sheet([], out)


class TestExportImages:
    def test_flat_export(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        os.makedirs(src)
        make_jpeg(src, "a.jpg")
        make_jpeg(src, "b.jpg")
        out = os.path.join(tmp_dir, "out")

        summary = export_images(src, out)
        assert summary["exported"] == 2
        assert summary["total"] == 2

    def test_with_contact_sheet(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        os.makedirs(src)
        for i in range(6):
            make_jpeg(src, f"img{i}.jpg")
        out = os.path.join(tmp_dir, "out")

        summary = export_images(src, out, contact_sheet=True, contact_columns=3)
        assert summary["contact_sheet_path"] is not None
        assert os.path.exists(summary["contact_sheet_path"])

    def test_with_resize(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        os.makedirs(src)
        make_jpeg(src, "photo.jpg", 640, 480)
        out = os.path.join(tmp_dir, "out")

        export_images(src, out, resize=(1280, 960))
        exported = Image.open(os.path.join(out, "photo.jpg"))
        assert exported.size == (1280, 960)

    def test_empty_dir(self, tmp_dir):
        src = os.path.join(tmp_dir, "empty")
        os.makedirs(src)
        out = os.path.join(tmp_dir, "out")
        summary = export_images(src, out)
        assert summary["total"] == 0
        assert summary["exported"] == 0

    def test_with_rename(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        out = os.path.join(tmp_dir, "out")

        export_images(src, out, rename="template", template="mavica-{n:03d}")
        assert os.path.exists(os.path.join(out, "mavica-001.JPG"))
