# AGENTS.md — mavica-tools

## Project Overview

Floppy disk recovery and troubleshooting toolkit for Sony Mavica cameras (FD5, FD7, FD73, FD88, FD91, etc). Helps diagnose whether issues are caused by the camera, the floppy disk, or the PC floppy drive, and recovers images from damaged disks.

Cross-platform: Windows, macOS, Linux. Managed with `uv`. 195 tests.

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
│   ├── export.py                 # Photo export (organize, rename, contact sheets, watermark)
│   ├── gps.py                    # GPS track merge (GPX parser, timestamp matching, piexif)
│   ├── utils.py                  # Shared utilities (gather_jpegs, get_photo_timestamp, JPEG constants)
│   └── tui/                      # Textual terminal UI
│       ├── app.py                # Main App class, CSS theme, screen registry
│       ├── screens/
│       │   ├── home.py           # Categorized tool menu (4 sections, keyboard shortcuts)
│       │   ├── multipass.py      # Floppy imager with live sector map
│       │   ├── carve.py          # JPEG extraction with image preview
│       │   ├── check.py          # Corruption scanner with progress bar
│       │   ├── repair.py         # Before/after image preview
│       │   ├── swaptest.py       # Interactive test matrix
│       │   ├── workflow.py       # Guided step-by-step recovery
│       │   ├── fat12_screen.py   # FAT12 file browser
│       │   ├── recover_screen.py # Batch recovery pipeline
│       │   ├── stamp_screen.py   # EXIF metadata stamper
│       │   ├── format_screen.py  # Floppy formatter (image + device)
│       │   ├── export_screen.py # Photo export with contact sheets
│       │   ├── gps_screen.py    # GPS track merge
│       │   └── troubleshoot.py  # Interactive troubleshooting wizard
│       └── widgets/
│           ├── sector_map.py     # Colored sector health grid
│           ├── image_preview.py  # Half-block Unicode image renderer
│           └── file_picker.py    # DirectoryTree-based file/folder modal
├── tests/                        # pytest test suite (195 tests)
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
│   ├── test_export.py            # Contact sheets, watermark, rename, organize (18)
│   ├── test_gps.py               # GPX parsing, matching, interpolation, map (15)
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
├── Global bindings: q=quit, h=home, ?=help, s=screenshot
├── SCREENS dict: 17 screen classes
└── Screen navigation via push_screen/pop_screen

Screen data flow (prefill attributes):
  MultipassScreen._merged_path → CarveScreen._prefill_image
  CarveScreen output_dir → CheckScreen._prefill_path
  CheckScreen._bad_files → RepairScreen._prefill_files
  CheckScreen._good_files → StampScreen._prefill_files
  WorkflowScreen: sequential step enabling
