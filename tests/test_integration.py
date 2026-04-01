"""Integration tests — end-to-end pipelines.

Tests the full recovery workflow: create disk image → carve → check → repair → stamp.
"""

import os
import struct
import tempfile

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image
from io import BytesIO

from mavica_tools.format import create_disk_image
from mavica_tools.fat12 import (
    FAT_OFFSET, FATS_COUNT, SECTORS_PER_FAT, ROOT_DIR_ENTRIES,
    DATA_START_SECTOR, SECTOR_SIZE, extract_with_names, list_files,
)
from mavica_tools.multipass import merge_passes
from mavica_tools.carve import carve_jpegs
from mavica_tools.check import check_jpeg_structure
from mavica_tools.repair import repair_jpeg
from mavica_tools.stamp import stamp_jpeg
from mavica_tools.importcmd import quick_import


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _make_real_jpeg(width=640, height=480):
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _embed_jpeg_in_disk(disk: bytearray, jpeg_data: bytes, cluster: int = 2):
    """Write JPEG data into a FAT12 disk image at the given cluster."""
    clusters_needed = (len(jpeg_data) + SECTOR_SIZE - 1) // SECTOR_SIZE

    # Write data sectors
    for i in range(clusters_needed):
        offset = (DATA_START_SECTOR + (cluster - 2) + i) * SECTOR_SIZE
        chunk = jpeg_data[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE]
        disk[offset : offset + len(chunk)] = chunk

    # Write FAT chain
    fat_offset = FAT_OFFSET * SECTOR_SIZE
    for c in range(cluster, cluster + clusters_needed):
        next_c = c + 1 if c < cluster + clusters_needed - 1 else 0xFF8
        byte_pos = fat_offset + (c * 3) // 2
        if c % 2 == 0:
            disk[byte_pos] = next_c & 0xFF
            disk[byte_pos + 1] = (disk[byte_pos + 1] & 0xF0) | ((next_c >> 8) & 0x0F)
        else:
            disk[byte_pos] = (disk[byte_pos] & 0x0F) | ((next_c & 0x0F) << 4)
            disk[byte_pos + 1] = (next_c >> 4) & 0xFF

    # Copy FAT to FAT2
    fat2_offset = fat_offset + SECTORS_PER_FAT * SECTOR_SIZE
    disk[fat2_offset : fat2_offset + SECTORS_PER_FAT * SECTOR_SIZE] = (
        disk[fat_offset : fat_offset + SECTORS_PER_FAT * SECTOR_SIZE]
    )

    # Write directory entry
    root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
    entry = bytearray(32)
    entry[0:8] = b"MVC-001 "
    entry[8:11] = b"JPG"
    entry[11] = 0x20
    struct.pack_into("<H", entry, 26, cluster)
    struct.pack_into("<I", entry, 28, len(jpeg_data))
    disk[root_offset : root_offset + 32] = entry

    return disk


