#!/usr/bin/env python3
"""Значок приложения.

Рисуется кодом, а не хранится картинкой: так его можно поправить и
пересобрать, не открывая редактор.

    python scripts/make_icon.py

Мотив — интерференционные кольца: то, что прибор записывает, и то, из
чего программа считает сдвиг фазы. Сдержанно, без объёма и блеска:
значок должен читаться и в 16 пикселях на панели задач.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "holocyt.ico"

#: Размеры, которые Windows берёт из .ico.
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: Рисуем крупно и уменьшаем — так края выходят гладкими.
SUPER = 8

BG = (23, 33, 47)          # глубокий холодный графит
RING_OUTER = (86, 124, 168)
RING_INNER = (150, 190, 226)
CORE = (226, 238, 248)


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def render(size):
    s = size * SUPER
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Подложка со скруглением: на панели задач квадрат в край выглядит грубо.
    pad = s * 0.045
    d.rounded_rectangle([pad, pad, s - pad, s - pad],
                        radius=s * 0.20, fill=BG)

    cx = cy = s / 2
    # Кольца от внешнего к внутреннему. Их немного и они толстые:
    # при 16 пикселях тонкая штриховка сливается в пятно.
    rings = [(0.355, 0.055, 0.0), (0.255, 0.058, 0.5), (0.155, 0.060, 1.0)]
    for frac, w, t in rings:
        r = s * frac
        width = max(1, round(s * w))
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=_lerp(RING_OUTER, RING_INNER, t), width=width)

    # Ядро — объект, который программа находит на карте фазы.
    r = s * 0.062
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CORE)

    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [render(n) for n in SIZES]
    frames[-1].save(OUT, format="ICO",
                    sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    print(f"  {OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.1f} КБ, "
          f"размеры: {', '.join(str(n) for n in SIZES)}")
    # Отдельный PNG удобен для документации и окна «О программе».
    png = OUT.with_suffix(".png")
    render(256).save(png)
    print(f"  {png.relative_to(ROOT)}  {png.stat().st_size / 1024:.1f} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
