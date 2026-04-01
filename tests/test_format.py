"""Tests for the FAT12 floppy formatter."""

import os
import struct
import tempfile

import pytest

from mavica_tools.format import (
    DISK_SIZE,
    MEDIA_DESCRIPTOR,
    SECTOR_SIZE,
    SECTORS_PER_FAT,
    TOTAL_SECTORS,
    create_boot_sector,
    create_disk_image,
    create_fat,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestCreateBootSector:
    def test_size(self):
        boot = create_boot_sector()
        assert len(boot) == SECTOR_SIZE

    def test_boot_signature(self):
        boot = create_boot_sector()
        assert boot[510] == 0x55
        assert boot[511] == 0xAA

    def test_oem_name(self):
        boot = create_boot_sector()
        assert boot[3:11] == b"MAVICA  "

    def test_bytes_per_sector(self):
        boot = create_boot_sector()
        bps = struct.unpack_from("<H", boot, 11)[0]
        assert bps == 512

    def test_sectors_per_cluster(self):
        boot = create_boot_sector()
        assert boot[13] == 1

    def test_total_sectors(self):
        boot = create_boot_sector()
        total = struct.unpack_from("<H", boot, 19)[0]
        assert total == TOTAL_SECTORS

    def test_media_descriptor(self):
        boot = create_boot_sector()
        assert boot[21] == MEDIA_DESCRIPTOR

    def test_fat12_label(self):
        boot = create_boot_sector()
        assert boot[54:62] == b"FAT12   "

    def test_custom_volume_label(self):
        boot = create_boot_sector("MY DISK")
        label = boot[43:54].decode("ascii")
        assert label.strip() == "MY DISK"

    def test_extended_boot_signature(self):
        boot = create_boot_sector()
        assert boot[38] == 0x29


class TestCreateFat:
    def test_fat_size(self):
        fat = create_fat()
        assert len(fat) == SECTORS_PER_FAT * SECTOR_SIZE

    def test_media_descriptor_in_fat(self):
        fat = create_fat()
        assert fat[0] == MEDIA_DESCRIPTOR

    def test_reserved_entries(self):
        fat = create_fat()
        # Bytes 0-2 encode entries 0 and 1
        assert fat[0] == 0xF0
        assert fat[1] == 0xFF
        assert fat[2] == 0xFF


class TestCreateDiskImage:
    def test_image_size(self):
        image = create_disk_image()
        assert len(image) == DISK_SIZE

    def test_image_is_valid_fat12(self):
        """The created image should be parseable by our FAT12 parser."""
        from mavica_tools.fat12 import list_files, read_fat12

        image = create_disk_image("TEST")

        # Write to temp file for list_files
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as f:
            f.write(image)
            path = f.name

        try:
            fat = read_fat12(image)
            assert fat[0] == 0xFF0  # media descriptor
            assert fat[1] == 0xFFF  # end of chain

            files = list_files(path)
            assert files == []  # empty disk
        finally:
            os.unlink(path)

    def test_write_to_file(self, tmp_dir):
        image = create_disk_image()
        path = os.path.join(tmp_dir, "test.img")
        with open(path, "wb") as f:
            f.write(image)
        assert os.path.getsize(path) == DISK_SIZE
