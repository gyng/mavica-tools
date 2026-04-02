"""GPS track merge tool for recovered Mavica images.

Matches photo timestamps to GPX track data and embeds GPS coordinates
into EXIF. Mavica cameras have no GPS — this tool pairs them with
external GPS logger data (Garmin, phone GPX export, Google Timeline).
"""

import argparse
import glob as globmod
import math
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from mavica_tools.utils import get_photo_timestamp as _utils_get_timestamp


@dataclass
class GpsPoint:
    """A GPS trackpoint."""

    lat: float
    lon: float
    alt: float | None
    time: datetime


@dataclass
class GpsMatch:
    """A photo matched to a GPS point."""

    photo_path: str
    point: GpsPoint
    offset_seconds: float  # Time difference between photo and nearest GPS point
    interpolated: bool = False  # True if position was interpolated between two points
    nearest_distance_m: float = 0.0  # Distance from nearest trackpoint in metres


def parse_gpx(gpx_path: str) -> list[GpsPoint]:
    """Parse a GPX file and return trackpoints sorted by time.

    Handles standard GPX 1.0 and 1.1 formats.
    """
    tree = ET.parse(gpx_path)
    root = tree.getroot()

    # Handle namespace — GPX files typically have xmlns
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    points = []

    # Parse <trk><trkseg><trkpt> elements
    for trkpt in root.iter(f"{ns}trkpt"):
        lat = float(trkpt.get("lat", 0))
        lon = float(trkpt.get("lon", 0))

        alt = None
        ele = trkpt.find(f"{ns}ele")
        if ele is not None and ele.text:
            try:
                alt = float(ele.text)
            except ValueError:
                pass

        time_elem = trkpt.find(f"{ns}time")
        if time_elem is not None and time_elem.text:
            time = _parse_gpx_time(time_elem.text)
            if time:
                points.append(GpsPoint(lat=lat, lon=lon, alt=alt, time=time))

    # Also parse <wpt> (waypoints)
    for wpt in root.iter(f"{ns}wpt"):
        lat = float(wpt.get("lat", 0))
        lon = float(wpt.get("lon", 0))

        alt = None
        ele = wpt.find(f"{ns}ele")
        if ele is not None and ele.text:
            try:
                alt = float(ele.text)
            except ValueError:
                pass

        time_elem = wpt.find(f"{ns}time")
        if time_elem is not None and time_elem.text:
            time = _parse_gpx_time(time_elem.text)
            if time:
                points.append(GpsPoint(lat=lat, lon=lon, alt=alt, time=time))

    points.sort(key=lambda p: p.time)
    return points


