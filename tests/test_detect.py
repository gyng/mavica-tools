"""Tests for floppy drive auto-detection."""

import platform
from unittest.mock import patch

from mavica_tools.detect import detect_floppy_drives, FloppyDrive


class TestDetectFloppyDrives:
    def test_returns_list(self):
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
