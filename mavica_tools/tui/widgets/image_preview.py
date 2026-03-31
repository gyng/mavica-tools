"""Terminal image preview using half-block Unicode characters.

Works on all platforms (Windows Terminal, iTerm2, GNOME Terminal, etc).
Uses upper-half-block (U+2580) with fg/bg colors to get 2 vertical
pixels per character cell.
"""

import os

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text


class ImagePreview(Widget):
    """Renders an image in the terminal using half-block characters."""

    DEFAULT_CSS = """
    ImagePreview {
        height: auto;
        min-height: 3;
        max-height: 30;
        padding: 0 1;
        border: tall #333333;
    }
    """

    image_path: reactive[str] = reactive("", layout=True)

    def render(self) -> Text:
        if not self.image_path:
            return Text("  No image selected", style="dim")

        try:
            return self._render_image()
        except Exception as e:
            return Text(f"  Cannot preview: {e}", style="red")

    def _render_image(self) -> Text:
        from PIL import Image

        # Show file info header
        file_size = os.path.getsize(self.image_path)
        name = os.path.basename(self.image_path)

        img = Image.open(self.image_path)
        img = img.convert("RGB")
        orig_w, orig_h = img.size

        text = Text()
        text.append(f"  {name}", style="bold")
        text.append(f"  {orig_w}x{orig_h}  {file_size / 1024:.0f}KB\n", style="dim")

        # Target size: fit within widget
        target_w = min(60, self.size.width - 4) if self.size.width > 4 else 60
        aspect = img.height / img.width
        target_h = int(target_w * aspect)
        if target_h % 2 != 0:
            target_h += 1
        target_h = min(target_h, 40)  # Cap height

        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        pixels = img.load()

        for y in range(0, target_h, 2):
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

        return text
