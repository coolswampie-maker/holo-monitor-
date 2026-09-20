#!/usr/bin/env python3
"""Сборка документации в PDF из размеченного текста.

Свой минимальный отрисовщик вместо внешнего конвертера: тянуть в
поставку ещё одну зависимость ради трёх документов не хочется, а
matplotlib уже есть и корректно рисует кириллицу.

Поддерживается: заголовки #, ##, ###, абзацы, списки, нумерованные
списки, таблицы, код в ``` и разделители ---.
"""

import re
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holocyt.version import PRODUCT, VERSION            # noqa: E402

plt.rcParams.update({"font.family": "DejaVu Sans"})

def _plain(s):
    """Убирает разметку, которую отрисовщик не поддерживает."""
    return s.replace("**", "").replace("`", "")


A4 = (8.27, 11.69)
LEFT, RIGHT, TOP, BOTTOM = 0.10, 0.92, 0.93, 0.075
ACCENT = "#2F6FD0"
DISCLAIMER = ("Исследовательское программное обеспечение. "
              "Не является медицинским изделием.")


class Doc:
    def __init__(self, pdf, title):
        self.pdf = pdf
        self.title = title
        self.page = 0
        self.fig = None
        self.y = 0.0
        self._new_page()

    def _new_page(self):
        if self.fig is not None:
            self._footer()
            self.pdf.savefig(self.fig)
            plt.close(self.fig)
        self.fig = plt.figure(figsize=A4)
        self.page += 1
        self.y = TOP
        if self.page > 1:
            self.fig.text(LEFT, 0.955, self.title, size=7.5, color="#999999")
            self.fig.patches.append(plt.Rectangle(
                (LEFT, 0.948), RIGHT - LEFT, 0.0015,
                transform=self.fig.transFigure, color="#E3E8EF"))

    def _footer(self):
        self.fig.text(0.5, 0.035, DISCLAIMER, ha="center", size=7, color="#AAAAAA")
        self.fig.text(RIGHT, 0.035, str(self.page), ha="right", size=8, color="#888888")
        self.fig.text(LEFT, 0.035, f"{PRODUCT} {VERSION}", size=7, color="#AAAAAA")

    def space(self, dy):
        self.y -= dy
        if self.y < BOTTOM:
            self._new_page()

    def text(self, s, size=9.5, color="#222222", weight="normal",
             indent=0.0, wrap=95, line=0.0175):
        for para in s.split("\n"):
            lines = textwrap.wrap(para, wrap) or [""]
            for ln in lines:
                if self.y < BOTTOM:
                    self._new_page()
                self.fig.text(LEFT + indent, self.y, ln, size=size,
                              color=color, weight=weight, va="top")
                self.y -= line

    def heading(self, s, level=1):
        s = _plain(s)
        sizes = {1: 17, 2: 12.5, 3: 10.5}
        # Новую страницу начинаем только если на текущей почти не
        # осталось места. Иначе короткие документы раздуваются.
        if level == 1 and self.page > 1 and self.y < TOP - 0.55:
            self._new_page()
        self.space(0.022 if level > 1 else 0.008)
        if self.y < BOTTOM + 0.08:
            self._new_page()
        self.fig.text(LEFT, self.y, s, size=sizes[level], weight="bold",
                      color=ACCENT if level < 3 else "#222222", va="top")
        self.y -= 0.024 if level == 1 else 0.020
        if level == 1:
            self.fig.patches.append(plt.Rectangle(
                (LEFT, self.y + 0.008), RIGHT - LEFT, 0.002,
                transform=self.fig.transFigure, color=ACCENT))
            self.y -= 0.012

    def bullet(self, s, marker="•", indent=0.02):
        s = _plain(s)
        lines = textwrap.wrap(s, 88) or [""]
        for i, ln in enumerate(lines):
            if self.y < BOTTOM:
                self._new_page()
            if i == 0:
                self.fig.text(LEFT + indent, self.y, marker, size=9.5,
                              color=ACCENT, va="top")
            self.fig.text(LEFT + indent + 0.022, self.y, ln, size=9.5, va="top")
            self.y -= 0.0175

    def code(self, lines):
        self.space(0.008)
        h = 0.0155 * len(lines) + 0.012
        if self.y - h < BOTTOM:
            self._new_page()
        self.fig.patches.append(plt.Rectangle(
            (LEFT, self.y - h + 0.008), RIGHT - LEFT, h,
            transform=self.fig.transFigure, facecolor="#F5F7FA",
            edgecolor="#E3E8EF"))
        yy = self.y - 0.004
        for ln in lines:
            self.fig.text(LEFT + 0.012, yy, ln, size=8.5,
                          family="DejaVu Sans Mono", va="top")
            yy -= 0.0155
        self.y = yy - 0.008

    def table(self, rows):
        if not rows:
            return
        self.space(0.010)
        ncol = len(rows[0])
        h = 0.020 * len(rows) + 0.008
        if self.y - h < BOTTOM:
            self._new_page()
        ax = self.fig.add_axes([LEFT, self.y - h, RIGHT - LEFT, h])
        ax.axis("off")
        t = ax.table(cellText=[r[1:] if False else r for r in rows[1:]],
                     colLabels=rows[0], loc="upper center", cellLoc="left")
        t.auto_set_font_size(False); t.set_fontsize(8); t.scale(1, 1.4)
        for (r, c), cell in t.get_celld().items():
            cell.set_edgecolor("#DDDDDD")
            if r == 0:
                cell.set_facecolor(ACCENT)
                cell.set_text_props(color="white", weight="bold")
            elif r % 2 == 0:
                cell.set_facecolor("#F7F9FC")
        self.y -= h + 0.010

    def image(self, path, height=0.30):
        p = Path(path)
        if not p.exists():
            return
        import matplotlib.image as mpimg
        img = mpimg.imread(str(p))
        ar = img.shape[0] / img.shape[1]
        w = RIGHT - LEFT
        h = min(height, w * ar * A4[0] / A4[1])
        if self.y - h < BOTTOM:
            self._new_page()
        ax = self.fig.add_axes([LEFT, self.y - h, w, h])
        ax.imshow(img); ax.axis("off")
        self.y -= h + 0.014

    def close(self):
        self._footer()
        self.pdf.savefig(self.fig)
        plt.close(self.fig)


