"""File and directory picker modal widget."""

import os
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
        height: 30;
        border: thick #33ff33;
        background: #0a0a0a;
        padding: 1 2;
    }

    #picker-title {
        text-style: bold;
        color: #ffaa00;
        height: 1;
        margin-bottom: 1;
    }

    #picker-tree {
        height: 1fr;
        border: tall #333333;
        margin-bottom: 1;
    }

    #picker-path {
        height: 3;
        margin-bottom: 1;
    }

    #picker-new-folder-row {
        height: auto;
        margin-bottom: 1;
    }

    #picker-new-folder-name {
        width: 1fr;
    }

    #picker-buttons {
        height: auto;
        min-height: 3;
        align: right middle;
    }

    #picker-buttons Button {
        min-width: 12;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        start_path: str = ".",
        extensions: tuple[str, ...] = (),
        title: str = "Select file",
        select_directory: bool = False,
        allow_new_folder: bool = False,
    ):
        super().__init__()
        self._start_path = start_path
        self._extensions = extensions
        self._title = title
        self._select_directory = select_directory
        self._allow_new_folder = allow_new_folder
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
            if self._allow_new_folder:
                with Horizontal(id="picker-new-folder-row"):
                    yield Input(
                        placeholder="New folder name...",
                        id="picker-new-folder-name",
                    )
                    yield Button("New Folder", variant="warning", id="picker-new-folder")
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
        elif event.button.id == "picker-new-folder":
            self._create_new_folder()

    def _create_new_folder(self) -> None:
        """Create a new folder inside the currently selected directory."""
        name = self.query_one("#picker-new-folder-name", Input).value.strip()
        if not name:
            self.notify("Enter a folder name", severity="warning")
            return

        # Determine parent: use selected path if it's a dir, otherwise use start path
        parent = self.query_one("#picker-path", Input).value.strip()
        if parent and os.path.isfile(parent):
            parent = os.path.dirname(parent)
        if not parent or not os.path.isdir(parent):
            parent = self._start_path

        new_path = os.path.join(parent, name)
        try:
            os.makedirs(new_path, exist_ok=True)
            self.query_one("#picker-path", Input).value = new_path
            self._selected_path = new_path
            # Refresh the tree to show the new folder
            tree = self.query_one("#picker-tree", FilteredDirectoryTree)
            tree.reload()
            self.query_one("#picker-new-folder-name", Input).value = ""
            self.notify(f"Created: {new_path}", timeout=2)
        except OSError as e:
            self.notify(f"Cannot create folder: {e}", severity="error")

    def action_cancel(self) -> None:
        self.dismiss("")
