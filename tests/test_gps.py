"""Tests for the GPS track merge tool."""

import os
import tempfile
from datetime import datetime, timezone

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from mavica_tools.gps import (
    GpsMatch,
    GpsPoint,
    _decimal_to_dms,
    _interpolate_point,
    generate_map_html,
    match_photos_to_track,
    merge_tracks,
    parse_gpx,
    stamp_gps_exif,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_gpx(tmp_dir, name="track.gpx", points=None):
    """Create a GPX file with trackpoints."""
    if points is None:
        points = [
            (47.6062, -122.3321, 10, "2001-07-04T10:00:00Z"),
            (47.6065, -122.3325, 12, "2001-07-04T10:05:00Z"),
            (47.6070, -122.3330, 15, "2001-07-04T10:10:00Z"),
            (47.6080, -122.3340, 20, "2001-07-04T10:20:00Z"),
        ]

    gpx_content = '<?xml version="1.0"?>\n<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">\n<trk><trkseg>\n'
    for lat, lon, alt, time in points:
        gpx_content += (
            f'<trkpt lat="{lat}" lon="{lon}"><ele>{alt}</ele><time>{time}</time></trkpt>\n'
        )
    gpx_content += "</trkseg></trk>\n</gpx>"

    path = os.path.join(tmp_dir, name)
    with open(path, "w") as f:
        f.write(gpx_content)
    return path


def make_jpeg_with_time(tmp_dir, name, date_str):
    """Create a JPEG with EXIF date set."""
    img = Image.new("RGB", (640, 480), color=(100, 50, 25))
    path = os.path.join(tmp_dir, name)

    exif = img.getexif()
    exif[0x9003] = date_str  # DateTimeOriginal
    img.save(path, "JPEG", exif=exif.tobytes())
    return path


class TestParseGpx:
    def test_parse_valid_gpx(self, tmp_dir):
        path = make_gpx(tmp_dir)
        points = parse_gpx(path)
        assert len(points) == 4
        assert points[0].lat == pytest.approx(47.6062)
        assert points[0].lon == pytest.approx(-122.3321)
        assert points[0].alt == pytest.approx(10)

    def test_sorted_by_time(self, tmp_dir):
        points_data = [
            (47.0, -122.0, 0, "2001-07-04T10:10:00Z"),
            (47.1, -122.1, 0, "2001-07-04T10:00:00Z"),
        ]
        path = make_gpx(tmp_dir, points=points_data)
        points = parse_gpx(path)
        assert points[0].time < points[1].time

    def test_empty_gpx(self, tmp_dir):
        path = os.path.join(tmp_dir, "empty.gpx")
        with open(path, "w") as f:
            f.write(
                '<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>'
            )
        points = parse_gpx(path)
        assert points == []

    def test_no_namespace(self, tmp_dir):
        """GPX files without namespace should still parse."""
        path = os.path.join(tmp_dir, "nons.gpx")
        with open(path, "w") as f:
            f.write(
                '<?xml version="1.0"?><gpx><trk><trkseg>'
                '<trkpt lat="47.0" lon="-122.0"><time>2001-07-04T10:00:00Z</time></trkpt>'
                "</trkseg></trk></gpx>"
            )
        points = parse_gpx(path)
        assert len(points) == 1


class TestMatchPhotos:
    def test_exact_match(self, tmp_dir):
        gpx = make_gpx(tmp_dir)
        track = parse_gpx(gpx)
        photo = make_jpeg_with_time(tmp_dir, "photo.jpg", "2001:07:04 10:05:00")

        matches = match_photos_to_track([photo], track, tolerance_seconds=300)
        assert matches[0] is not None
        assert matches[0].point.lat == pytest.approx(47.6065, abs=0.001)

    def test_within_tolerance(self, tmp_dir):
        gpx = make_gpx(tmp_dir)
        track = parse_gpx(gpx)
        # 2 minutes after a trackpoint — within 5min tolerance
        photo = make_jpeg_with_time(tmp_dir, "photo.jpg", "2001:07:04 10:07:00")

        matches = match_photos_to_track([photo], track, tolerance_seconds=300)
        assert matches[0] is not None

    def test_outside_tolerance(self, tmp_dir):
        gpx = make_gpx(tmp_dir)
        track = parse_gpx(gpx)
        # 2 hours later — way outside tolerance
        photo = make_jpeg_with_time(tmp_dir, "photo.jpg", "2001:07:04 12:00:00")

        matches = match_photos_to_track([photo], track, tolerance_seconds=300)
        assert matches[0] is None

    def test_no_track(self, tmp_dir):
        photo = make_jpeg_with_time(tmp_dir, "photo.jpg", "2001:07:04 10:00:00")
        matches = match_photos_to_track([photo], [], tolerance_seconds=300)
        assert matches[0] is None

    def test_multiple_photos(self, tmp_dir):
        gpx = make_gpx(tmp_dir)
        track = parse_gpx(gpx)
        photos = [
            make_jpeg_with_time(tmp_dir, "a.jpg", "2001:07:04 10:00:00"),
            make_jpeg_with_time(tmp_dir, "b.jpg", "2001:07:04 10:10:00"),
            make_jpeg_with_time(tmp_dir, "c.jpg", "2001:07:04 15:00:00"),  # no match
        ]
        matches = match_photos_to_track(photos, track, tolerance_seconds=300)
        assert matches[0] is not None
        assert matches[1] is not None
        assert matches[2] is None


class TestInterpolate:
    def test_midpoint(self):
        p1 = GpsPoint(
            lat=47.0, lon=-122.0, alt=0, time=datetime(2001, 7, 4, 10, 0, tzinfo=timezone.utc)
        )
        p2 = GpsPoint(
            lat=48.0, lon=-123.0, alt=100, time=datetime(2001, 7, 4, 10, 10, tzinfo=timezone.utc)
        )
        mid_time = datetime(2001, 7, 4, 10, 5, tzinfo=timezone.utc)
        result = _interpolate_point(p1, p2, mid_time)
        assert result.lat == pytest.approx(47.5)
        assert result.lon == pytest.approx(-122.5)
        assert result.alt == pytest.approx(50)


class TestDecimalToDms:
    def test_positive(self):
        dms = _decimal_to_dms(47.6062)
        assert dms[0] == (47, 1)  # degrees
        assert dms[1] == (36, 1)  # minutes

    def test_negative(self):
        dms = _decimal_to_dms(-122.3321)
        assert dms[0] == (122, 1)  # absolute degrees


class TestStampGps:
    def test_writes_gps_exif(self, tmp_dir):
        piexif = pytest.importorskip("piexif")
        path = os.path.join(tmp_dir, "photo.jpg")
        img = Image.new("RGB", (640, 480))
        img.save(path, "JPEG")

        ok, msg = stamp_gps_exif(path, 47.6062, -122.3321, alt=50.0)
        assert ok is True
        assert "47.6062" in msg

    def test_graceful_without_piexif(self, tmp_dir, monkeypatch):
        """stamp_gps_exif should fail gracefully if piexif is not installed."""

        # Simulate piexif missing by making import fail
        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )

        def mock_import(name, *args, **kwargs):
            if name == "piexif":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        path = os.path.join(tmp_dir, "photo.jpg")
        img = Image.new("RGB", (640, 480))
        img.save(path, "JPEG")

        monkeypatch.setattr("builtins.__import__", mock_import)
        ok, msg = stamp_gps_exif(path, 47.0, -122.0)
        assert ok is False
        assert "piexif" in msg.lower()


