"""End-to-end CLI tests.

Runs actual mavica CLI commands via subprocess and verifies outputs.
Tests the full user experience as if typing commands in a terminal.
"""

import os
import struct
import subprocess
import sys
import tempfile

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image
from io import BytesIO


MAVICA = [sys.executable, "-m", "mavica_tools"]


def run(args, timeout=30, **kwargs):
    """Run a mavica CLI command and return the result."""
    return subprocess.run(
        MAVICA + args,
        capture_output=True, text=True, timeout=timeout, **kwargs,
    )


def make_jpeg(directory, name="MVC-001.JPG", width=640, height=480):
    """Create a real JPEG file in a directory."""
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    path = os.path.join(directory, name)
    img.save(path, "JPEG")
    return path


def make_disk_image(directory, name="disk.img", jpeg_data=None):
    """Create a FAT12 disk image with an embedded JPEG."""
    from mavica_tools.format import create_disk_image
    from mavica_tools.fat12 import (
        FAT_OFFSET, FATS_COUNT, SECTORS_PER_FAT,
        DATA_START_SECTOR, SECTOR_SIZE,
    )

    disk = bytearray(create_disk_image("TEST"))

    if jpeg_data is None:
        img = Image.new("RGB", (640, 480), color=(180, 90, 45))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=80)
        jpeg_data = buf.getvalue()

    # Write data
    cluster = 2
    clusters_needed = (len(jpeg_data) + SECTOR_SIZE - 1) // SECTOR_SIZE
    for i in range(clusters_needed):
        offset = (DATA_START_SECTOR + i) * SECTOR_SIZE
        chunk = jpeg_data[i * SECTOR_SIZE : (i + 1) * SECTOR_SIZE]
        disk[offset : offset + len(chunk)] = chunk

    # FAT chain
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

    # Copy FAT2
    fat2_offset = fat_offset + SECTORS_PER_FAT * SECTOR_SIZE
    disk[fat2_offset : fat2_offset + SECTORS_PER_FAT * SECTOR_SIZE] = (
        disk[fat_offset : fat_offset + SECTORS_PER_FAT * SECTOR_SIZE]
    )

    # Directory entry
    root_offset = (FAT_OFFSET + FATS_COUNT * SECTORS_PER_FAT) * SECTOR_SIZE
    entry = bytearray(32)
    entry[0:8] = b"MVC-001 "
    entry[8:11] = b"JPG"
    entry[11] = 0x20
    dos_date = 15 | (7 << 5) | ((2001 - 1980) << 9)
    struct.pack_into("<H", entry, 24, dos_date)
    struct.pack_into("<H", entry, 26, cluster)
    struct.pack_into("<I", entry, 28, len(jpeg_data))
    disk[root_offset : root_offset + 32] = entry

    path = os.path.join(directory, name)
    with open(path, "wb") as f:
        f.write(disk)
    return path


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ─── Help & basic CLI ────────────────────────────────────────────────────

class TestCLIBasics:
    def test_help(self):
        r = run(["--help"])
        assert r.returncode == 0
        assert "mavica" in r.stdout.lower()

    def test_no_args_shows_tools(self):
        r = run([])
        out = r.stdout + r.stderr
        assert "import" in out
        assert "tui" in out

    def test_invalid_subcommand(self):
        r = run(["nonexistent"])
        assert r.returncode != 0


# ─── mavica import ───────────────────────────────────────────────────────

