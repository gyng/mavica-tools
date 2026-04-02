"""Tests for the batch recovery pipeline."""

import os
import struct
import tempfile

import pytest

PIL = pytest.importorskip("PIL")
from io import BytesIO

from PIL import Image

from mavica_tools.fat12 import (
    DATA_START_SECTOR,
    FAT_OFFSET,
    FATS_COUNT,
    SECTOR_SIZE,
    SECTORS_PER_FAT,
)
from mavica_tools.format import create_disk_image
from mavica_tools.recover import recover_from_images


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _make_real_jpeg():
    """Create a real small JPEG."""
    img = Image.new("RGB", (64, 48), color=(200, 100, 50))
    buf = BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def _make_disk_with_jpeg(tmp_dir, jpeg_data):
    """Create a FAT12 disk image with a JPEG embedded (both in FAT and raw)."""
    image = bytearray(create_disk_image("TEST"))

    # Write JPEG data to cluster 2
    cluster = 2
    data_offset = DATA_START_SECTOR * SECTOR_SIZE + (cluster - 2) * SECTOR_SIZE

    # May need multiple sectors
    for i in range(0, len(jpeg_data), SECTOR_SIZE):
        offset = data_offset + i
        chunk = jpeg_data[i : i + SECTOR_SIZE]
        image[offset : offset + len(chunk)] = chunk

    # Write FAT chain
    fat_offset = FAT_OFFSET * SECTOR_SIZE
    clusters_needed = (len(jpeg_data) + SECTOR_SIZE - 1) // SECTOR_SIZE

    for c in range(cluster, cluster + clusters_needed):
        next_cluster = c + 1 if c < cluster + clusters_needed - 1 else 0xFF8
        byte_pos = fat_offset + (c * 3) // 2
        if c % 2 == 0:
            image[byte_pos] = next_cluster & 0xFF
            image[byte_pos + 1] = (image[byte_pos + 1] & 0xF0) | ((next_cluster >> 8) & 0x0F)
        else:
            image[byte_pos] = (image[byte_pos] & 0x0F) | ((next_cluster & 0x0F) << 4)
            image[byte_pos + 1] = (next_cluster >> 4) & 0xFF

    # Copy FAT to FAT2
    fat2_offset = fat_offset + SECTORS_PER_FAT * SECTOR_SIZE
    image[fat2_offset : fat2_offset + SECTORS_PER_FAT * SECTOR_SIZE] = image[
        fat_offset : fat_offset + SECTORS_PER_FAT * SECTOR_SIZE
    ]

    # Write directory entry
    root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
    entry = bytearray(32)
    entry[0:8] = b"MVC-001 "
    entry[8:11] = b"JPG"
    entry[11] = 0x20  # Archive
    struct.pack_into("<H", entry, 26, cluster)
    struct.pack_into("<I", entry, 28, len(jpeg_data))
    image[root_offset : root_offset + 32] = entry

    path = os.path.join(tmp_dir, "pass_01.img")
    with open(path, "wb") as f:
        f.write(image)
    return path