class TestMergeTracks:
    def test_merge_two_gpx(self, tmp_dir):
        gpx1 = make_gpx(
            tmp_dir,
            "day1.gpx",
            [
                (47.0, -122.0, 0, "2001-07-04T10:00:00Z"),
            ],
        )
        gpx2 = make_gpx(
            tmp_dir,
            "day2.gpx",
            [
                (47.1, -122.1, 0, "2001-07-05T10:00:00Z"),
            ],
        )
        track = merge_tracks([gpx1, gpx2])
        assert len(track) == 2
        assert track[0].time < track[1].time


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestFixtureGpx:
    """Tests using the fixture GPX track and real Mavica JPEG fixtures."""

    def test_parse_fixture_gpx(self):
        """Fixture GPX should parse with 61 trackpoints."""
        gpx_path = os.path.join(FIXTURES_DIR, "track_2001-07-04.gpx")
        if not os.path.exists(gpx_path):
            pytest.skip("fixture GPX not built — run tests/build_fixtures.py")
        points = parse_gpx(gpx_path)
        assert len(points) == 61
        assert points[0].lat == pytest.approx(35.68, abs=0.01)
        assert points[0].alt is not None
        # Track spans 1 hour
        duration = (points[-1].time - points[0].time).total_seconds()
        assert duration == pytest.approx(3600, abs=1)

    def test_match_fixture_jpegs_to_track(self, tmp_dir):
        """Fixture JPEGs (with EXIF dates on 2001-07-04) should match the fixture track."""
        gpx_path = os.path.join(FIXTURES_DIR, "track_2001-07-04.gpx")
        if not os.path.exists(gpx_path):
            pytest.skip("fixture GPX not built — run tests/build_fixtures.py")

        track = parse_gpx(gpx_path)

        # Create photos with timestamps that fall within the track window
        photos = [
            make_jpeg_with_time(tmp_dir, "MVC-001.JPG", "2001:07:04 10:05:00"),
            make_jpeg_with_time(tmp_dir, "MVC-002.JPG", "2001:07:04 10:30:00"),
            make_jpeg_with_time(tmp_dir, "MVC-003.JPG", "2001:07:04 10:55:00"),
            make_jpeg_with_time(tmp_dir, "MVC-004.JPG", "2001:07:04 12:00:00"),  # outside track
        ]

        matches = match_photos_to_track(photos, track, tolerance_seconds=300)
        # First 3 should match (within the 10:00-11:00 track window)
        assert matches[0] is not None
        assert matches[1] is not None
        assert matches[2] is not None
        # Last one is 1 hour after track ends — outside 5min tolerance
        assert matches[3] is None

        # Matched coordinates should be in Tokyo area
        for m in matches[:3]:
            assert 35.67 < m.point.lat < 35.70
            assert 139.76 < m.point.lon < 139.79

    def test_fixture_tolerance_matching(self):
        """Fixture JPEGs have offset timestamps to test tolerance behavior.

        MVC-002F: 10:10:42 — 42s offset from 10:10 trackpoint (easy match)
        MVC-004F: 10:33:18 — 3m18s offset from 10:33 trackpoint (within 5m)
        MVC-006F: 11:06:15 — 6m15s past track end at 11:00, outside 5m tolerance
        """
        gpx_path = os.path.join(FIXTURES_DIR, "track_2001-07-04.gpx")
        if not os.path.exists(gpx_path):
            pytest.skip("fixture GPX not built — run tests/build_fixtures.py")

        track = parse_gpx(gpx_path)
        fixture_jpegs = sorted(
            os.path.join(FIXTURES_DIR, f)
            for f in os.listdir(FIXTURES_DIR)
            if f.endswith(".JPG")
        )

        # Default 5m tolerance: MVC-002F and MVC-004F match, MVC-006F doesn't
        matches_5m = match_photos_to_track(fixture_jpegs, track, tolerance_seconds=300)
        names = {os.path.basename(f): m for f, m in zip(fixture_jpegs, matches_5m)}
        assert names["MVC-002F.JPG"] is not None  # 42s offset
        assert names["MVC-002F.JPG"].offset_seconds < 60
        assert names["MVC-004F.JPG"] is not None  # 3m18s offset
        assert names["MVC-004F.JPG"].offset_seconds < 240
        assert names["MVC-006F.JPG"] is None  # 6m15s — outside 5m

        # Increase tolerance to 7m: now MVC-006F should also match
        matches_7m = match_photos_to_track(fixture_jpegs, track, tolerance_seconds=420)
        names_7m = {os.path.basename(f): m for f, m in zip(fixture_jpegs, matches_7m)}
        assert names_7m["MVC-006F.JPG"] is not None
        assert names_7m["MVC-006F.JPG"].offset_seconds < 420

    def test_stamp_fixture_gpx_roundtrip(self, tmp_dir):
        """Match + stamp + re-read GPS coordinates from fixture track."""
        piexif = pytest.importorskip("piexif")
        gpx_path = os.path.join(FIXTURES_DIR, "track_2001-07-04.gpx")
        if not os.path.exists(gpx_path):
            pytest.skip("fixture GPX not built — run tests/build_fixtures.py")

        track = parse_gpx(gpx_path)
        photo = make_jpeg_with_time(tmp_dir, "test.jpg", "2001:07:04 10:30:00")
        matches = match_photos_to_track([photo], track, tolerance_seconds=300)
        assert matches[0] is not None

        # Stamp GPS
        m = matches[0]
        ok, msg = stamp_gps_exif(photo, m.point.lat, m.point.lon, m.point.alt, m.point.time)
        assert ok

        # Read back and verify coordinates
        exif_dict = piexif.load(photo)
        gps = exif_dict["GPS"]
        assert piexif.GPSIFD.GPSLatitude in gps
        assert piexif.GPSIFD.GPSLongitude in gps
        # Latitude ref should be N (Tokyo)
        assert gps[piexif.GPSIFD.GPSLatitudeRef] == b"N"
        assert gps[piexif.GPSIFD.GPSLongitudeRef] == b"E"


class TestMapHtml:
    def test_generates_html(self, tmp_dir):
        matches = [
            GpsMatch(
                photo_path="/photo1.jpg",
                point=GpsPoint(47.6, -122.3, None, datetime.now(tz=timezone.utc)),
                offset_seconds=0,
            ),
        ]
        out = os.path.join(tmp_dir, "map.html")
        generate_map_html(matches, out, title="Test Map")
        assert os.path.exists(out)
        with open(out) as f:
            html = f.read()
        assert "leaflet" in html.lower()
        assert "47.6" in html
        assert "Test Map" in html
