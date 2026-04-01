"""Mavica camera database — parsed from mavica-db.tsv.

Single source of truth for camera specs, used by stamping,
autodetection, and UI.
"""

import csv
import os
from dataclasses import dataclass


@dataclass
class MavicaModel:
    """Parsed camera model from the database."""

    key: str  # e.g. "fd7", "cd300"
    model: str  # e.g. "Sony Mavica MVC-FD7"
    year: int
    megapixels: float
    resolution: tuple[int, int]  # (width, height)
    interlaced: bool
    optical_zoom: float
    focal_length_mm: float  # min focal length
    focal_length_max_mm: float  # max focal length
    focal_length_35mm: int  # estimated 35mm equivalent (from min)
    aperture_max: float  # widest aperture (smallest f-number)
    aperture_min: float  # narrowest aperture at tele end
    manual_focus: bool
    macro: bool
    exposure_modes: str
    spot_metering: bool
    white_balance: str
    manual_white_bal: bool
    viewfinder: bool
    steadyshot: bool
    picture_effects: bool
    multi_mode: bool
    thread_size: float | None  # filter thread in mm, None if none
    sensor_size: str  # e.g. "1/4", "1/2.7"
    media: str  # e.g. "Floppy only", "CD", "Floppy & MS slot"
    fd_speed: str  # e.g. "1x", "4x", "" for CD models
    usb: bool
    pics_per_disk: int
    manual_url: str
    iso: int = 100  # all Mavicas are ISO 100
    flash: bool = True  # all models have flash


def _parse_aperture(s: str) -> tuple[float, float]:
    """Parse aperture string like 'f2.0-2.1' or 'f2.8' into (max, min)."""
    s = s.strip().lower().replace("f", "")
    if "-" in s:
        parts = s.split("-")
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return 2.8, 2.8
    try:
        v = float(s)
        return v, v
    except ValueError:
        return 2.8, 2.8


def _parse_bool(s: str) -> bool:
    """Parse various yes/no values."""
    return s.strip().lower() not in ("no", "none", "none (auto only)", "")


_CROP_FACTORS = {
    "1/4": 11.2,
    "1/3": 8.6,
    "1/3.6": 10.0,
    "1/2.7": 6.7,
    "1/1.8": 4.8,
}


def _actual_focal_from_35mm(focal_35mm: float, sensor_size: str) -> float:
    """Convert 35mm equivalent focal length back to actual lens focal length."""
    factor = _CROP_FACTORS.get(sensor_size, 7.0)
    return round(focal_35mm / factor, 1)


def _load_db() -> dict[str, MavicaModel]:
    """Load and parse the TSV database."""
    tsv_path = os.path.join(os.path.dirname(__file__), "..", "mavica-db.tsv")
    if not os.path.exists(tsv_path):
        # Try package-relative path
        tsv_path = os.path.join(os.path.dirname(__file__), "mavica-db.tsv")
    if not os.path.exists(tsv_path):
        return {}

    models = {}
    with open(tsv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            raw_model = row.get("Model", "").strip()
            if not raw_model:
                continue

            key = raw_model.lower()
            year = int(row.get("Year", 0) or 0)
            h_res = int(row.get("H. Res", 0) or 0)
            v_res = int(row.get("V. Res", 0) or 0)
            mp = float(row.get("MP", 0) or 0)

            aperture_str = row.get("Max Aperture", "f2.8")
            ap_max, ap_min = _parse_aperture(aperture_str)

            focal_min = float(row.get("Min Focal Length", 0) or 0)
            focal_max = float(row.get("Max Focal Length", 0) or 0)
            sensor_size = row.get("Sensor Size", "1/4").strip()

            optical_zoom = float(row.get("Optical Zoom", 1) or 1)

            thread_str = row.get("Thread Size", "").strip()
            thread_size = None
            if thread_str and thread_str.lower() not in ("none", ""):
                try:
                    # Handle things like "37", "52", "None (40.5mm lens cap)"
                    thread_size = float(thread_str.split("(")[0].strip() or 0) or None
                except ValueError:
                    thread_size = None

            media = row.get("Memory Format(s)", "").strip()
            fd_speed = row.get("FD Speed", "").strip()

            # Determine model prefix for full name
            if key.startswith("cd"):
                full_model = f"Sony Mavica MVC-CD{raw_model[2:]}"
            else:
                full_model = f"Sony Mavica MVC-{raw_model.upper()}"

            # DB focal lengths are 35mm equivalents — convert to actual
            actual_focal_min = _actual_focal_from_35mm(focal_min, sensor_size)
            actual_focal_max = _actual_focal_from_35mm(focal_max, sensor_size)

            models[key] = MavicaModel(
                key=key,
                model=full_model,
                year=year,
                megapixels=mp,
                resolution=(h_res, v_res),
                interlaced=row.get("Interlaced", "").strip().lower() == "yes",
                optical_zoom=optical_zoom,
                focal_length_mm=actual_focal_min,
                focal_length_max_mm=actual_focal_max,
                focal_length_35mm=round(focal_min),
                aperture_max=ap_max,
                aperture_min=ap_min,
                manual_focus=_parse_bool(row.get("Manual Focus", "No")),
                macro=_parse_bool(row.get("Macro", "No")),
                exposure_modes=row.get("Exposure Modes", "Auto only").strip(),
                spot_metering=_parse_bool(row.get("Spot Metering", "No")),
                white_balance=row.get("White Balance Presets", "").strip(),
                manual_white_bal=_parse_bool(row.get("Manual White Bal", "No")),
                viewfinder=_parse_bool(row.get("Viewfinder", "No")),
                steadyshot=_parse_bool(row.get("SteadyShot", "No")),
                picture_effects=_parse_bool(row.get("Picture Effects", "No")),
                multi_mode=_parse_bool(row.get("Multi-Mode", "No")),
                thread_size=thread_size,
                sensor_size=sensor_size,
                media=media,
                fd_speed=fd_speed,
                usb=_parse_bool(row.get("USB", "No")),
                pics_per_disk=int(row.get("Pics/Disk", 0) or 0),
                manual_url=row.get("Manual", "").strip(),
            )

    return models


# Module-level singleton — loaded once on first import
MODELS: dict[str, MavicaModel] = _load_db()

# Convenience: same interface as the old MAVICA_SPECS for backward compat
MAVICA_SPECS: dict[str, dict] = {}
for _k, _m in MODELS.items():
    MAVICA_SPECS[_k] = {
        "model": _m.model,
        "year": _m.year,
        "resolution": _m.resolution,
        "sensor": f'{_m.sensor_size}" CCD',
        "focal_length_mm": _m.focal_length_mm,
        "focal_length_35mm": _m.focal_length_35mm,
        "aperture_max": _m.aperture_max,
        "aperture_min": _m.aperture_min,
        "zoom_optical": _m.optical_zoom,
        "zoom_digital": 1.0,  # not in DB, not needed for EXIF
        "iso": _m.iso,
        "flash": _m.flash,
        "media": _m.media,
    }
