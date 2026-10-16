"""Draw the app icon (``pitwall.ico``): the marshal flag of the banner and favicon.

Regenerate with ``uv run --with pillow python packaging/windows/make_icon.py``.
The .ico is committed, so the build does not need Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ORANGE = (242, 107, 29, 255)  # --orange, as in the favicon
INK = (13, 16, 20, 255)  # banner background
SIZE = 256
OUT = Path(__file__).with_name("pitwall.ico")


def draw(size: int = SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 16  # 16x16 grid keeps the shapes on whole pixels at small sizes
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=round(3 * u), fill=ORANGE)
    # Pole and cloth.
    d.rectangle((3 * u, 3 * u, 4.5 * u - 1, 13 * u - 1), fill=INK)
    d.rectangle((4.5 * u, 3 * u, 13 * u - 1, 9 * u - 1), fill=INK)
    # Checks: orange squares cut out of the cloth, two rows.
    cell = 1.5 * u
    for row in range(2):
        for col in range(5):
            if (row + col) % 2 == 0:
                continue
            x = 4.75 * u + col * cell
            y = 4.5 * u + row * cell
            d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=ORANGE)
    return img


def main() -> None:
    draw().save(OUT, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
