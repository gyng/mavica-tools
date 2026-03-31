"""Terminal image preview using half-block Unicode characters.

Works on all platforms (Windows Terminal, iTerm2, GNOME Terminal, etc).
Uses upper-half-block (U+2580) with fg/bg colors to get 2 vertical
pixels per character cell.
"""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text


class ImagePreview(Widget):
    """Renders an image in the terminal using half-block characters."""

    DEFAULT_CSS = """
    ImagePreview {
        height: auto;
        min-height: 5;
        max-height: 30;
        padding: 0 1;
        border: tall #333333;
    }
    """

    image_path: reactive[str] = reactive("", layout=True)

    def render(self) -> Text:
        if not self.image_path:
            return Text("No image selected", style="dim")

        try:
            return self._render_image()
        except Exception as e:
            return Text(f"Cannot preview: {e}", style="red")

    def _render_image(self) -> Text:
        from PIL import Image

        img = Image.open(self.image_path)
        img = img.convert("RGB")

        # Target size: fit within widget, ~60 chars wide, height proportional
        # Each char = 1 pixel wide, 2 pixels tall (half-block trick)
        target_w = min(60, self.size.width - 4) if self.size.width > 4 else 60
        aspect = img.height / img.width
        target_h = int(target_w * aspect)
        # Must be even for half-block pairing
        if target_h % 2 != 0:
            target_h += 1

        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        pixels = img.load()

        text = Text()
        for y in range(0, target_h, 2):
            for x in range(target_w):
                top_r, top_g, top_b = pixels[x, y]
                if y + 1 < target_h:
                    bot_r, bot_g, bot_b = pixels[x, y + 1]
                else:
                    bot_r, bot_g, bot_b = 0, 0, 0

                # Upper half block: fg = top pixel, bg = bottom pixel
                fg = f"#{top_r:02x}{top_g:02x}{top_b:02x}"
                bg = f"#{bot_r:02x}{bot_g:02x}{bot_b:02x}"
                text.append("\u2580", style=f"{fg} on {bg}")
            text.append("\n")

        return text