class TestEndToEndRecovery:
    """Full pipeline: disk image → extract → check → stamp."""

    def test_fat12_extract_check_stamp(self, tmp_dir):
        """Create disk with JPEG → extract via FAT12 → check → stamp."""
        jpeg_data = _make_real_jpeg()
        disk = bytearray(create_disk_image("TEST"))
        _embed_jpeg_in_disk(disk, jpeg_data)

        img_path = os.path.join(tmp_dir, "disk.img")
        with open(img_path, "wb") as f:
            f.write(disk)

        # Extract
        extract_dir = os.path.join(tmp_dir, "extracted")
        results = extract_with_names(img_path, extract_dir)
        assert len(results) == 1
        name, path, size, deleted = results[0]
        assert name == "MVC-001.JPG"

        # Check
        check_result = check_jpeg_structure(path)
        assert check_result["has_soi"] is True

        # Stamp
        ok, stamped_path, msg = stamp_jpeg(path, model="fd7", date="2001-07-04", overwrite=True)
        assert ok is True

        # Verify EXIF
        img = Image.open(path)
        exif = img.getexif()
        assert exif[0x0110] == "SONY MAVICA MVC-FD7"

    def test_carve_check_repair_pipeline(self, tmp_dir):
        """Carve from raw → check → repair truncated."""
        # Create a truncated JPEG embedded in a disk image
        jpeg_data = _make_real_jpeg()
        truncated = jpeg_data[:int(len(jpeg_data) * 0.7)]  # Cut 30%

        from mavica_tools.multipass import DISK_SIZE
        disk = bytearray(DISK_SIZE)
        offset = DATA_START_SECTOR * SECTOR_SIZE
        disk[offset : offset + len(truncated)] = truncated

        img_path = os.path.join(tmp_dir, "disk.img")
        with open(img_path, "wb") as f:
            f.write(disk)

        # Carve
        carved_dir = os.path.join(tmp_dir, "carved")
        carved = carve_jpegs(img_path, carved_dir)
        assert len(carved) >= 1

        # Check — should find issues
        result = check_jpeg_structure(carved[0])
        assert len(result["issues"]) > 0  # Should be damaged

        # Repair
        repaired_path = os.path.join(tmp_dir, "repaired.png")
        ok, rpath, msg = repair_jpeg(carved[0], repaired_path)
        # May or may not succeed depending on truncation point
        if ok:
            assert os.path.exists(rpath)

    def test_multipass_merge_carve(self, tmp_dir):
        """Multiple disk images → merge → carve."""
        jpeg_data = _make_real_jpeg()
        from mavica_tools.multipass import DISK_SIZE

        # Create two "passes" — one with data, one with some zeros
        pass1 = bytearray(DISK_SIZE)
        offset = DATA_START_SECTOR * SECTOR_SIZE
        pass1[offset : offset + len(jpeg_data)] = jpeg_data

        pass2 = bytearray(pass1)  # Copy — same data

        p1_path = os.path.join(tmp_dir, "pass_01.img")
        p2_path = os.path.join(tmp_dir, "pass_02.img")
        with open(p1_path, "wb") as f:
            f.write(pass1)
        with open(p2_path, "wb") as f:
            f.write(pass2)

        # Merge
        merged, status = merge_passes([p1_path, p2_path])
        assert len(merged) == DISK_SIZE

        # Write merged
        merged_path = os.path.join(tmp_dir, "merged.img")
        with open(merged_path, "wb") as f:
            f.write(merged)

        # Carve
        carved_dir = os.path.join(tmp_dir, "carved")
        carved = carve_jpegs(merged_path, carved_dir)
        assert len(carved) >= 1

    def test_quick_import_full_pipeline(self, tmp_dir):
        """Quick import from directory → tag → contact sheet."""
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)

        # Create real JPEGs
        for i in range(3):
            img = Image.new("RGB", (640, 480), color=(100 + i * 50, 50, 25))
            img.save(os.path.join(src, f"MVC-{i:03d}.JPG"), "JPEG")

        out = os.path.join(tmp_dir, "photos")
        result = quick_import(src, out, model="fd7", contact_sheet=True)

        assert result["imported"] == 3
        assert result["tagged"] is True
        assert result["contact_sheet"] is not None
        assert os.path.exists(result["contact_sheet"])

        # Verify EXIF on an imported file
        img = Image.open(result["files"][0])
        exif = img.getexif()
        assert "SONY" in exif.get(0x010F, "")


