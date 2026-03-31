"""Tests for HTML recovery report generation."""

import os
import tempfile

import pytest

from mavica_tools.report import generate_report, _sector_map_html, _file_table_html


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestSectorMapHtml:
    def test_generates_html(self):
        status = ["good"] * 18 + ["blank"] * 18
        html = _sector_map_html(status)
        assert "sector-map" in html
        assert "#33ff33" in html  # good color
        assert "#ff3333" in html  # blank color

    def test_all_statuses(self):
        status = ["good", "recovered", "blank", "conflict"] * 5
        html = _sector_map_html(status)
        for s in ("good", "recovered", "blank", "conflict"):
            assert s in html


class TestFileTableHtml:
    def test_generates_table(self):
        files = [
            {"name": "MVC-001.JPG", "size": 50000, "status": "ok", "details": ""},
            {"name": "MVC-002.JPG", "size": 30000, "status": "repaired", "details": "trimmed"},
        ]
        html = _file_table_html(files)
        assert "MVC-001.JPG" in html
        assert "MVC-002.JPG" in html
        assert "OK" in html
        assert "REPAIRED" in html

    def test_empty_list(self):
        html = _file_table_html([])
        assert "<table" in html


class TestGenerateReport:
    def test_creates_html_file(self, tmp_dir):
        output = os.path.join(tmp_dir, "report.html")
        result = generate_report(
            output,
            sector_status=["good"] * 2880,
            files=[{"name": "test.jpg", "size": 1000, "status": "ok", "details": ""}],
            disk_label="TEST-001",
        )
        assert result == output
        assert os.path.exists(output)

        with open(output) as f:
            html = f.read()
        assert "TEST-001" in html
        assert "test.jpg" in html
        assert "<!DOCTYPE html>" in html

    def test_report_without_sector_map(self, tmp_dir):
        output = os.path.join(tmp_dir, "report.html")
        generate_report(
            output,
            files=[{"name": "img.jpg", "size": 500, "status": "ok", "details": ""}],
        )
        with open(output) as f:
            html = f.read()
        assert "img.jpg" in html

    def test_report_without_files(self, tmp_dir):
        output = os.path.join(tmp_dir, "report.html")
        generate_report(
            output,
            sector_status=["good"] * 100 + ["blank"] * 10,
        )
        with open(output) as f:
            html = f.read()
        assert "Sector Health" in html

    def test_report_with_camera_and_notes(self, tmp_dir):
        output = os.path.join(tmp_dir, "report.html")
        generate_report(
            output,
            disk_label="FD7-DISK",
            camera_model="Sony Mavica FD7",
            notes="Recovered from beach trip 2001",
        )
        with open(output) as f:
            html = f.read()
        assert "Sony Mavica FD7" in html
        assert "beach trip" in html

    def test_html_escapes_user_input(self, tmp_dir):
        output = os.path.join(tmp_dir, "report.html")
        generate_report(
            output,
            disk_label="<script>alert('xss')</script>",
            files=[{"name": "<b>bad</b>.jpg", "size": 0, "status": "ok", "details": ""}],
        )
        with open(output) as f:
            html = f.read()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