class TestImportCLI:
    def test_import_from_directory(self, tmp_dir):
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        make_jpeg(src, "MVC-002.JPG")
        out = os.path.join(tmp_dir, "photos")

        r = run(["import", src, "-o", out])
        assert r.returncode == 0
        assert "2 photo(s) imported" in r.stdout
        assert os.path.exists(os.path.join(out, "MVC-001.JPG"))
        assert os.path.exists(os.path.join(out, "MVC-002.JPG"))

    def test_import_with_model(self, tmp_dir):
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        make_jpeg(src, "MVC-001.JPG")
        out = os.path.join(tmp_dir, "photos")

        r = run(["import", src, "-o", out, "-m", "fd7"])
        assert r.returncode == 0
        assert "Tagged" in r.stdout or "tagged" in r.stdout.lower()

        # Verify EXIF
        img = Image.open(os.path.join(out, "MVC-001.JPG"))
        exif = img.getexif()
        assert exif.get(0x0110) == "Sony Mavica MVC-FD7"

    def test_import_with_contact_sheet(self, tmp_dir):
        src = os.path.join(tmp_dir, "floppy")
        os.makedirs(src)
        for i in range(4):
            make_jpeg(src, f"MVC-{i:03d}.JPG")
        out = os.path.join(tmp_dir, "photos")

        r = run(["import", src, "-o", out, "--contact-sheet"])
        assert r.returncode == 0
        assert "contact" in r.stdout.lower()
        assert os.path.exists(os.path.join(out, "contact_sheet.jpg"))

    def test_import_empty_dir(self, tmp_dir):
        src = os.path.join(tmp_dir, "empty")
        os.makedirs(src)
        out = os.path.join(tmp_dir, "photos")

        r = run(["import", src, "-o", out])
        assert "0 photo(s)" in r.stdout or "No photos" in r.stdout


# ─── mavica check ────────────────────────────────────────────────────────

class TestCheckCLI:
    def test_check_good_files(self, tmp_dir):
        make_jpeg(tmp_dir, "good.jpg")
        r = run(["check", tmp_dir, "-v"])
        assert r.returncode == 0
        assert "1 files checked" in r.stdout
        assert "OK" in r.stdout

    def test_check_bad_file(self, tmp_dir):
        path = os.path.join(tmp_dir, "bad.jpg")
        with open(path, "wb") as f:
            f.write(b"not a jpeg at all")

        r = run(["check", path])
        assert "BAD" in r.stdout or "Bad" in r.stdout

    def test_check_mixed(self, tmp_dir):
        make_jpeg(tmp_dir, "good.jpg")
        bad = os.path.join(tmp_dir, "bad.jpg")
        with open(bad, "wb") as f:
            f.write(b"not jpeg")

        r = run(["check", tmp_dir])
        assert "OK" in r.stdout


# ─── mavica carve ────────────────────────────────────────────────────────

class TestCarveCLI:
    def test_carve_from_disk_image(self, tmp_dir):
        img_path = make_disk_image(tmp_dir)
        out = os.path.join(tmp_dir, "carved")

        r = run(["carve", img_path, "-o", out])
        assert r.returncode == 0
        assert "extracted" in r.stdout.lower() or "image(s)" in r.stdout

        carved = [f for f in os.listdir(out) if f.endswith(".jpg")]
        assert len(carved) >= 1

    def test_carve_empty_image(self, tmp_dir):
        from mavica_tools.multipass import DISK_SIZE
        path = os.path.join(tmp_dir, "empty.img")
        with open(path, "wb") as f:
            f.write(b"\x00" * DISK_SIZE)
        out = os.path.join(tmp_dir, "carved")

        r = run(["carve", path, "-o", out])
        assert "No JPEG" in r.stdout or "0" in r.stdout


# ─── mavica repair ───────────────────────────────────────────────────────

class TestRepairCLI:
    def test_repair_good_jpeg(self, tmp_dir):
        path = make_jpeg(tmp_dir, "good.jpg")
        r = run(["repair", path])
        assert r.returncode == 0
        assert "FIXED" in r.stdout or "fixed" in r.stdout

    def test_repair_not_jpeg(self, tmp_dir):
        path = os.path.join(tmp_dir, "fake.jpg")
        with open(path, "wb") as f:
            f.write(b"not a jpeg")
        r = run(["repair", path])
        assert "FAIL" in r.stdout or "fail" in r.stdout


