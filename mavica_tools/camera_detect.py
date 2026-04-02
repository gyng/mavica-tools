"""Auto-detect which Mavica camera model produced a set of files.

Uses multiple heuristics:
1. Existing EXIF Make/Model tags (definitive)
2. JPEG resolution (strong — each model has fixed resolution)
3. Companion file types (.411 thumbnails, .htm indexes, .mov videos)
4. JPEG file size patterns
5. Filename patterns (MVC-NNN vs PICT0NNN)
"""

import contextlib
import glob as globmod
import os
from dataclasses import dataclass

from mavica_tools.mavica_db import MAVICA_SPECS

# Which models produce which companion file types
# FD7x series introduced .411 thumbnails
# FD8x series added .htm index pages and .mov video
_HAS_411 = {
    "fd71",
    "fd73",
    "fd75",
    "fd83",
    "fd85",
    "fd87",
    "fd88",
    "fd90",
    "fd91",
    "fd92",
    "fd95",
    "fd97",
    "fd100",
    "fd200",
}
_HAS_HTM = {
    "fd83",
    "fd85",
    "fd87",
    "fd88",
    "fd90",
    "fd91",
    "fd92",
    "fd95",
    "fd97",
    "fd100",
    "fd200",
}
_HAS_MOV = {
    "fd83",
    "fd85",
    "fd87",
    "fd88",
    "fd90",
    "fd91",
    "fd92",
    "fd95",
    "fd97",
    "fd100",
    "fd200",
}

# Resolution -> set of models (from DB — many resolutions are now unique)
_RES_MAP: dict[tuple[int, int], set[str]] = {}
for _k, _v in MAVICA_SPECS.items():
    _r = _v["resolution"]
    _RES_MAP.setdefault(_r, set()).add(_k)


@dataclass
class DetectionResult:
    """Result of camera auto-detection."""

    model: str | None  # Best-guess model shorthand (e.g. "fd7"), None if unknown
    confidence: str  # "exact", "likely", "guess", "unknown"
    candidates: list[str]  # All plausible models (may be >1)
    reason: str  # Human-readable explanation of how it was detected


