"""File and directory picker modal widget."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Static, Button, Input


class FilteredDirectoryTree(DirectoryTree):
    """DirectoryTree that filters by file extensions."""

    def __init__(self, path: str, extensions: tuple[str, ...] = (), **kwargs):
        super().__init__(path, **kwargs)
        self._extensions = tuple(e.lower() for e in extensions)

    def filter_paths(self, paths):
        if not self._extensions:
            return paths
        return [
            p for p in paths
            if p.is_dir() or p.suffix.lower() in self._extensions
        ]


class FilePicker(ModalScreen[str]):
    """Modal file/directory picker.

    Returns the selected path as a string, or empty string if cancelled.
    """

    DEFAULT_CSS = """
    FilePicker {
        align: center middle;
    }

    #picker-container {
        width: 70;
        height: 28;
        border: thick #33ff33;
        background: #0a0a0a;
        padding: 1 2;
    }

    #picker-title {
        text-style: bold;
        color: #ffaa00;
        margin-bottom: 1;
    }

    #picker-tree {
        height: 18;
        border: tall #333333;
        margin-bottom: 1;
    }

    #picker-path {
        margin-bottom: 1;
    }

    #picker-buttons {
        height: 3;
        align: right middle;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        start_path: str = ".",
        extensions: tuple[str, ...] = (),
        title: str = "Select file",
        select_directory: bool = False,
    ):
        super().__init__()
        self._start_path = start_path
        self._extensions = extensions
        self._title = title
        self._select_directory = select_directory
        self._selected_path = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-container"):
            yield Static(self._title, id="picker-title")
            yield FilteredDirectoryTree(
                self._start_path,
                extensions=self._extensions,
                id="picker-tree",
            )
            yield Input(
                value=self._start_path,
                placeholder="Selected path",
                id="picker-path",
            )
            with Horizontal(id="picker-buttons"):
                yield Button("Cancel", variant="default", id="picker-cancel")
                yield Button("Select", variant="success", id="picker-select")

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self._selected_path = str(event.path)
        self.query_one("#picker-path", Input).value = self._selected_path

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        if self._select_directory:
            self._selected_path = str(event.path)
            self.query_one("#picker-path", Input).value = self._selected_path

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-select":
            path = self.query_one("#picker-path", Input).value.strip()
            self.dismiss(path)
        elif event.button.id == "picker-cancel":
            self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")
