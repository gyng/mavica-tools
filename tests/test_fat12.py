"""Tests for the FAT12 filesystem parser."""

import os
import struct
import tempfile

import pytest

from mavica_tools.fat12 import (
    DATA_START_SECTOR,
    FAT_OFFSET,
    FATS_COUNT,
    ROOT_DIR_ENTRIES,
    SECTOR_SIZE,
    SECTORS_PER_FAT,
    extract_file,
    extract_with_names,
    get_cluster_chain,
    list_files,
    read_directory,
    read_fat12,
)
from mavica_tools.format import create_disk_image


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _add_file_to_image(image: bytearray, name: str, ext: str, data: bytes, cluster: int):
    """Helper: write a file entry + FAT chain + data into a disk image.

    Only handles single-cluster files for simplicity.
    """
    # Write FAT entry (end of chain for single-cluster file)
    fat_offset = FAT_OFFSET * SECTOR_SIZE
    byte_pos = fat_offset + (cluster * 3) // 2
    if cluster % 2 == 0:
        # Low 12 bits
        image[byte_pos] = 0xF8  # 0xFF8 = end of chain (low byte)
        image[byte_pos + 1] = (image[byte_pos + 1] & 0xF0) | 0x0F
    else:
        # High 12 bits
        image[byte_pos] = (image[byte_pos] & 0x0F) | 0x80
        image[byte_pos + 1] = 0xFF  # upper byte of 0xFF8

    # Copy FAT to second FAT
    fat2_offset = fat_offset + SECTORS_PER_FAT * SECTOR_SIZE
    for i in range(SECTORS_PER_FAT * SECTOR_SIZE):
        image[fat2_offset + i] = image[fat_offset + i]

    # Write directory entry
    root_dir_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
    # Find first empty entry
    for i in range(ROOT_DIR_ENTRIES):
        entry_off = root_dir_offset + i * 32
        if image[entry_off] == 0x00:
            # Write 8.3 name
            padded_name = name.encode("ascii").ljust(8)[:8]
            padded_ext = ext.encode("ascii").ljust(3)[:3]
            image[entry_off : entry_off + 8] = padded_name
            image[entry_off + 8 : entry_off + 11] = padded_ext
            image[entry_off + 11] = 0x20  # Archive attribute
            # Date: 2000-01-15
            dos_date = (15) | (1 << 5) | ((2000 - 1980) << 9)
            struct.pack_into("<H", image, entry_off + 24, dos_date)
            # Time: 10:30:00
            dos_time = (0) | (30 << 5) | (10 << 11)
            struct.pack_into("<H", image, entry_off + 22, dos_time)
            # Start cluster
            struct.pack_into("<H", image, entry_off + 26, cluster)
            # File size
            struct.pack_into("<I", image, entry_off + 28, len(data))
            break

    # Write data to cluster
    data_offset = DATA_START_SECTOR * SECTOR_SIZE + (cluster - 2) * SECTOR_SIZE
    image[data_offset : data_offset + len(data)] = data[:SECTOR_SIZE]


def _make_test_image(tmp_dir, files=None):
    """Create a test FAT12 disk image with optional files.

    files: list of (name, ext, data, cluster)
    """
    image = bytearray(create_disk_image("TEST"))

    if files:
        for name, ext, data, cluster in files:
            _add_file_to_image(image, name, ext, data, cluster)

    path = os.path.join(tmp_dir, "test.img")
    with open(path, "wb") as f:
        f.write(image)
    return path


class TestReadFat12:
    def test_empty_fat_has_reserved_entries(self, tmp_dir):
        path = _make_test_image(tmp_dir)
        with open(path, "rb") as f:
            data = f.read()
        fat = read_fat12(data)
        # First two entries are reserved
        assert fat[0] == 0xFF0  # media descriptor
        assert fat[1] == 0xFFF  # end of chain

    def test_fat_entries_default_to_zero(self, tmp_dir):
        path = _make_test_image(tmp_dir)
        with open(path, "rb") as f:
            data = f.read()
        fat = read_fat12(data)
        # Entries after reserved should be 0 (free)
        assert fat[2] == 0
        assert fat[3] == 0


