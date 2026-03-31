# AGENTS.md — mavica-tools

## Project Overview

Floppy disk recovery and troubleshooting toolkit for Sony Mavica cameras (FD5, FD7, FD73, FD88, FD91, etc). Helps diagnose whether issues are caused by the camera, the floppy disk, or the PC floppy drive, and recovers images from damaged disks.

Cross-platform: Windows, macOS, Linux. Managed with `uv`. 160 tests.

## Repository Structure

```
mavica-tools/
├── .github/workflows/ci.yml     # GitHub Actions CI (Linux/Win/Mac × Py 3.11/3.12)
├── mavica_tools/                 # Python package
│   ├── __init__.py               # Package version
│   ├── cli.py                    # Main CLI entry point — dispatches to all tools
│   ├── multipass.py              # Multi-pass floppy imager + sector merge
│   ├── carve.py                  # JPEG carver for raw disk images
│   ├── check.py                  # JPEG corruption checker
│   ├── repair.py                 # Partial JPEG repair (3 strategies)
│   ├── swaptest.py               # Cross-camera swap test tracker
│   ├── fat12.py                  # FAT12 filesystem parser + deleted file recovery
│   ├── recover.py                # Batch recovery pipeline (merge→extract→check→repair)
│   ├── format.py                 # Mavica-compatible FAT12 floppy formatter
│   ├── stamp.py                  # EXIF metadata stamper for bare Mavica JPEGs
│   ├── detect.py                 # Floppy drive auto-detection (Linux/Win/Mac)
│   ├── history.py                # Disk health history tracking + degradation detection
│   ├── report.py                 # HTML recovery report generator
│   └── tui/                      # Textual terminal UI
│       ├── app.py                # Main App class, CSS theme, screen registry
│       ├── screens/
│       │   ├── home.py           # Tool menu (10 options, keyboard shortcuts)
│       │   ├── multipass.py      # Floppy imager with live sector map
│       │   ├── carve.py          # JPEG extraction with image preview
│       │   ├── check.py          # Corruption scanner with progress bar
│       │   ├── repair.py         # Before/after image preview
│       │   ├── swaptest.py       # Interactive test matrix
│       │   ├── workflow.py       # Guided step-by-step recovery
│       │   ├── fat12_screen.py   # FAT12 file browser
│       │   ├── recover_screen.py # Batch recovery pipeline
│       │   ├── stamp_screen.py   # EXIF metadata stamper
│       │   └── format_screen.py  # Floppy formatter (image + device)
│       └── widgets/
│           ├── sector_map.py     # Colored sector health grid
│           ├── image_preview.py  # Half-block Unicode image renderer
│           └── file_picker.py    # DirectoryTree-based file/folder modal
├── tests/                        # pytest test suite (160 tests)
│   ├── test_multipass.py         # Sector merge, blank detection, image padding (10)
│   ├── test_carve.py             # JPEG finding, carving, boundary detection (8)
│   ├── test_check.py             # Structural checks, zero-byte detection (10)
│   ├── test_repair.py            # Repair strategies, batch repair (7)
│   ├── test_swaptest.py          # DB ops, report analysis, status tracking (14)
│   ├── test_fat12.py             # FAT12 parsing, cluster chains, extraction (13)
│   ├── test_format.py            # Boot sector, FAT structure, image creation (15)
│   ├── test_stamp.py             # EXIF tags, model shorthands, batch stamp (12)
│   ├── test_recover.py           # Full pipeline, carve fallback (4)
│   ├── test_detect.py            # Drive detection mocking (4)
│   ├── test_history.py           # Snapshots, comparison, persistence (12)
│   ├── test_report.py            # HTML generation, XSS escaping (8)
│   └── test_tui.py               # Headless screen navigation + widget tests (31)
├── screenshots/                  # SVG screenshots for README
├── pyproject.toml                # uv/hatch config, dependencies, pytest config
├── README.md                     # User guide
├── AGENTS.md                     # This file
├── TUI_PLAN.md                   # Original TUI design document
└── mavica-floppy-troubleshooting.md  # Hardware troubleshooting guide
```

## Architecture

### Design Pattern

Every tool module follows the same pattern:

1. **Core functions** — accept data, return structured results, no side effects
2. **CLI wrapper** (`main()`) — argparse, calls core functions, prints output
3. **TUI screen** — imports core functions, runs them in Textual Workers

The CLI entry point (`cli.py`) dispatches `mavica <tool>` to each module's `main()`. The TUI (`tui/app.py`) registers screen classes and manages navigation.

### Core Function Signatures

These are the integration points. The TUI calls these directly — no subprocess wrapping.