def detect_camera(files: list[str]) -> DetectionResult:
    """Detect which Mavica camera produced these files.

    Args:
        files: List of file paths (JPEGs, .411s, etc.)

    Returns:
        DetectionResult with best guess and explanation.
    """
    if not files:
        return DetectionResult(None, "unknown", [], "No files to analyze")

    jpegs = [f for f in files if f.lower().endswith((".jpg", ".jpeg"))]
    all_files_lower = {os.path.basename(f).lower() for f in files}

    # 1. Check existing EXIF
    exif_model = _check_exif(jpegs)
    if exif_model:
        return exif_model

    # 2. Get resolution from first readable JPEG
    resolution = _get_resolution(jpegs)

    # 3. Check companion files in the same directory
    companion_dir = os.path.dirname(files[0]) if files else ""
    has_411 = any(f.endswith(".411") for f in all_files_lower)
    has_htm = any(f.endswith(".htm") or f.endswith(".html") for f in all_files_lower)
    has_mov = any(f.endswith(".mov") for f in all_files_lower)

    # Also check the source directory for companions not in the file list
    if companion_dir and os.path.isdir(companion_dir):
        if not has_411:
            has_411 = bool(globmod.glob(os.path.join(companion_dir, "*.411")))
        if not has_htm:
            has_htm = bool(
                globmod.glob(os.path.join(companion_dir, "*.htm"))
                or globmod.glob(os.path.join(companion_dir, "*.HTM"))
            )
        if not has_mov:
            has_mov = bool(
                globmod.glob(os.path.join(companion_dir, "*.mov"))
                or globmod.glob(os.path.join(companion_dir, "*.MOV"))
            )

    # 4. Filename pattern (reserved for future scoring)
    _has_mvc = any(f.startswith("mvc") for f in all_files_lower)
    _has_pict = any(f.startswith("pict") for f in all_files_lower)

    # 5. Average JPEG file size (reserved for future scoring)
    _avg_size = _avg_file_size(jpegs)

    # Build candidate set
    candidates = set(MAVICA_SPECS.keys())
    reasons = []

    # Filter by resolution (strongest signal)
    if resolution and resolution in _RES_MAP:
        candidates &= _RES_MAP[resolution]
        reasons.append(f"{resolution[0]}x{resolution[1]} resolution")

    # Filter by companion files
    if has_411:
        candidates &= _HAS_411
        reasons.append(".411 thumbnails found")
    else:
        # No .411 files — exclude models that always produce them
        # (only early models: fd5, fd7, fd51 don't make .411s)
        no_411_models = set(MAVICA_SPECS.keys()) - _HAS_411
        if candidates & no_411_models:
            # Only narrow if it doesn't eliminate all candidates
            narrowed = candidates & no_411_models
            if narrowed:
                candidates = narrowed
                reasons.append("no .411 thumbnails")

    if has_htm:
        candidates &= _HAS_HTM
        reasons.append(".htm index found")

    if has_mov:
        candidates &= _HAS_MOV
        reasons.append(".mov video found")

    # Determine confidence
    sorted_candidates = sorted(candidates)
    if not sorted_candidates:
        return DetectionResult(None, "unknown", [], "Could not match any camera model")

    if len(sorted_candidates) == 1:
        model = sorted_candidates[0]
        spec = MAVICA_SPECS[model]
        return DetectionResult(
            model,
            "likely",
            sorted_candidates,
            f"Detected {spec['model']}: {', '.join(reasons)}",
        )

    # Multiple candidates — pick the most common/popular model as default
    # Prefer models that are more distinctive
    model = sorted_candidates[0]  # alphabetical first as fallback
    spec = MAVICA_SPECS[model]
    reason_str = ", ".join(reasons) if reasons else "resolution match"
    return DetectionResult(
        model,
        "guess",
        sorted_candidates,
        f"Best guess {spec['model']} (also possible: "
        f"{', '.join(MAVICA_SPECS[c]['model'] for c in sorted_candidates[1:])}). "
        f"Based on: {reason_str}",
    )


def _check_exif(jpegs: list[str]) -> DetectionResult | None:
    """Check if any JPEG already has EXIF camera info."""
    try:
        from PIL import Image
    except ImportError:
        return None

    for path in jpegs[:5]:  # Check first 5 files
        try:
            img = Image.open(path)
            exif = img.getexif()
            if not exif:
                continue
            model_str = str(exif.get(0x0110, "") or "").strip()  # TAG_MODEL
            if not model_str:
                continue
            # Try to match to a known model
            model_lower = model_str.lower()
            for key, spec in MAVICA_SPECS.items():
                if key in model_lower or spec["model"].lower() in model_lower:
                    return DetectionResult(
                        key,
                        "exact",
                        [key],
                        f"EXIF says {model_str} (from {os.path.basename(path)})",
                    )
            # Has EXIF but not a known Mavica model
            return DetectionResult(
                None,
                "exact",
                [],
                f"EXIF camera: {model_str} (not a known Mavica model)",
            )
        except Exception:
            continue
    return None


def _get_resolution(jpegs: list[str]) -> tuple[int, int] | None:
    """Get the resolution of the first readable JPEG."""
    try:
        from PIL import Image
    except ImportError:
        return None

    for path in jpegs[:3]:
        try:
            img = Image.open(path)
            return img.size
        except Exception:
            continue
    return None


def _avg_file_size(jpegs: list[str]) -> int:
    """Get average JPEG file size in bytes."""
    if not jpegs:
        return 0
    sizes = []
    for f in jpegs[:20]:
        with contextlib.suppress(OSError):
            sizes.append(os.path.getsize(f))
    return sum(sizes) // len(sizes) if sizes else 0