class TestEdgeCases:
    """Edge cases that could break core functionality."""

    def test_zero_byte_jpeg(self, tmp_dir):
        """A zero-byte file should not crash check or repair."""
        path = os.path.join(tmp_dir, "empty.jpg")
        with open(path, "wb") as f:
            pass
        result = check_jpeg_structure(path)
        assert result["valid"] is False

        ok, _, msg = repair_jpeg(path)
        assert ok is False

    def test_exactly_one_sector_jpeg(self, tmp_dir):
        """A JPEG that's exactly 512 bytes."""
        data = b"\xff\xd8\xff\xe0" + b"\xab" * 506 + b"\xff\xd9"
        assert len(data) == 512
        path = os.path.join(tmp_dir, "small.jpg")
        with open(path, "wb") as f:
            f.write(data)

        result = check_jpeg_structure(path)
        assert result["has_soi"] is True
        assert result["has_eoi"] is True

    def test_disk_image_only_deleted_files(self, tmp_dir):
        """FAT12 with only deleted entries."""
        disk = bytearray(create_disk_image("TEST"))

        # Write a directory entry with 0xE5 first byte (deleted)
        root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
        disk[root_offset] = 0xE5
        disk[root_offset + 1 : root_offset + 8] = b"VC-001 "
        disk[root_offset + 8 : root_offset + 11] = b"JPG"
        disk[root_offset + 11] = 0x20
        struct.pack_into("<I", disk, root_offset + 28, 1000)

        img_path = os.path.join(tmp_dir, "disk.img")
        with open(img_path, "wb") as f:
            f.write(disk)

        # Without deleted flag — should find nothing
        files = list_files(img_path, include_deleted=False)
        assert len(files) == 0

        # With deleted flag — should find the entry with reconstructed name
        files = list_files(img_path, include_deleted=True)
        assert len(files) == 1
        assert files[0].is_deleted is True
        assert files[0].name.startswith("M")  # Reconstructed first byte

    def test_carve_no_jpegs_in_zeros(self, tmp_dir):
        """Carving an all-zeros disk should find nothing."""
        from mavica_tools.multipass import DISK_SIZE
        img_path = os.path.join(tmp_dir, "zeros.img")
        with open(img_path, "wb") as f:
            f.write(b"\x00" * DISK_SIZE)
        carved = carve_jpegs(img_path, os.path.join(tmp_dir, "carved"))
        assert carved == []

    def test_stamp_unknown_model(self, tmp_dir):
        """Stamping with an unknown model should use it as-is."""
        img = Image.new("RGB", (64, 48))
        path = os.path.join(tmp_dir, "test.jpg")
        img.save(path, "JPEG")

        ok, _, _ = stamp_jpeg(path, model="Custom Camera 3000", overwrite=True)
        assert ok is True

        exif = Image.open(path).getexif()
        assert exif[0x0110] == "CUSTOM CAMERA 3000"


class TestFuzzLike:
    """Test with random/malformed data to catch crashes."""

    def test_carve_random_data(self, tmp_dir):
        """Carving random data should not crash."""
        import random
        random.seed(42)
        data = bytes(random.getrandbits(8) for _ in range(10000))

        img_path = os.path.join(tmp_dir, "random.img")
        with open(img_path, "wb") as f:
            f.write(data)

        # Should not crash — may or may not find "JPEGs"
        carve_jpegs(img_path, os.path.join(tmp_dir, "carved"))

    def test_fat12_corrupt_image(self, tmp_dir):
        """Parsing a corrupt FAT12 image should not crash."""
        import random
        random.seed(42)
        data = bytes(random.getrandbits(8) for _ in range(1_474_560))

        img_path = os.path.join(tmp_dir, "corrupt.img")
        with open(img_path, "wb") as f:
            f.write(data)

        # Should not crash — may raise, but not crash
        try:
            list_files(img_path)
        except Exception:
            pass  # Expected — corrupt data

    def test_check_binary_garbage(self, tmp_dir):
        """Checking a non-JPEG binary file should not crash."""
        path = os.path.join(tmp_dir, "garbage.jpg")
        with open(path, "wb") as f:
            f.write(os.urandom(5000))

        result = check_jpeg_structure(path)
        assert result["valid"] is False

    def test_repair_binary_garbage(self, tmp_dir):
        """Repairing a non-JPEG file should fail gracefully."""
        path = os.path.join(tmp_dir, "garbage.jpg")
        with open(path, "wb") as f:
            f.write(os.urandom(5000))

        ok, _, _ = repair_jpeg(path)
        assert ok is False
