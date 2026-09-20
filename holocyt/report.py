"""Отчёт по эксперименту в PDF.

Отчёт самодостаточен и показывается заказчику, поэтому в нём нет ни
одной цифры, полученной на синтетических данных: только то, что
измерено на этом конкретном эксперименте. Происхождение каждой группы
величин указано отдельным разделом.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch
from scipy import ndimage as ndi
from skimage import measure, segmentation

from . import __version__, __product__
from . import parameters as pm
from .synth import CLASS_RU, CLASS_COLOR, DISPLAY_CLASSES

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                     "axes.titlesize": 10, "axes.labelsize": 9,
                     "figure.dpi": 110})

A4 = (8.27, 11.69)
CAT_COLOR = {pm.DIRECT: "#2E9E5B", pm.CALIBRATED: "#2F6FD0", pm.DERIVED: "#8A6FC4"}
DISCLAIMER = ("Исследовательское программное обеспечение. "
              "Не является медицинским изделием.")


def overlay_axes(ax, phase, labels, states=None, title="", line_width=2):
    """Кадр с контурами найденных объектов."""
    has = labels is not None and labels.max() > 0
    if has:
        inside = phase[labels > 0]
        vmax = float(np.percentile(inside, 92)) if inside.size else 1.0
    else:
        vmax = float(np.percentile(phase, 99.5))
    vmin = float(np.percentile(phase, 20))
    if vmax <= vmin:
        vmax = vmin + 1e-3
    ax.imshow(phase, cmap="gray", vmin=vmin, vmax=vmax)

    if has:
        bnd = segmentation.find_boundaries(labels, mode="outer")
        halo = ndi.binary_dilation(bnd, iterations=int(line_width))
        core = ndi.binary_dilation(bnd, iterations=max(int(line_width) - 1, 0))
        state_by = {}
        if states is not None:
            for rp, st in zip(measure.regionprops(labels), states):
                state_by[rp.label] = st
        rgba = np.zeros(labels.shape + (4,))
        for rp in measure.regionprops(labels):
            st = state_by.get(rp.label)
            c = matplotlib.colors.to_rgb(
                CLASS_COLOR.get(st, "#3FD07A") if st else "#3FD07A")
            sl = rp.slice
            own = ndi.binary_dilation(labels[sl] == rp.label,
                                      iterations=int(line_width) + 1)
            rgba[sl][own & halo[sl]] = (0.05, 0.05, 0.05, 0.9)
            rgba[sl][own & core[sl]] = (*c, 1.0)
        ax.imshow(rgba)
    ax.set_title(title, fontsize=8)
    ax.set_xticks([]); ax.set_yticks([])


def _legend_handles(present):
    return [Patch(facecolor=CLASS_COLOR[c], label=CLASS_RU[c])
            for c in DISPLAY_CLASSES if c in present]


def _footer(fig):
    fig.text(0.5, 0.017, DISCLAIMER, ha="center", size=7.5, color="#999999")


# --- страница 1: титул -----------------------------------------------------
def _title_page(pdf, ex, meta):
    fig = plt.figure(figsize=A4)
    fig.text(0.5, 0.885, __product__, ha="center", size=32, weight="bold")
    fig.text(0.5, 0.838,
             "Программное обеспечение анализа данных\nцифровой голографической микроскопии",
             ha="center", size=12, color="#444444", linespacing=1.6)
    fig.patches.append(plt.Rectangle((0.13, 0.788), 0.74, 0.0035,
                                     transform=fig.transFigure, color="#2F6FD0"))

    cal = ex.cal
    n_cells = sum(f.n_cells for f in ex.fields)
    w = h = "—"
    if ex.fields:
        h, w = ex.fields[0].labels.shape
    created = meta.get("created", "—")

    rows = [
        ("Эксперимент", ex.name),
        ("Каталог", str(ex.root)),
        ("Дата съёмки", created),
        ("Дата отчёта", datetime.now().strftime("%d.%m.%Y %H:%M")),
        ("Кадров", f"{len(ex.fields)}"),
        ("Размер изображения", f"{w} × {h} пикселей"),
        ("Объектов найдено", f"{n_cells}"),
        ("", ""),
        ("Калибровка", "загружена" if cal.complete else "НЕ НАЙДЕНА"),
        ("Версия программы", __version__),
    ]
    y = 0.70
    for k, v in rows:
        if k:
            fig.text(0.16, y, k, size=9.5, color="#555555")
            fig.text(0.46, y, str(v), size=9.5, weight="bold", wrap=True)
        y -= 0.028

    # Заметный блок о калибровке: от неё зависит, есть ли в отчёте
    # физические величины вообще.
    box_y = y - 0.045
    ok = cal.complete
    fig.patches.append(plt.Rectangle(
        (0.14, box_y), 0.72, 0.075, transform=fig.transFigure,
        facecolor="#EDF9F1" if ok else "#FFF6E5",
        edgecolor="#B6E2C6" if ok else "#E0A32E", lw=1.2))
    if ok:
        txt = ("Калибровка прибора известна. В отчёте приведены физические\n"
               "величины: площадь в мкм², оптическая толщина и объём, сухая масса.")
    else:
        txt = ("Калибровка прибора не найдена. Величины в микрометрах,\n"
               "кубических микрометрах и пикограммах в отчёте ОТСУТСТВУЮТ.\n"
               "Приведены счёт объектов, геометрия в пикселях и сдвиг фазы.")
    fig.text(0.16, box_y + 0.038, txt, size=8.6, va="center",
             color="#226B3F" if ok else "#7A5B12", linespacing=1.6)

    _footer(fig)
    pdf.savefig(fig); plt.close(fig)


# --- страница 2: сводка и графики -----------------------------------------
def _summary_page(pdf, ex):
    fig = plt.figure(figsize=A4)
    fig.suptitle("Сводка по эксперименту", size=13, weight="bold", y=0.965)

    cells = [c for f in ex.fields for c in f.cells]
    calibrated = ex.cal.complete
    rows = [
        ("Кадров", f"{len(ex.fields)}", pm.DIRECT),
        ("Объектов найдено", f"{len(cells)}", pm.DIRECT),
        ("Объектов на кадр, медиана",
         f"{np.median([f.n_cells for f in ex.fields]):.0f}", pm.DIRECT),
        ("Занято площади кадра, %",
         f"{np.mean([f.confluence_pct for f in ex.fields]):.1f}", pm.DIRECT),
        ("Площадь объекта, медиана, пикселей",
         f"{np.median([c['area_px'] for c in cells]):.0f}", pm.DIRECT),
        ("Сумма сдвига фазы, медиана, длин волн",
         f"{np.median([c['phase_sum_waves'] for c in cells]):.1f}", pm.DIRECT),
    ]
    if calibrated:
        rows += [
            ("Площадь объекта, медиана, мкм²",
             f"{np.median([c['area_um2'] for c in cells]):.1f}", pm.CALIBRATED),
            ("Оптическая толщина средняя, медиана, мкм",
             f"{np.median([c['thickness_avg_um'] for c in cells]):.2f}", pm.CALIBRATED),
            ("Оптический объём, медиана, мкм³",
             f"{np.median([c['optical_volume_um3'] for c in cells]):.0f}", pm.CALIBRATED),
            ("Сухая масса, медиана, пг",
             f"{np.median([c['dry_mass_pg'] for c in cells]):.1f}", pm.CALIBRATED),
        ]

    ax = fig.add_axes([0.08, 0.70, 0.84, 0.22]); ax.axis("off")
    tbl = ax.table(cellText=[[r[0], r[1], r[2]] for r in rows],
                   colLabels=["Показатель", "Значение", "Кат."],
                   loc="upper center", cellLoc="left",
                   colWidths=[0.62, 0.26, 0.12])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.55)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#DDDDDD")
        if r == 0:
            cell.set_facecolor("#2F6FD0"); cell.set_text_props(color="white", weight="bold")
        else:
            if c == 1:
                cell.set_text_props(ha="right")
            if c == 2:
                cell.set_text_props(ha="center", weight="bold",
                                    color=CAT_COLOR[rows[r - 1][2]])
            if r % 2 == 0:
                cell.set_facecolor("#F5F7FA")

    unit = "мкм²" if calibrated else "пикселей"
    key = "area_um2" if calibrated else "area_px"

    ax1 = fig.add_axes([0.10, 0.47, 0.36, 0.145])
    ax1.plot([f.n_cells for f in ex.fields], color="#2F6FD0", lw=1.6)
    ax1.set_title("Число объектов по кадрам", fontsize=9)
    ax2 = fig.add_axes([0.58, 0.47, 0.36, 0.145])
    ax2.plot([np.median([c[key] for c in f.cells]) if f.cells else np.nan
              for f in ex.fields], color="#2E9E5B", lw=1.6)
    ax2.set_title(f"Медианная площадь объекта, {unit}", fontsize=9)
    ax3 = fig.add_axes([0.10, 0.265, 0.36, 0.145])
    ax3.hist([c[key] for c in cells], bins=30, color="#2F6FD0", alpha=0.8)
    ax3.set_title(f"Распределение площади, {unit}", fontsize=9)
    ax4 = fig.add_axes([0.58, 0.265, 0.36, 0.145])
    ax4.plot([f.confluence_pct for f in ex.fields], color="#8A6FC4", lw=1.6)
    ax4.set_title("Доля площади кадра, занятая объектами, %", fontsize=9)
    for a in (ax1, ax2, ax3, ax4):
        a.grid(alpha=0.25, lw=0.5); a.spines[["top", "right"]].set_visible(False)
        a.tick_params(labelsize=7.5)
    for a in (ax1, ax2, ax4):
        a.set_xlabel("номер кадра в порядке файлов", fontsize=7.5)

    fig.text(0.10, 0.205,
             "Кадры отложены в порядке файлов. Порядок съёмки во времени в данных\n"
             "эксперимента не восстанавливается, поэтому ось подписана именно так.",
             size=7.8, color="#777777", linespacing=1.5)

    # Состав популяции — только если он вообще вычислялся.
    if calibrated:
        tot = len(cells) or 1
        counts = {}
        for f in ex.fields:
            for k, v in f.state_counts().items():
                counts[k] = counts.get(k, 0) + v
        axc = fig.add_axes([0.10, 0.095, 0.84, 0.055])
        left = 0.0
        for c in DISPLAY_CLASSES:
            p = 100.0 * counts.get(c, 0) / tot
            if p <= 0:
                continue
            axc.barh([0], [p], left=left, color=CLASS_COLOR[c], label=CLASS_RU[c])
            left += p
        axc.set_xlim(0, 100); axc.set_yticks([]); axc.tick_params(labelsize=7.5)
        axc.set_title("Состав популяции по оценке ГОЛОЦИТа, % (категория C)", fontsize=9)
        axc.legend(ncol=6, fontsize=7, frameon=False,
                   loc="upper center", bbox_to_anchor=(0.5, -0.35))
        axc.spines[["top", "right", "left"]].set_visible(False)

    _footer(fig)
    pdf.savefig(fig); plt.close(fig)


# --- страница 3: представительные кадры -----------------------------------
def _fields_page(pdf, ex, n=4):
    fields = ex.fields
    if not fields:
        return
    # Берём кадры с разной заполненностью: так виднее, как работает разметка.
    order = np.argsort([f.confluence_pct for f in fields])
    idx = sorted({int(order[0]), int(order[len(order) // 3]),
                  int(order[2 * len(order) // 3]), int(order[-1])})[:n]
    fig, axes = plt.subplots(2, 2, figsize=(A4[0], A4[1] * 0.66))
    fig.suptitle("Представительные кадры с разметкой", size=13, weight="bold", y=0.975)
    present = set()
    for ax, i in zip(axes.ravel(), idx):
        fr = fields[i]
        present |= set(fr.states) if fr.calibrated else set()
        overlay_axes(ax, fr.phase, fr.labels,
                     fr.states if fr.calibrated else None,
                     title=f"{Path(fr.name).name} — объектов {fr.n_cells}, "
                           f"занято {fr.confluence_pct:.0f} %")
    for ax in axes.ravel()[len(idx):]:
        ax.axis("off")
    if present:
        fig.legend(handles=_legend_handles(present), loc="lower center",
                   ncol=6, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 0.03))
    fig.tight_layout(rect=[0, 0.06, 1, 0.955])
    _footer(fig)
    pdf.savefig(fig); plt.close(fig)


# --- страница 4: происхождение величин -------------------------------------
def _provenance_page(pdf, ex, meta):
    fig = plt.figure(figsize=A4)
    fig.suptitle("Происхождение величин и метаданные", size=13, weight="bold", y=0.965)
    y = 0.90

    fig.text(0.08, y, "Источники значений", size=10.5, weight="bold", color="#2F6FD0")
    y -= 0.028
    blocks = [
        ("Импортировано из Hstudio", pm.DIRECT,
         "Метаданные эксперимента из imagedb.xml и, если он есть, паспорт\n"
         "съёмки из DBTransferInfo.xml: размер пикселя камеры, увеличение\n"
         "объектива, длина волны, показатели преломления."),
        ("Вычислено из карты фазы", pm.DIRECT,
         "Счёт объектов, геометрия в пикселях, статистика сдвига фазы.\n"
         "Эти величины не зависят от калибровки и верны всегда."),
        ("Вычислено при наличии калибровки", pm.CALIBRATED,
         "Площадь в мкм², оптическая толщина и объём, разность хода,\n"
         "сухая масса. Без калибровки не вычисляются вовсе."),
        ("Вычислено ГОЛОЦИТом", pm.DERIVED,
         "Оценки формы, шероховатости и текстуры, состояние клетки.\n"
         "Это наши показатели. Даже при совпадении названия с параметром\n"
         "штатного ПО их определения могут расходиться."),
    ]
    for title, cat, body in blocks:
        fig.patches.append(plt.Rectangle((0.08, y - 0.004), 0.012, 0.012,
                                         transform=fig.transFigure,
                                         color=CAT_COLOR[cat]))
        fig.text(0.105, y, title, size=9.2, weight="bold")
        y -= 0.021
        fig.text(0.105, y, body, size=8, va="top", color="#555555", linespacing=1.6)
        y -= 0.021 * (body.count("\n") + 1) + 0.016

    y -= 0.01
    fig.text(0.08, y, "Калибровка прибора", size=10.5, weight="bold", color="#2F6FD0")
    y -= 0.022
    for r in ex.cal.rows():
        if not r["required"] and r["value"] is None:
            continue
        v = "—" if r["value"] is None else f"{r['value']:.6g}"
        fig.text(0.10, y, r["name"], size=8, color="#555555")
        fig.text(0.62, y, v, size=8, weight="bold")
        fig.text(0.74, y, r["status_ru"], size=7.5, color="#777777")
        y -= 0.019

    y -= 0.015
    fig.text(0.08, y, "Метаданные эксперимента", size=10.5, weight="bold", color="#2F6FD0")
    y -= 0.022
    for k, v in list(meta.items())[:8]:
        fig.text(0.10, y, str(k), size=8, color="#555555")
        fig.text(0.42, y, str(v)[:60], size=8)
        y -= 0.019

    y -= 0.018
    fig.text(0.08, y, "Ограничения", size=10.5, weight="bold", color="#2F6FD0")
    y -= 0.022
    fig.text(0.10, y,
             "• Разметка объектов выполняется автоматически и не проверялась оператором.\n"
             "• Показатели категории «вычислено ГОЛОЦИТом» не воспроизводят определения\n"
             "  штатного ПО прибора и не должны сравниваться с ним напрямую.\n"
             "• Состояние клеток определяется моделью, обученной на модельных данных;\n"
             "  для конкретной клеточной линии её следует дообучить.\n"
             "• Результат носит исследовательский характер.",
             size=8, va="top", color="#555555", linespacing=1.7)

    _footer(fig)
    pdf.savefig(fig); plt.close(fig)


def build_report(ex, out_path, meta=None):
    """Собирает отчёт по проанализированному эксперименту."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(meta or {})
    h = getattr(ex, "hstudio", None)
    if h is not None:
        for k, v in h.provenance.values.items():
            if v.source == "measured":
                meta.setdefault(k, v.value)

    with PdfPages(out_path) as pdf:
        _title_page(pdf, ex, meta)
        _summary_page(pdf, ex)
        _fields_page(pdf, ex)
        _provenance_page(pdf, ex, meta)
        d = pdf.infodict()
        d["Title"] = f"{__product__} — отчёт: {ex.name}"
        d["Author"] = __product__
        d["Subject"] = "Анализ данных цифровой голографической микроскопии"
        d["CreationDate"] = datetime.now()
    return out_path
