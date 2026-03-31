# AGENTS.md — mavica-tools

## Project Overview

Floppy disk recovery and troubleshooting toolkit for Sony Mavica cameras (FD5, FD7, FD73, FD88, FD91, etc). Helps diagnose whether issues are caused by the camera, the floppy disk, or the PC floppy drive, and recovers images from damaged disks.

## Repository Structure

```
mavica-tools/
├── mavica_tools/           # Python package
│   ├── __init__.py         # Package metadata, version
│   ├── cli.py              # Main CLI entry point (mavica <tool>)
│   ├── multipass.py        # Multi-pass floppy disk imager + sector merge
│   ├── carve.py            # JPEG carver for raw disk images
│   ├── check.py            # JPEG corruption checker
│   ├── repair.py           # Partial JPEG repair (multiple strategies)
│   └── swaptest.py         # Cross-camera swap test tracker
├── tests/                  # pytest test suite
│   ├── test_multipass.py   # Sector merge, blank detection, image padding
│   ├── test_carve.py       # JPEG finding, carving, truncation handling
│   ├── test_check.py       # Structural checks, zero-byte detection
│   ├── test_repair.py      # Repair strategies, batch repair
│   └── test_swaptest.py    # DB operations, report analysis, status
├── setup.py                # Package config with console_scripts entry point
├── requirements.txt        # Pillow>=9.0
├── README.md               # User-facing docs
└── mavica-floppy-troubleshooting.md  # Detailed troubleshooting guide
```

## Architecture

### Tool Modules

Each tool module follows the same pattern:
- **Core functions** that accept data and return structured results (no I/O side effects)
- A **CLI wrapper** (`main()`) that parses args, calls core functions, and prints output
- The CLI entry point (`cli.py`) dispatches to each tool's `main()`

Key function signatures (these are the integration points for any UI):

| Module | Function | Input | Output |
|--------|----------|-------|--------|
| multipass | `merge_passes(image_paths)` | list of file paths | `(bytes, list[str])` — merged data + sector status |
| multipass | `sector_is_blank(data)` | 512 bytes | `bool` |
| carve | `find_jpegs(data)` | raw bytes | `list[(offset, length, truncated)]` |
| carve | `carve_jpegs(image_path, output_dir)` | paths | `list[str]` — extracted file paths |
| check | `check_jpeg_structure(filepath)` | file path | `dict` with valid, issues, size, has_soi, has_eoi, dimensions |
| repair | `repair_jpeg(input_path, output_path)` | paths | `(bool, str, str)` — success, output path, message |
| swaptest | `load_db(path)` / `save_db(db, path)` | path | `dict` with cameras, disks, tests |
| swaptest | `cmd_report(db, args)` | db dict | prints analysis (stdout) |

### Constants (multipass.py)

- `SECTOR_SIZE = 512`
- `SECTORS_PER_TRACK = 18`
- `HEADS = 2`, `TRACKS = 80`
- `DISK_SIZE = 1,474,560` (1.44MB)
- `TOTAL_SECTORS = 2880`

### Constants (carve.py)

- `MIN_JPEG_SIZE = 1024` (1KB)
- `MAX_JPEG_SIZE = 307,200` (300KB)
- JPEG SOI: `FF D8 FF`, EOI: `FF D9`

## Development

### Setup

```bash
pip install -e .
pip install pytest
```

### Running Tests

```bash
python -m pytest tests/ -v
```

All tests run without hardware — they create synthetic disk images and JPEG data in temp directories.

### Dependencies

- **Runtime**: Python 3.7+, Pillow>=9.0 (for check/repair pixel decoding)
- **Test**: pytest
- **Hardware** (multipass read only): Linux with `/dev/fd0` and `dd`

## Conventions

- Core functions return structured data, CLI wrappers handle printing
- Tests use `pytest` fixtures with `tempfile.TemporaryDirectory`
- Fake JPEG test data uses `0xAB` fill to avoid accidental marker bytes
- Sector status values: `"good"`, `"recovered"`, `"blank"`, `"conflict"`

## Planned: TUI (Textual)

A terminal UI is planned using Python Textual. It will live in `mavica_tools/tui/` and call the existing core functions directly. Key screens: Home, Multipass, Carve, Check, Repair, Swap Test, Guided Workflow. See `TUI_PLAN.md` for the full design.

When implementing the TUI:
- Do NOT modify core function return types — the TUI must adapt to them
- `multipass.py` needs a callback refactor for progress reporting (add `progress_callback` param, keep `print()` as default)
- `swaptest.py` needs I/O decoupling — separate `input()` prompts from data logic
- All long-running operations must use Textual `Worker` threads
- Image preview uses half-block Unicode characters via Pillow resize