def _parse_gpx_time(time_str: str) -> datetime | None:
    """Parse GPX time formats (ISO 8601)."""
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(time_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _get_photo_time(filepath: str, use_mtime: bool = False) -> datetime | None:
    """Get photo timestamp from EXIF or file mtime, with timezone."""
    dt = _utils_get_timestamp(filepath, use_mtime=use_mtime)
    if dt and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _interpolate_point(p1: GpsPoint, p2: GpsPoint, target_time: datetime) -> GpsPoint:
    """Linearly interpolate between two GPS points at a target time."""
    total = (p2.time - p1.time).total_seconds()
    if total == 0:
        return p1

    frac = (target_time - p1.time).total_seconds() / total
    frac = max(0.0, min(1.0, frac))

    lat = p1.lat + (p2.lat - p1.lat) * frac
    lon = p1.lon + (p2.lon - p1.lon) * frac
    alt = None
    if p1.alt is not None and p2.alt is not None:
        alt = p1.alt + (p2.alt - p1.alt) * frac

    return GpsPoint(lat=lat, lon=lon, alt=alt, time=target_time)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance between two lat/lon points in metres."""
    R = 6_371_000  # Earth radius in metres
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def match_photos_to_track(
    photo_paths: list[str],
    track_points: list[GpsPoint],
    tolerance_seconds: float = 300,  # 5 minutes
    use_mtime: bool = False,
    interpolate: bool = True,
) -> list[GpsMatch | None]:
    """Match photos to GPS track by timestamp.

    Returns a list parallel to photo_paths — each element is a GpsMatch or None.
    Uses binary search + optional linear interpolation.
    """
    if not track_points:
        return [None] * len(photo_paths)

    import bisect

    track_times = [p.time for p in track_points]

    results = []
    for path in photo_paths:
        photo_time = _get_photo_time(path, use_mtime)
        if photo_time is None:
            results.append(None)
            continue

        # Binary search for nearest trackpoint
        idx = bisect.bisect_left(track_times, photo_time)

        # Check the two nearest candidates
        best_point = None
        best_offset = float("inf")

        for candidate_idx in (idx - 1, idx):
            if 0 <= candidate_idx < len(track_points):
                offset = abs((track_points[candidate_idx].time - photo_time).total_seconds())
                if offset < best_offset:
                    best_offset = offset
                    best_point = track_points[candidate_idx]

        if best_point is None or best_offset > tolerance_seconds:
            results.append(None)
            continue

        # Interpolate between flanking points if possible
        if interpolate and 0 < idx < len(track_points):
            point = _interpolate_point(track_points[idx - 1], track_points[idx], photo_time)
            dist = _haversine_m(point.lat, point.lon, best_point.lat, best_point.lon)
            results.append(
                GpsMatch(
                    photo_path=path,
                    point=point,
                    offset_seconds=best_offset,
                    interpolated=True,
                    nearest_distance_m=dist,
                )
            )
        else:
            results.append(
                GpsMatch(
                    photo_path=path,
                    point=best_point,
                    offset_seconds=best_offset,
                    interpolated=False,
                    nearest_distance_m=0.0,
                )
            )

    return results


def _decimal_to_dms(decimal_degrees: float) -> tuple[tuple, str]:
    """Convert decimal degrees to (degrees, minutes, seconds) rational tuples + ref."""
    if decimal_degrees < 0:
        decimal_degrees = -decimal_degrees
        # Caller determines N/S or E/W

    degrees = int(decimal_degrees)
    minutes_float = (decimal_degrees - degrees) * 60
    minutes = int(minutes_float)
    seconds_float = (minutes_float - minutes) * 60
    # Represent as rational: seconds * 100 / 100 for precision
    seconds_num = int(seconds_float * 100)

    return ((degrees, 1), (minutes, 1), (seconds_num, 100))


def stamp_gps_exif(
    photo_path: str,
    lat: float,
    lon: float,
    alt: float | None = None,
    timestamp: datetime | None = None,
) -> tuple[bool, str]:
    """Write GPS coordinates into JPEG EXIF using piexif.

    Writes proper GPS IFD tags (GPSLatitude, GPSLongitude, etc.)
    that are compatible with all photo viewers and mapping tools.

    Returns (success, message).
    """
    import piexif

    try:
        exif_dict = piexif.load(photo_path)

        lat_dms = _decimal_to_dms(lat)
        lon_dms = _decimal_to_dms(lon)

        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: lat_dms,
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: lon_dms,
        }

        if alt is not None:
            gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = 0 if alt >= 0 else 1
            gps_ifd[piexif.GPSIFD.GPSAltitude] = (int(abs(alt) * 100), 100)

        if timestamp:
            gps_ifd[piexif.GPSIFD.GPSDateStamp] = timestamp.strftime("%Y:%m:%d").encode()
            h, m, s = timestamp.hour, timestamp.minute, timestamp.second
            gps_ifd[piexif.GPSIFD.GPSTimeStamp] = ((h, 1), (m, 1), (s, 1))

        exif_dict["GPS"] = gps_ifd
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, photo_path)

        return True, f"{lat:.6f}, {lon:.6f}"
    except Exception as e:
        return False, str(e)


def generate_map_html(matches: list[GpsMatch], output_path: str, title: str = "") -> str:
    """Generate a self-contained HTML map with photo markers.

    Uses LeafletJS from CDN with OpenStreetMap tiles.
    """
    from html import escape

    valid = [m for m in matches if m is not None]
    if not valid:
        return output_path

    # Calculate center and bounds
    lats = [m.point.lat for m in valid]
    lons = [m.point.lon for m in valid]
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    markers_js = []
    for m in valid:
        name = escape(os.path.basename(m.photo_path))
        time_str = m.point.time.strftime("%Y-%m-%d %H:%M:%S") if m.point.time else ""
        popup = f"{name}<br>{time_str}<br>{m.point.lat:.6f}, {m.point.lon:.6f}"
        markers_js.append(
            f'L.marker([{m.point.lat}, {m.point.lon}]).addTo(map).bindPopup("{popup}");'
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{escape(title or "Mavica Photo Map")}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
body {{ margin:0; background:#0a0a0a; font-family:monospace; }}
h1 {{ color:#33ff33; padding:10px; margin:0; font-size:16px; }}
#map {{ height:calc(100vh - 60px); }}
.info {{ color:#999; padding:5px 10px; font-size:12px; }}
</style>
</head>
<body>
<h1>{escape(title or "Mavica Photo Map")}</h1>
<div class="info">{len(valid)} photo(s) mapped</div>
<div id="map"></div>
<script>
var map = L.map('map').setView([{center_lat}, {center_lon}], 13);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);
{chr(10).join(markers_js)}
var group = L.featureGroup([{",".join(f"L.marker([{m.point.lat},{m.point.lon}])" for m in valid)}]);
map.fitBounds(group.getBounds().pad(0.1));
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def merge_tracks(gpx_paths: list[str]) -> list[GpsPoint]:
    """Parse and merge multiple GPX files into a single sorted track."""
    all_points = []
    for path in gpx_paths:
        all_points.extend(parse_gpx(path))
    all_points.sort(key=lambda p: p.time)
    return all_points


def main():
    parser = argparse.ArgumentParser(description="Merge GPS track data into recovered Mavica JPEGs")
    subparsers = parser.add_subparsers(dest="command")

    # Merge GPS into photos
    merge_p = subparsers.add_parser("merge", help="Match photos to GPS track")
    merge_p.add_argument("photos", help="Directory of JPEG files")
    merge_p.add_argument("gpx", nargs="+", help="GPX track file(s)")
    merge_p.add_argument(
        "--tolerance",
        default="5m",
        help="Max time difference (e.g., 5m, 30s, 1h). Default: 5m",
    )
    merge_p.add_argument("--use-mtime", action="store_true", help="Use file mtime instead of EXIF")
    merge_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    merge_p.add_argument("--no-interpolate", action="store_true", help="Use nearest point only")

    # Generate map
    map_p = subparsers.add_parser("map", help="Generate HTML map of geotagged photos")
    map_p.add_argument("photos", help="Directory of geotagged JPEG files")
    map_p.add_argument("-o", "--output", default="map.html", help="Output HTML file")
    map_p.add_argument("--title", default="", help="Map title")

    # GPX info
    info_p = subparsers.add_parser("info", help="Show GPX file info")
    info_p.add_argument("gpx", help="GPX file")

    args = parser.parse_args()

    if args.command == "merge":
        # Parse tolerance
        tol_str = args.tolerance.lower().strip()
        if tol_str.endswith("m"):
            tolerance = float(tol_str[:-1]) * 60
        elif tol_str.endswith("h"):
            tolerance = float(tol_str[:-1]) * 3600
        elif tol_str.endswith("s"):
            tolerance = float(tol_str[:-1])
        else:
            tolerance = float(tol_str) * 60  # default minutes

        # Load tracks
        track = merge_tracks(args.gpx)
        print(f"Loaded {len(track)} trackpoints from {len(args.gpx)} GPX file(s)")

        # Find photos
        files = []
        for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
            files.extend(globmod.glob(os.path.join(args.photos, ext)))
        files.sort()
        print(f"Found {len(files)} photo(s)\n")

        matches = match_photos_to_track(
            files,
            track,
            tolerance_seconds=tolerance,
            use_mtime=args.use_mtime,
            interpolate=not args.no_interpolate,
        )

        matched = 0
        for path, match in zip(files, matches):
            name = os.path.basename(path)
            if match:
                matched += 1
                loc = f"{match.point.lat:.6f}, {match.point.lon:.6f}"
                offset = f"{match.offset_seconds:.0f}s offset"
                if args.dry_run:
                    print(f"  MATCH {name}: {loc} ({offset})")
                else:
                    ok, msg = stamp_gps_exif(
                        path,
                        match.point.lat,
                        match.point.lon,
                        match.point.alt,
                        match.point.time,
                    )
                    status = "OK" if ok else "FAIL"
                    print(f"  {status}  {name}: {loc} ({offset})")
            else:
                print(f"  SKIP  {name}: no GPS match within tolerance")

        print(f"\n{matched}/{len(files)} photos matched")
        if args.dry_run:
            print("(dry run — no files modified)")

    elif args.command == "map":
        files = []
        for ext in ("*.jpg", "*.JPG", "*.jpeg", "*.JPEG"):
            files.extend(globmod.glob(os.path.join(args.photos, ext)))
        files.sort()

        # Read GPS from EXIF
        matches = []
        for path in files:
            try:
                from PIL import Image

                img = Image.open(path)
                exif = img.getexif()
                gps_info = exif.get(0x8825)
                if gps_info:
                    lat_ref = gps_info.get(0x0001, "N")
                    lat_dms = gps_info.get(0x0002, ((0, 1), (0, 1), (0, 1)))
                    lon_ref = gps_info.get(0x0003, "E")
                    lon_dms = gps_info.get(0x0004, ((0, 1), (0, 1), (0, 1)))

                    lat = (
                        lat_dms[0][0] / lat_dms[0][1]
                        + lat_dms[1][0] / (lat_dms[1][1] * 60)
                        + lat_dms[2][0] / (lat_dms[2][1] * 3600)
                    )
                    lon = (
                        lon_dms[0][0] / lon_dms[0][1]
                        + lon_dms[1][0] / (lon_dms[1][1] * 60)
                        + lon_dms[2][0] / (lon_dms[2][1] * 3600)
                    )

                    if lat_ref == "S":
                        lat = -lat
                    if lon_ref == "W":
                        lon = -lon

                    matches.append(
                        GpsMatch(
                            photo_path=path,
                            point=GpsPoint(
                                lat=lat, lon=lon, alt=None, time=datetime.now(tz=timezone.utc)
                            ),
                            offset_seconds=0,
                        )
                    )
            except Exception:
                pass

        if matches:
            generate_map_html(matches, args.output, title=args.title)
            print(f"Map generated: {args.output} ({len(matches)} photos)")
        else:
            print("No geotagged photos found.")

    elif args.command == "info":
        points = parse_gpx(args.gpx)
        if not points:
            print("No trackpoints found in GPX file.")
            return

        print(f"GPX: {args.gpx}")
        print(f"  Trackpoints: {len(points)}")
        print(f"  Time range:  {points[0].time.isoformat()} — {points[-1].time.isoformat()}")
        duration = (points[-1].time - points[0].time).total_seconds()
        print(f"  Duration:    {duration / 3600:.1f} hours")

        has_alt = sum(1 for p in points if p.alt is not None)
        if has_alt:
            alts = [p.alt for p in points if p.alt is not None]
            print(f"  Altitude:    {min(alts):.0f}m — {max(alts):.0f}m")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
