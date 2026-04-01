"""Tests for floppy drive auto-detection."""

from unittest.mock import MagicMock, patch

from mavica_tools.detect import FloppyDrive, detect_floppy_drives, detect_floppy_mount_points


class TestDetectFloppyDrives:
    @patch("mavica_tools.detect.subprocess.run", side_effect=FileNotFoundError())
    def test_returns_list(self, mock_run):
        """Should always return a list, even if empty."""
        result = detect_floppy_drives()
        assert isinstance(result, list)

    def test_floppy_drive_dataclass(self):
        d = FloppyDrive(
            device="/dev/fd0",
            label="Test",
            removable=True,
            size_bytes=1474560,
        )
        assert d.device == "/dev/fd0"
        assert d.size_bytes == 1474560

    @patch("mavica_tools.detect.platform.system", return_value="Linux")
    @patch("mavica_tools.detect.os.path.exists", return_value=True)
    def test_linux_detects_fd0(self, mock_exists, mock_system):
        drives = detect_floppy_drives()
        devices = [d.device for d in drives]
        assert "/dev/fd0" in devices

    @patch("mavica_tools.detect.platform.system", return_value="Windows")
    @patch("mavica_tools.detect.subprocess.run")
    def test_windows_fallback_suggests_a_drive(self, mock_run, mock_system):
        mock_run.side_effect = FileNotFoundError()
        drives = detect_floppy_drives()
        assert len(drives) >= 1
        assert any("A:" in d.device for d in drives)


class TestDetectFloppyMountPoints:
    @patch("mavica_tools.detect.subprocess.run", side_effect=FileNotFoundError())
    @patch("mavica_tools.detect.os.path.isdir", return_value=False)
    def test_returns_list(self, mock_isdir, mock_run):
        result = detect_floppy_mount_points()
        assert isinstance(result, list)

    @patch("mavica_tools.detect.platform.system", return_value="Windows")
    @patch("mavica_tools.detect.subprocess.run")
    @patch("mavica_tools.detect.os.path.isdir", return_value=True)
    def test_windows_returns_drive_letter(self, mock_isdir, mock_run, mock_system):
        import json

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"DeviceID": "A:"}),
        )
        mounts = detect_floppy_mount_points()
        assert any("A:" in m for m in mounts)

    @patch("mavica_tools.detect.platform.system", return_value="Windows")
    @patch("mavica_tools.detect.subprocess.run")
    @patch("mavica_tools.detect.os.path.isdir")
    def test_windows_fallback_checks_a_b(self, mock_isdir, mock_run, mock_system):
        mock_run.side_effect = FileNotFoundError()
        mock_isdir.side_effect = lambda p: p == "A:\\"
        mounts = detect_floppy_mount_points()
        assert "A:\\" in mounts

    @patch("mavica_tools.detect.platform.system", return_value="Windows")
    @patch("mavica_tools.detect.subprocess.run")
    @patch("mavica_tools.detect.os.path.isdir", return_value=False)
    def test_windows_no_drives(self, mock_isdir, mock_run, mock_system):
        mock_run.side_effect = FileNotFoundError()
        mounts = detect_floppy_mount_points()
        assert mounts == []

    @patch("mavica_tools.detect.platform.system", return_value="Linux")
    @patch("builtins.open")
    @patch("mavica_tools.detect.os.path.ismount", return_value=False)
    def test_linux_reads_proc_mounts(self, mock_ismount, mock_open, mock_system):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.__iter__ = lambda s: iter(["/dev/fd0 /mnt/floppy vfat rw 0 0\n"])
        mounts = detect_floppy_mount_points()
        assert "/mnt/floppy" in mounts
