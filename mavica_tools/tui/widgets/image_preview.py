"""Terminal image preview using half-block Unicode characters.

Works on all platforms (Windows Terminal, iTerm2, GNOME Terminal, etc).
Uses upper-half-block (U+2580) with fg/bg colors to get 2 vertical
pixels per character cell.
"""

import os

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text


def _render_half_blocks(img, text, target_w, target_h, pad_left: int = 0):
    """Render an image using half-block characters into a Text object."""
    pixels = img.load()

    for y in range(0, target_h, 2):
        if pad_left > 0:
            text.append(" " * pad_left)
        for x in range(target_w):
            top_r, top_g, top_b = pixels[x, y]
            if y + 1 < target_h:
                bot_r, bot_g, bot_b = pixels[x, y + 1]
            else:
                bot_r, bot_g, bot_b = 0, 0, 0

            fg = f"#{top_r:02x}{top_g:02x}{top_b:02x}"
            bg = f"#{bot_r:02x}{bot_g:02x}{bot_b:02x}"
            text.append("\u2580", style=f"{fg} on {bg}")
        text.append("\n")


class ImagePreview(Widget):
    """Renders an image in the terminal using half-block characters."""

    DEFAULT_CSS = """
    ImagePreview {
        height: auto;
        min-height: 3;
        padding: 0 1;
        border: tall #333333;
    }
    """

    image_path: reactive[str] = reactive("", layout=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rendered: Text | None = None
        self._loading: bool = False
        self._last_path: str = ""
        self._pil_image = None
        self._pil_image_name: str = ""

    def set_pil_image(self, img, name: str = "preview") -> None:
        """Set a PIL Image directly, bypassing file I/O."""
        self._pil_image = img
        self._pil_image_name = name
        self._last_path = ""
        self._loading = False
        self._rendered = self._render_pil(img, name)
        self.image_path = ""
        self.refresh()

    def watch_image_path(self, new_path: str) -> None:
        if not new_path:
            if not self._pil_image:
                self._rendered = None
            return
        if new_path == self._last_path:
            return
        self._last_path = new_path
        self._pil_image = None
        self._rendered = None
        self._loading = True
        self.refresh()
        self.run_worker(self._load_image(new_path), exclusive=True)

    async def _load_image(self, path: str) -> None:
        import asyncio
        try:
            rendered = await asyncio.to_thread(self._render_image, path)
            if self._last_path == path:
                self._rendered = rendered
                self._loading = False
                self.refresh()
        except Exception as e:
            self._rendered = Text(f"  Cannot preview: {e}", style="red")
            self._loading = False
            self.refresh()

    def render(self) -> Text:
        if self._rendered:
            return self._rendered

        if not self.image_path and not self._pil_image:
            return Text("  No image selected", style="dim")

        if self._loading:
            frames = ["|", "/", "-", "\\"]
            import time
            frame = frames[int(time.time() * 4) % len(frames)]
            text = Text()
            text.append(f"  {frame} ", style="bold #ffaa00")
            text.append("Loading preview...", style="dim")
            self.set_timer(0.25, self.refresh)
            return text

        return Text("  No image selected", style="dim")

    def _calc_target(self, orig_w, orig_h):
        """Calculate target pixel dimensions for half-block rendering."""
        target_w = max(20, self.size.width) if self.size.width > 4 else 80
        aspect = orig_h / orig_w
        target_h = int(target_w * aspect)
        if target_h % 2 != 0:
            target_h += 1
        target_w = max(4, target_w)
        target_h = max(2, target_h)
        return target_w, target_h

    def _render_pil(self, img, name: str) -> Text:
        """Render a PIL Image directly using half-blocks."""
        img = img.convert("RGB")
        orig_w, orig_h = img.size

        text = Text()
        text.append(f"  {name}", style="bold")
        text.append(f"  {orig_w}x{orig_h}\n", style="dim")

        target_w, target_h = self._calc_target(orig_w, orig_h)
        img = img.resize((target_w, target_h), 0)  # NEAREST
        _render_half_blocks(img, text, target_w, target_h)

        return text

    def _render_image(self, path: str) -> Text:
        from PIL import Image

        file_size = os.path.getsize(path)
        name = os.path.basename(path)

        img = Image.open(path)
        img = img.convert("RGB")
        orig_w, orig_h = img.size

        text = Text()
        text.append(f"  {name}", style="bold")
        text.append(f"  {orig_w}x{orig_h}  {file_size / 1024:.0f}KB\n", style="dim")

        target_w, target_h = self._calc_target(orig_w, orig_h)
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        _render_half_blocks(img, text, target_w, target_h)

        return text