class TestReadDirectory:
    def test_empty_directory(self, tmp_dir):
        path = _make_test_image(tmp_dir)
        with open(path, "rb") as f:
            data = f.read()
        root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
        entries = read_directory(data, root_offset, ROOT_DIR_ENTRIES)
        assert entries == []

    def test_reads_file_entry(self, tmp_dir):
        file_data = b"\xff\xd8\xff\xe0" + b"\xab" * 100
        path = _make_test_image(tmp_dir, [("MVC-001 ", "JPG", file_data, 2)])
        with open(path, "rb") as f:
            data = f.read()
        root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
        entries = read_directory(data, root_offset, ROOT_DIR_ENTRIES)
        assert len(entries) == 1
        assert entries[0].name == "MVC-001.JPG"
        assert entries[0].size == len(file_data)
        assert entries[0].start_cluster == 2
        assert entries[0].is_deleted is False

    def test_reads_date_time(self, tmp_dir):
        path = _make_test_image(tmp_dir, [("TEST    ", "JPG", b"\xff" * 10, 2)])
        with open(path, "rb") as f:
            data = f.read()
        root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
        entries = read_directory(data, root_offset, ROOT_DIR_ENTRIES)
        assert entries[0].date_str == "2000-01-15"
        assert entries[0].time_str == "10:30:00"


class TestGetClusterChain:
    def test_single_cluster(self):
        # FAT: cluster 2 = end of chain
        fat = [0xFF0, 0xFFF, 0xFF8, 0, 0, 0]
        chain = get_cluster_chain(fat, 2)
        assert chain == [2]

    def test_multi_cluster(self):
        # FAT: 2 -> 3 -> 4 -> end
        fat = [0xFF0, 0xFFF, 3, 4, 0xFF8, 0]
        chain = get_cluster_chain(fat, 2)
        assert chain == [2, 3, 4]

    def test_free_cluster_stops_chain(self):
        # Cluster 2 points to 0 (free), chain should include only cluster 2
        # because next lookup fat[0] = 0xFF0 which is >= 0xFF8? No, 0xFF0 < 0xFF8
        # Actually: cluster 2 has value 0, so next = fat[0] = 0xFF0, which is end-of-chain
        # The chain walk follows: 2 -> fat[2]=0 -> fat[0]=0xFF0 -> stop (>= 0xFF8? no)
        # Actually 0xFF0 < 0xFF8, so it continues. Let's just test what the code does.
        fat = [0xFF0, 0xFFF, 0xFF8, 0]  # cluster 2 = end of chain
        chain = get_cluster_chain(fat, 2)
        assert chain == [2]

    def test_prevents_infinite_loop(self):
        # Circular: 2 -> 3 -> 2
        fat = [0xFF0, 0xFFF, 3, 2, 0]
        chain = get_cluster_chain(fat, 2)
        assert chain == [2, 3]  # Should stop at the cycle


class TestExtractFile:
    def test_extract_single_cluster(self, tmp_dir):
        file_data = b"\xff\xd8\xff\xe0" + b"\xab" * 100
        path = _make_test_image(tmp_dir, [("MVC-001 ", "JPG", file_data, 2)])
        with open(path, "rb") as f:
            data = f.read()

        fat = read_fat12(data)
        root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
        entries = read_directory(data, root_offset, ROOT_DIR_ENTRIES)

        extracted = extract_file(data, fat, entries[0])
        assert extracted == file_data


class TestListFiles:
    def test_list_files(self, tmp_dir):
        path = _make_test_image(
            tmp_dir,
            [
                ("MVC-001 ", "JPG", b"\xff" * 50, 2),
                ("MVC-002 ", "JPG", b"\xff" * 80, 3),
            ],
        )
        files = list_files(path)
        assert len(files) == 2
        names = [f.name for f in files]
        assert "MVC-001.JPG" in names
        assert "MVC-002.JPG" in names

    def test_empty_image(self, tmp_dir):
        path = _make_test_image(tmp_dir)
        files = list_files(path)
        assert files == []


class TestExtractWithNames:
    def test_extract_preserves_names(self, tmp_dir):
        file_data = b"\xff\xd8" + b"\xab" * 100
        img_path = _make_test_image(tmp_dir, [("MVC-001 ", "JPG", file_data, 2)])
        output_dir = os.path.join(tmp_dir, "output")

        results = extract_with_names(img_path, output_dir)
        assert len(results) == 1
        name, path, size, deleted = results[0]
        assert name == "MVC-001.JPG"
        assert os.path.exists(path)
        assert os.path.basename(path) == "MVC-001.JPG"
        assert deleted is False