```

All long operations run in Textual `Worker` threads. Buttons disable during operations and show loading labels ("Checking...", "Carving...").

### TUI Screen UX Patterns

These patterns were established in the .411 viewer and should be replicated across all tool screens.

**Screen structure** (top to bottom, budget for 24 rows):
1. Header (1 row, docked)
2. Title bar (1 row + 1 row margin-bottom)
3. Input rows (1-2 rows) — keep minimal, combine where possible
4. Action buttons (1 row)
5. Main content area (`height: 1fr` — takes all remaining space)
6. Log (2-3 rows, `border: none`)
7. Footer (1 row, docked)

**Input/Output rows**:
- Label + Input + buttons on same row: `In [path...] Browse Open`
- Use short labels: `In` / `Out`, not "Source Directory" / "Output Directory"
- Browse and Open buttons next to the input they act on (proximity principle)
- Default paths use `mavica_out/` convention (see Output Directory Convention)
- Input for source should default to where previous tool's output goes (chaining)

**Primary action placement**:
- Convert/Run button goes on the output row (configure → act, left to right)
- Use `variant="success"` for the primary action
- Button label should reflect state: "Convert 9 files" not just "Convert"
- Update label dynamically via `_update_convert_label()` pattern

**File list with selection**:
- Two-column layout: file list left (`width: 1fr`), preview right (`width: 40`)
- DataTable with `cursor_type="row"`, columns: Sel / Filename / Size / Status
- Selection markers: `●` (green, selected) / `○` (dim, deselected)
- Selected rows: bold filename. Deselected: dim filename and size.
- All selected by default on load. All/None buttons above the table.
- Space/Enter toggles selection (via `on_key` with focus check, NOT screen-level BINDINGS)
- `on_data_table_row_highlighted` for live preview on cursor movement
- Empty state: "Browse for a directory with .411 files" / "No files found"

**Preview pane**:
- Use `set_pil_image(img, name)` for instant previews (no temp file race)
- Show source filename as preview label, output path below with `→` arrow
- Refresh preview when format dropdown changes (`on_select_changed`)
- `content-align: center top` to center the image
- `margin-bottom: 1` for breathing room

**Keyboard shortcuts**:
- Only use screen-level `BINDINGS` for keys that don't conflict with widget behavior
- Safe for BINDINGS: `escape`, `b` (browse), `F2` (convert), `i` (open in), `o` (open out)
- NOT safe for BINDINGS: `enter`, `space`, `c`, `a`, `n` — these conflict with buttons, inputs, selects
- Use `on_key` with `table.has_focus` check for context-sensitive keys (space/enter toggle)
- Footer shows all BINDINGS automatically. Add inline hints for context keys: "Space/Enter to toggle"

**Select dropdown**:
- Use `Select[str](..., value="default", allow_blank=False, compact=True)` in constructor
- Do NOT set value on mount or via CSS — set in constructor
- Do NOT apply global CSS to Select/SelectCurrent/OptionList — it breaks the overlay

**Progressive disclosure**:
- Files list immediately on valid path input (`on_input_changed` with `os.path.isdir` guard)
- Also list on `on_input_submitted` (Enter) for paths typed manually
- Auto-preview first file on load, auto-focus the table
- Show conversion results in-place (update table status column, don't rebuild)

**Open buttons**:
- Use `explorer.exe` on Windows (not `os.startfile`) to bring window to foreground
- `os.path.abspath()` for relative paths before opening
- `os.makedirs(exist_ok=True)` before opening output dir

**File picker**:
- `allow_new_folder=True` for output directory browsing
- No new folder for input browsing (read-only)

### TUI Layout Guidelines

- **Minimum width**: 80 columns
- **Target width**: 100 columns
- **Target/minimum height**: 24 rows
- All screens must be usable at 80x24. Design for 100x24 as the comfortable default.

**Textual layout fundamentals**:
- Vertical layout (default): widgets auto-expand width but NOT height. Always set `height` explicitly.
- Horizontal layout: inverse — height auto-expands, width does NOT. Set `width` on children.
- `1fr` divides remaining space proportionally. Only works when parent has a fixed/known height.
- `auto` sizes to content. Use `1fr` when you want stretch-to-fill.
- **Do not** use `overflow-y: auto` on Screen — it makes the screen infinitely tall, breaking `1fr`.
- Margins overlap (largest wins, they don't add). Padding does not overlap.
- `box-sizing: border-box` is default — padding/border subtract from declared dimensions.

**Control sizing** (global CSS in `app.py`):
- Buttons: `height: 1`, no border — single-row compact controls
- Inputs: `height: 1`, `border: none`, `padding: 0 0`. Padding > 0 can garble placeholder text at height 1.
- Select: use `compact=True` constructor param for single-row. Do NOT force `height`/`border` via CSS — it breaks the dropdown overlay (SelectOverlay is an OptionList that needs space to render).
- ProgressBar: `height: 1`
- input-row / button-row: `height: 1`, `margin: 0 1 1 1` for side padding
- Do NOT set global `max-height` on OptionList or DataTable — it constrains Select overlays and stretching tables.

**Layout patterns**:
- Main content area: `height: 1fr` — takes all remaining space after fixed-height controls
- Two-column layouts: content on left (`width: 1fr`), preview on right (`width: 40`)
- In horizontal layouts, children need explicit `height` (e.g. `height: 1fr` or `100%`)
- RichLog panels: `max-height: 8`, `border: none`, `margin: 0`, always `wrap=True`
- DataTable in a stretching pane: `height: 1fr` — no global max-height caps
- Docked widgets (Header/Footer): removed from layout flow, fixed to edge, don't scroll

**Textual CSS rules**:
- `DEFAULT_CSS` on widgets has LOWER specificity than app-level `CSS` — app CSS always wins
- Type selectors match base classes (e.g. `Static { }` applies to Button too)
- CSS classes are mutable — change via `add_class()`/`remove_class()`, unlike `id`
- Variables (`$var`) only work in values, never in selectors
- Nesting without `&` creates descendant selectors. Use `&.class` to combine with parent.
- `!important` locks in values — avoid unless resolving genuine conflicts
- Specificity order: most IDs > most classes/pseudo > most types

### Textual Bindings & Actions

- Use `BINDINGS` for keyboard shortcuts — they auto-show in Footer with `show=True`
- **Do not** use `BINDINGS` for context-sensitive keys like Enter/Space that conflict with widget behavior (buttons, inputs, selects). Use `on_key` with focus checks instead.
- Resolution order: focused widget → parent widgets → screen → app
- `priority=True` bypasses widget bindings — use sparingly (global hotkeys only)
- Actions are `action_`-prefixed methods, can be async
- Action string params must be **literals only** — no variables: `"set_bg('red')"` not `"set_bg(color)"`
- Use `check_action(action, params) -> bool|None` to dynamically show/hide/disable keys
- `refresh_bindings()` updates Footer after state changes
- `reactive(value, bindings=True)` auto-refreshes Footer when the reactive changes

### Textual Events & Messages

- Handler naming: `on_` + namespace + message_name in snake_case (e.g. `on_input_changed`, `on_button_pressed`)
- Events bubble up the DOM tree (child → parent) unless `event.stop()` called
- `event.prevent_default()` blocks base class handlers
- `widget.prevent(MessageType)` context manager suppresses messages during mutations
- Use `@on(Button.Pressed, "#submit")` decorator to filter by CSS selector
- Long-running sync code in handlers freezes UI — use workers instead

### Textual Reactivity

- `reactive(default)` triggers `render()` on change. `reactive(default, layout=True)` also recalculates layout. `reactive(default, recompose=True)` rebuilds children.
- `var(default)` — reactive without auto-refresh (for internal state)
- In `__init__`, use `self.set_reactive(MyWidget.attr, value)` — direct assignment triggers watchers before DOM is ready
- Watch methods: `def watch_attr(self, value)` or `def watch_attr(self, old, new)` — Textual inspects the signature
- Validate methods: `def validate_attr(self, value) -> type` — MUST return the (possibly modified) value
- Mutable collections (lists/dicts): call `self.mutate_reactive(MyWidget.attr)` after mutation — Textual can't detect in-place changes
- Data binding: one-way parent→child via `child.data_bind(ParentClass.attr)`. Reverse requires explicit watchers.

### Textual Workers

- `run_worker(coro, exclusive=True)` or `@work(exclusive=True)` for I/O operations
- `exclusive=True` cancels previous worker before starting new one — prevents race conditions
- **Never update UI from worker threads** — use `self.app.call_from_thread(widget.method, args)` or `self.post_message(msg)` (both thread-safe)
- Threaded workers: check `worker.is_cancelled` periodically. Async workers: get `CancelledError` automatically.
- Access results via `Worker.StateChanged` event, not `await worker.wait()` (blocks event loop)
- Workers auto-cancel when their parent widget/screen is removed
- Set `exit_on_error=False` for graceful failure handling

### Textual Widgets Reference

**Select**:
- Use `Select[str]` with type annotation for type safety
- `compact=True` for borderless single-row mode
- Set `value=` in constructor with `allow_blank=False` — first option auto-selects if no value given
- Do NOT set value on mount or via CSS height — set in constructor
- Listen for `Select.Changed` event (has `event.value`)
- `set_options()` resets current selection
- Empty options + `allow_blank=False` raises `EmptySelectError`

**DataTable**:
- `cursor_type="row"` for row selection
- `RowHighlighted` fires on cursor movement (arrow keys), `RowSelected` fires on Enter/click
- Use `update_cell()` for in-place updates instead of clear+rebuild when possible
- `zebra_stripes=True` for visual clarity
- `fixed_rows`/`fixed_columns` for pinned header areas

**Input**:
- Single-line only. `height: 1` + `border: none` for compact mode
- `Changed` fires on every keystroke, `Submitted` fires on Enter, `Blurred` on focus loss
- `validate_on=["changed"|"submitted"|"blur"]` controls validation timing
- `restrict=r"regex"` limits allowed characters
- Text auto-selects on focus; disable with `select_on_focus=False`

**Image preview** (`widgets/image_preview.py`):
- Half-block Unicode chars (U+2580) — 2 vertical pixels per cell, fills widget width
- `set_pil_image(img, name)` for small/decoded images (avoids temp file races)
- `image_path` for file-based images (loads async in worker thread with spinner)
- `self.size.width` is content area width (border/padding already subtracted — do not subtract again)

### Textual Screens

- At least one screen must always exist — popping the last one raises `ScreenStackError`
- `push_screen(screen, callback)` for results — screen calls `dismiss(value)`
- `switch_screen(screen)` replaces top screen (doesn't change stack depth)
- Use `ModalScreen[ReturnType]` for dialogs — darkens background, blocks app bindings
- Named screens in `SCREENS` dict persist across push/pop; unnamed screens are deleted on pop
- `push_screen_wait()` blocks — only use inside workers, never in handlers
- `on_screen_suspend` fires for overlays (command palette, modals) too — check `isinstance(top, ModalScreen)` before cancelling workers
- Modes (`MODES` dict) maintain separate screen stacks per mode

### Textual Command Palette

- Ctrl+P opens the command palette. Override with `COMMAND_PALETTE_BINDING`.
- `get_system_commands(screen)` yields `SystemCommand(title, help_text, callback)` — callback is a callable, not an action string
- Always `yield from super().get_system_commands(screen)` to preserve built-in commands
- Advanced: `Provider` subclass with `async search(query) -> Hits` for dynamic results
- `COMMANDS = App.COMMANDS | {MyProvider}` to register providers

### Textual Testing

- `async with app.run_test(size=(80, 24)) as pilot:` — headless testing
- `await pilot.press("r", "enter")` for key sequences
- `await pilot.click("#submit")` for button clicks
- `await pilot.pause()` to process pending messages before assertions
- Snapshot testing: `assert snap_compare("app.py", press=["1"])` compares rendered output
- All tests must be `async def` and `await` pilot methods

**Floppy I/O in TUI**:
- All reads via `asyncio.to_thread()` — never block the event loop
- `on_sector(idx, state)` callback for live DefragMap updates via `call_from_thread`
- `_StopRequested` exception pattern for cancellation

**Quit behavior**:
- Home screen with no workers: exit immediately, no confirmation
- Sub-screen or workers running: show quit dialog (y/n)
- `self.exit()` for graceful terminal restore, 1s daemon timer `os._exit(0)` fallback

### Output Directory Convention

All tool outputs go under `mavica_out/` by default. Constants are in `utils.py`.

```
mavica_out/
├── photos/       Import destination (JPEGs + .411 from floppy)
├── thumbnails/   Converted .411 thumbnails
├── disk_images/  Multipass .img files (pass_01.img, merged.img)
├── recovery/     Recovery workflow (merged.img, extracted/, carved/)
├── extracted/    FAT12-extracted files with original names
├── repaired/     Repaired JPEGs
└── exported/     Export output (organized, contact sheets)
```

- `mavica_out/photos` is the default input source for .411 converter (thumbnails live alongside JPEGs)
- Tools that chain together share paths: recovery workflow writes to `mavica_out/recovery/`, check/repair reads from there
- Users can override per-tool via CLI `-o` flag or TUI input fields

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

- **Runtime**: Python 3.10+, Pillow>=9.0, piexif>=1.1.3 (GPS EXIF), Textual>=0.50
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