| Module | Function | Returns |
|--------|----------|---------|
| `multipass` | `merge_passes(image_paths: list[str])` | `(bytes, list[str])` — merged data + sector status per sector |
| `multipass` | `sector_is_blank(data: bytes)` | `bool` |
| `carve` | `find_jpegs(data: bytes)` | `list[(offset, length, truncated)]` |
| `carve` | `carve_jpegs(image_path, output_dir)` | `list[str]` — extracted file paths |
| `check` | `check_jpeg_structure(filepath)` | `dict` — valid, issues, size, has_soi, has_eoi, dimensions, pixel_test |
| `repair` | `repair_jpeg(input_path, output_path)` | `(bool, str, str)` — success, path, message |
| `fat12` | `parse_disk_image(image_path)` | `(list[FileEntry], list[int], bytes)` — files, FAT table, raw data |
| `fat12` | `extract_with_names(image_path, output_dir, ...)` | `list[(name, path, size, is_deleted)]` |
| `recover` | `recover_from_images(paths, output_dir, use_fat)` | `dict` — summary with total/good/repaired/failed counts |
| `format` | `create_disk_image(volume_label)` | `bytes` — 1.44MB FAT12 disk image |
| `stamp` | `stamp_jpeg(path, output, model, date, ...)` | `(bool, str, str)` — success, path, message |
| `detect` | `detect_floppy_drives()` | `list[FloppyDrive]` |
| `history` | `record_snapshot(label, sector_status, ...)` | `DiskSnapshot` |
| `history` | `compare_snapshots(older, newer)` | `dict` — readable_change, degrading |
| `report` | `generate_report(output_path, sector_status, files, ...)` | `str` — output path |
| `swaptest` | `load_db(path)` / `save_db(db, path)` | `dict` |

### Constants

**multipass.py**: `SECTOR_SIZE=512`, `SECTORS_PER_TRACK=18`, `HEADS=2`, `TRACKS=80`, `DISK_SIZE=1,474,560`, `TOTAL_SECTORS=2880`

**carve.py**: `MIN_JPEG_SIZE=1024`, `MAX_JPEG_SIZE=307,200`, SOI=`FF D8 FF`, EOI=`FF D9`

**fat12.py**: `FAT_OFFSET=1`, `FATS_COUNT=2`, `SECTORS_PER_FAT=9`, `ROOT_DIR_ENTRIES=224`, `DATA_START_SECTOR=33`

### TUI Architecture

```
MavicaApp (app.py)
├── CSS theme (retro green/amber on black)
├── Global bindings: q=quit, h=home, ?=help
├── SCREENS dict: 11 screen classes
└── Screen navigation via push_screen/pop_screen

Screen data flow (prefill attributes):
  MultipassScreen._merged_path → CarveScreen._prefill_image
  CarveScreen output_dir → CheckScreen._prefill_path
  CheckScreen._bad_files → RepairScreen._prefill_files
  CheckScreen._good_files → StampScreen._prefill_files
  WorkflowScreen: sequential step enabling
```

All long operations run in Textual `Worker` threads. Buttons disable during operations and show loading labels ("Checking...", "Carving...").

### Cross-Platform Floppy Access

| Platform | Device path | Read method | Notes |
|----------|-------------|-------------|-------|
| Linux | `/dev/fd0` | `dd` subprocess | Also scans `/sys/block` for USB floppies |
| Windows | `\\.\A:` | Python `open(device, "rb")` | Needs Administrator |
| macOS | `/dev/diskN` | `dd` subprocess | Uses `diskutil` for detection |

## Development

### Setup

```bash
uv sync              # install all deps
uv sync --extra dev  # include pytest + pytest-asyncio
```

### Running Tests

```bash
uv run --extra dev pytest -v           # all 160 tests
uv run --extra dev pytest tests/test_tui.py -v  # TUI tests only (~13s)
uv run --extra dev pytest -k "not tui" -v       # fast unit tests only (~1s)
```

All tests run without hardware. Synthetic disk images and JPEG data are created in temp directories. TUI tests use Textual's headless `run_test()` / `pilot` API.

### Dependencies

- **Runtime**: Python 3.10+, Pillow>=9.0, Textual>=0.50
- **Dev**: pytest>=7.0, pytest-asyncio>=0.23
- **CI**: GitHub Actions (Linux/Windows/macOS × Python 3.11/3.12)

### Adding a New Tool

1. Create `mavica_tools/newtool.py` with core functions + `main()` CLI wrapper
2. Add `subparsers.add_parser(...)` and dispatch in `cli.py`
3. Create `mavica_tools/tui/screens/newtool_screen.py`
4. Register in `app.py` SCREENS dict and imports
5. Add to home screen TOOLS list in `screens/home.py`
6. Write tests in `tests/test_newtool.py`

## Conventions

- Core functions return structured data; CLI wrappers handle printing
- Tests use `pytest` fixtures with `tempfile.TemporaryDirectory`
- Fake JPEG test data uses `0xAB` fill to avoid accidental marker bytes (`FF D8`, `FF D9`)
- Sector status values: `"good"`, `"recovered"`, `"blank"`, `"conflict"`
- TUI screens use `_prefill_*` attributes for cross-screen data passing
- Mavica model shorthands: `"fd7"` → `"Sony Mavica MVC-FD7"` (see `stamp.py` MAVICA_MODELS)
- FAT12 deleted file recovery: first byte reconstructed as `M` for MVC-*.JPG pattern
- HTML report uses `html.escape()` on all user input to prevent XSS