# ─── mavica stamp ────────────────────────────────────────────────────────

class TestStampCLI:
    def test_stamp_with_model(self, tmp_dir):
        path = make_jpeg(tmp_dir, "photo.jpg")
        r = run(["stamp", path, "-m", "fd88", "-d", "2001-07-04"])
        assert r.returncode == 0
        assert "stamped" in r.stdout.lower() or "OK" in r.stdout

    def test_stamp_auto_date(self, tmp_dir):
        path = make_jpeg(tmp_dir, "photo.jpg")
        r = run(["stamp", path, "-m", "fd7", "-d", "auto"])
        assert r.returncode == 0


# ─── mavica fat12 ────────────────────────────────────────────────────────

class TestFat12CLI:
    def test_fat12_ls(self, tmp_dir):
        img_path = make_disk_image(tmp_dir)
        r = run(["fat12", "ls", img_path])
        assert r.returncode == 0
        assert "MVC-001.JPG" in r.stdout

    def test_fat12_extract(self, tmp_dir):
        img_path = make_disk_image(tmp_dir)
        out = os.path.join(tmp_dir, "extracted")
        r = run(["fat12", "extract", img_path, "-o", out])
        assert r.returncode == 0
        assert os.path.exists(os.path.join(out, "MVC-001.JPG"))


# ─── mavica format ───────────────────────────────────────────────────────

class TestFormatCLI:
    def test_format_image(self, tmp_dir):
        out = os.path.join(tmp_dir, "blank.img")
        r = run(["format", "image", "-o", out, "-l", "MYmavica"])
        assert r.returncode == 0
        assert os.path.exists(out)
        assert os.path.getsize(out) == 1_474_560
        assert "MYmavica" in r.stdout


# ─── mavica export ───────────────────────────────────────────────────────