class TestRecoverFromImages:
    def test_full_pipeline_with_fat12(self, tmp_dir):
        """Recovery pipeline should extract via FAT12 and check files."""
        jpeg_data = _make_real_jpeg()
        img_path = _make_disk_with_jpeg(tmp_dir, jpeg_data)
        output_dir = os.path.join(tmp_dir, "recovery")

        summary = recover_from_images([img_path], output_dir, use_fat=True)

        assert summary["total_files"] >= 1
        assert summary["merged_path"] is not None
        assert os.path.exists(summary["merged_path"])

    def test_full_pipeline_carve_fallback(self, tmp_dir):
        """With no-fat, should fall back to JPEG carving."""
        # Create a larger JPEG to survive the MIN_JPEG_SIZE threshold in carver
        img = Image.new("RGB", (320, 240), color=(200, 100, 50))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=95)
        jpeg_data = buf.getvalue()

        # Write JPEG directly into a raw disk image (not via FAT12)
        # so the carver can find it by markers
        from mavica_tools.multipass import DISK_SIZE

        disk = bytearray(DISK_SIZE)
        # Place JPEG after boot sector area
        offset = 33 * SECTOR_SIZE
        disk[offset : offset + len(jpeg_data)] = jpeg_data

        img_path = os.path.join(tmp_dir, "pass_01.img")
        with open(img_path, "wb") as f:
            f.write(disk)

        output_dir = os.path.join(tmp_dir, "recovery")
        summary = recover_from_images([img_path], output_dir, use_fat=False)

        assert summary["extraction_method"] == "carve"
        assert summary["total_files"] >= 1

    def test_empty_disk_image(self, tmp_dir):
        """An empty disk should produce no files."""
        image = create_disk_image()
        img_path = os.path.join(tmp_dir, "pass_01.img")
        with open(img_path, "wb") as f:
            f.write(image)

        output_dir = os.path.join(tmp_dir, "recovery")
        summary = recover_from_images([img_path], output_dir)

        assert summary["total_files"] == 0

    def test_creates_output_directory(self, tmp_dir):
        jpeg_data = _make_real_jpeg()
        img_path = _make_disk_with_jpeg(tmp_dir, jpeg_data)
        output_dir = os.path.join(tmp_dir, "nested", "recovery")

        recover_from_images([img_path], output_dir)
        assert os.path.isdir(output_dir)


class TestRecoverFromFixtures:
    """Recovery tests using real Mavica disk image fixtures."""

    def test_recover_from_fixture_disk_image(self, tmp_dir, fixture_disk_image):
        """FAT12 recovery from good disk image should extract all files."""
        output_dir = os.path.join(tmp_dir, "recovery")
        summary = recover_from_images([fixture_disk_image], output_dir, use_fat=True)

        assert summary["total_files"] >= 5  # at least 5 JPEGs
        assert summary["merged_path"] is not None

    def test_carve_from_fixture_disk_image(self, tmp_dir, fixture_disk_image):
        """JPEG carving from good disk image should find all 5 photos."""
        output_dir = os.path.join(tmp_dir, "recovery")
        summary = recover_from_images([fixture_disk_image], output_dir, use_fat=False)

        assert summary["extraction_method"] == "carve"
        assert summary["total_files"] >= 5

    def test_recover_from_bad_sectors_disk(self, tmp_dir):
        """Recovery from disk with zeroed sectors should still extract files."""
        from mavica_tools.check import check_jpeg_structure
        from mavica_tools.fat12 import extract_with_names

        bad_disk = os.path.join(os.path.dirname(__file__), "fixtures", "disk_bad_sectors.img")
        output_dir = os.path.join(tmp_dir, "extracted")
        results = extract_with_names(bad_disk, output_dir)

        assert len(results) == 11  # all files still extractable

        # Find the damaged JPEG (MVC-006F.JPG) and check it
        for name, path, _size, _deleted in results:
            if name == "MVC-006F.JPG":
                check = check_jpeg_structure(path)
                assert any("zero-byte" in issue for issue in check["issues"])
                break
        else:
            pytest.fail("MVC-006F.JPG not found in extracted files")

    def test_recover_from_truncated_disk(self, tmp_dir):
        """Recovery from disk with truncated JPEG data."""
        from mavica_tools.check import check_jpeg_structure
        from mavica_tools.fat12 import extract_with_names

        trunc_disk = os.path.join(os.path.dirname(__file__), "fixtures", "disk_truncated.img")
        output_dir = os.path.join(tmp_dir, "extracted")
        results = extract_with_names(trunc_disk, output_dir)

        # MVC-002F.JPG should be extracted but damaged
        for name, path, _size, _deleted in results:
            if name == "MVC-002F.JPG":
                check = check_jpeg_structure(path)
                assert len(check["issues"]) > 0  # should have issues
                break
        else:
            pytest.fail("MVC-002F.JPG not found in extracted files")