def title_page(doc, title, subtitle, extra=()):
    f = doc.fig
    f.text(0.5, 0.74, PRODUCT, ha="center", size=34, weight="bold")
    f.text(0.5, 0.705, "Программное обеспечение анализа данных\n"
                       "цифровой голографической микроскопии",
           ha="center", size=11, color="#555555", linespacing=1.6)
    f.patches.append(plt.Rectangle((0.22, 0.665), 0.56, 0.003,
                                   transform=f.transFigure, color=ACCENT))
    f.text(0.5, 0.60, title, ha="center", size=20, weight="bold")
    if subtitle:
        f.text(0.5, 0.565, subtitle, ha="center", size=11, color="#666666")
    y = 0.48
    for k, v in extra:
        f.text(0.32, y, k, size=9.5, color="#666666", ha="right")
        f.text(0.35, y, v, size=9.5, weight="bold")
        y -= 0.026
    doc.y = 0.0
    doc._new_page()


def render(md_text, out_pdf, title, subtitle="", extra=(), images=None):
    images = images or {}
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_pdf) as pdf:
        doc = Doc(pdf, f"{PRODUCT} · {title}")
        title_page(doc, title, subtitle, extra)

        lines = md_text.splitlines()
        i, table, code = 0, [], None
        while i < len(lines):
            ln = lines[i].rstrip()
            if ln.startswith("```"):
                if code is None:
                    code = []
                else:
                    doc.code(code); code = None
                i += 1; continue
            if code is not None:
                code.append(ln); i += 1; continue
            if ln.startswith("|"):
                cells = [c.strip() for c in ln.strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    table.append(cells)
                i += 1
                if i >= len(lines) or not lines[i].startswith("|"):
                    doc.table(table); table = []
                continue
            if ln.startswith("!["):
                m = re.search(r"\((.+?)\)", ln)
                if m:
                    doc.image(images.get(m.group(1), m.group(1)))
                i += 1; continue
            if ln.startswith("### "):
                doc.heading(ln[4:], 3)
            elif ln.startswith("## "):
                doc.heading(ln[3:], 2)
            elif ln.startswith("# "):
                doc.heading(ln[2:], 1)
            elif ln.startswith("- ") or ln.startswith("* "):
                doc.bullet(ln[2:])
            elif re.match(r"^\d+\. ", ln):
                doc.bullet(ln[ln.index(".") + 2:], marker=ln[:ln.index(".") + 1])
            elif ln.strip() == "---":
                doc.space(0.012)
            elif ln.strip():
                doc.text(_plain(ln))
            else:
                doc.space(0.010)
            i += 1
        if table:
            doc.table(table)
        doc.close()
    return out_pdf