class TestExportCLI:
    def test_export_flat(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        os.makedirs(src)
        make_jpeg(src, "a.jpg")
        make_jpeg(src, "b.jpg")
        out = os.path.join(tmp_dir, "export")

        r = run(["export", src, "-o", out])
        assert r.returncode == 0
        assert "2" in r.stdout
        assert os.path.exists(os.path.join(out, "a.jpg"))

    def test_export_with_contact_sheet(self, tmp_dir):
        src = os.path.join(tmp_dir, "src")
        os.makedirs(src)
        for i in range(4):
            make_jpeg(src, f"img{i}.jpg")
        out = os.path.join(tmp_dir, "export")

        r = run(["export", src, "-o", out, "--contact-sheet", "--columns", "2"])
        assert r.returncode == 0
        assert os.path.exists(os.path.join(out, "contact_sheet.jpg"))


# ─── mavica detect ───────────────────────────────────────────────────────

class TestDetectCLI:
    def test_detect_runs(self):
        r = run(["detect"])
        assert r.returncode == 0
        assert "detection" in r.stdout.lower() or "drive" in r.stdout.lower()


# ─── mavica multipass merge ──────────────────────────────────────────────

class TestMultipassCLI:
    def test_merge_images(self, tmp_dir):
        # Create two identical pass images
        img_path = make_disk_image(tmp_dir, "pass_01.img")
        import shutil
        shutil.copy(img_path, os.path.join(tmp_dir, "pass_02.img"))

        merged = os.path.join(tmp_dir, "merged.img")
        r = run(["multipass", "merge",
                 os.path.join(tmp_dir, "pass_01.img"),
                 os.path.join(tmp_dir, "pass_02.img"),
                 "-o", merged])
        assert r.returncode == 0
        assert os.path.exists(merged)
        assert "health" in r.stdout.lower() or "Sector" in r.stdout


# ─── mavica history ──────────────────────────────────────────────────────

class TestHistoryCLI:
    def test_history_view_empty(self, tmp_dir):
        r = run(["history", "view"], env={**os.environ, "HOME": tmp_dir})
        assert r.returncode == 0


# ─── Full pipeline: import → check → stamp → export ─────────────────────

class TestFullPipeline:
    def test_photographer_workflow(self, tmp_dir):
        """Simulate the full photographer workflow via CLI."""
        # 1. Create a "floppy" with photos
        floppy = os.path.join(tmp_dir, "floppy")
        os.makedirs(floppy)
        for i in range(5):
            img = Image.new("RGB", (640, 480), color=(50 + i * 40, 100, 150))
            img.save(os.path.join(floppy, f"MVC-{i + 1:03d}.JPG"), "JPEG")

        # 2. Import with tagging
        photos = os.path.join(tmp_dir, "photos")
        r = run(["import", floppy, "-o", photos, "-m", "fd7", "--contact-sheet"])
        assert r.returncode == 0
        assert "5 photo(s) imported" in r.stdout

        # 3. Check imported photos (5 photos + contact sheet = 6 files)
        r = run(["check", photos, "-v"])
        assert r.returncode == 0
        assert "6 files checked" in r.stdout

        # 4. Export with watermark
        export_dir = os.path.join(tmp_dir, "export")
        r = run(["export", photos, "-o", export_dir,
                 "--watermark", "Shot on Mavica FD7",
                 "--contact-sheet"])
        assert r.returncode == 0

        # 5. Verify everything exists
        assert len(os.listdir(photos)) >= 5  # photos + contact sheet
        assert os.path.exists(os.path.join(export_dir, "contact_sheet.jpg"))

        # 6. Verify EXIF on a photo
        img = Image.open(os.path.join(photos, "MVC-001.JPG"))
        exif = img.getexif()
        assert exif.get(0x010F) == "Sony"
        assert exif.get(0x0110) == "Sony Mavica MVC-FD7"

    def test_recovery_workflow(self, tmp_dir):
        """Simulate the recovery workflow: disk image → carve → check → repair."""
        # 1. Create a disk image
        img_path = make_disk_image(tmp_dir)

        # 2. Carve JPEGs
        carved_dir = os.path.join(tmp_dir, "carved")
        r = run(["carve", img_path, "-o", carved_dir])
        assert r.returncode == 0

        carved_files = [f for f in os.listdir(carved_dir) if f.endswith(".jpg")]
        assert len(carved_files) >= 1

        # 3. Check carved files
        r = run(["check", carved_dir])
        assert r.returncode == 0

        # 4. Stamp
        r = run(["stamp", carved_dir, "-m", "fd88", "-d", "auto", "--overwrite"])
        assert r.returncode == 0

        # 5. Export
        export_dir = os.path.join(tmp_dir, "export")
        r = run(["export", carved_dir, "-o", export_dir, "--contact-sheet"])
        assert r.returncode == 0

    def test_fat12_pipeline(self, tmp_dir):
        """Disk image → FAT12 ls → FAT12 extract → stamp → export."""
        img_path = make_disk_image(tmp_dir)

        # List
        r = run(["fat12", "ls", img_path])
        assert "MVC-001.JPG" in r.stdout

        # Extract
        extract_dir = os.path.join(tmp_dir, "extracted")
        r = run(["fat12", "extract", img_path, "-o", extract_dir])
        assert r.returncode == 0
        assert os.path.exists(os.path.join(extract_dir, "MVC-001.JPG"))

        # Stamp
        r = run(["stamp", extract_dir, "-m", "fd7", "-d", "2001-07-15", "--overwrite"])
        assert r.returncode == 0

        # Export with rename
        export_dir = os.path.join(tmp_dir, "export")
        r = run(["export", extract_dir, "-o", export_dir,
                 "--rename", "template", "--template", "mavica-{n:03d}"])
        assert r.returncode == 0
        assert os.path.exists(os.path.join(export_dir, "mavica-001.JPG"))
