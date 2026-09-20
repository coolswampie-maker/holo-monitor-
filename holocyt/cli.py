"""Командный интерфейс ГОЛОЦИТа.

    python3 -m holocyt analyze demo_data/cytotox_demo
    python3 -m holocyt image снимок.tif
    python3 -m holocyt demo
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

from . import __product__, __version__
from ._compat import can_print_unicode, ascii_safe
from .optics import OpticalConfig
from .experiment import Experiment, read_phase
from .pipeline import analyze_field
from .report import build_report
from .synth import CLASS_RU

METHOD_RU = {
    "ml": "обученный попиксельный классификатор + водоразделы",
    "otsu": "порог Оцу (как в штатном ПО)",
    "minimum_error": "порог минимальной ошибки (как в штатном ПО)",
    "adaptive_gaussian": "адаптивный гауссов порог (как в штатном ПО)",
}


def _optics_from_args(a):
    return OpticalConfig(wavelength_um=a.wavelength, pixel_size_um=a.pixel_size,
                         n_cell=a.n_cell, n_medium=a.n_medium, alpha_um3_pg=a.alpha)


def _add_optics_args(p):
    g = p.add_argument_group(
        "калибровка прибора (по умолчанию НЕ подставляется: если её нет "
        "в данных, физические величины не вычисляются)")
    g.add_argument("--pixel-size", type=float, default=None,
                   help="размер пикселя в плоскости объекта, мкм")
    g.add_argument("--wavelength", type=float, default=None, help="длина волны, мкм")
    g.add_argument("--n-cell", type=float, default=None,
                   help="показатель преломления клеток")
    g.add_argument("--n-medium", type=float, default=None,
                   help="показатель преломления среды")


def _calibration_from_args(a, base=None):
    """Собирает калибровку: из данных прибора плюс то, что задал оператор."""
    from .calibration import from_user
    if any(v is not None for v in (a.pixel_size, a.wavelength, a.n_cell, a.n_medium)):
        return from_user(pixel_size_um=a.pixel_size, wavelength_um=a.wavelength,
                         n_cell=a.n_cell, n_medium=a.n_medium, base=base)
    return base


def cmd_analyze(a):
    """Анализ эксперимента Hstudio: разбор, расчёт, отчёт."""
    from .experiment import Experiment
    from .importers.hstudio import detect, load_experiment, read_phase_matrix

    t0 = time.time()
    path = Path(a.path)
    if detect(path) is None:
        print(f"  {path} не распознан как эксперимент Hstudio.")
        print("  Ожидается каталог с imagedb.xml и Storage/, либо с")
        print("  DBTransferInfo.xml, либо с файлами *.fmx / *.bin.")
        return 1

    h = load_experiment(path)
    pmx = read_phase_matrix(h.phase_files[0])
    cal = _calibration_from_args(a, h.calibration)

    print(f"{__product__} {__version__}\n")
    print(f"  Эксперимент:      {h.name}")
    print(f"  Кадров:           {h.n_frames}")
    print(f"  Размер кадра:     {pmx.width} x {pmx.height} пикселей")
    print(f"  Формат:           {pmx.version}")
    print(f"  Источники:        {', '.join(h.sources_found)}")
    print(f"  Калибровка:       {cal.status_line()}")
    if not cal.complete:
        mark = "⚠" if can_print_unicode() else "!"
        print(f"\n  {mark} Физические величины (мкм, мкм³, пг) вычисляться НЕ будут.")
        print(f"    Счёт объектов, геометрия в пикселях и сдвиг фазы — как обычно.")
        print(f"    Задать калибровку: --pixel-size, --wavelength, --n-cell, --n-medium")
    print()

    ex = Experiment.from_hstudio(path, cal=cal)
    fill, empty = ("█", "·") if can_print_unicode() else ("#", ".")

    def prog(i, n, name, fr):
        k = int(24 * i / n)
        print(f"\r  [{fill * k}{empty * (24 - k)}] {i:3d}/{n}  "
              f"{Path(name).name:16s} объектов {fr.n_cells:4d}    ", end="", flush=True)

    ex.run(method=a.method, progress=prog, min_area_px=a.min_area_px)
    cells = [c for f in ex.fields for c in f.cells]
    print(f"\n\n  Найдено объектов: {len(cells)} за {time.time() - t0:.1f} с\n")

    import numpy as _np
    rows = [("Объектов на кадр, медиана",
             f"{_np.median([f.n_cells for f in ex.fields]):.0f}", "A"),
            ("Занято площади кадра, %",
             f"{_np.mean([f.confluence_pct for f in ex.fields]):.1f}", "A"),
            ("Площадь объекта, медиана, пикселей",
             f"{_np.median([c['area_px'] for c in cells]):.0f}", "A"),
            ("Сумма сдвига фазы, медиана, длин волн",
             f"{_np.median([c['phase_sum_waves'] for c in cells]):.1f}", "A")]
    if cal.complete:
        rows += [("Площадь объекта, медиана, мкм²",
                  f"{_np.median([c['area_um2'] for c in cells]):.1f}", "B"),
                 ("Оптическая толщина средняя, мкм",
                  f"{_np.median([c['thickness_avg_um'] for c in cells]):.2f}", "B"),
                 ("Оптический объём, медиана, мкм³",
                  f"{_np.median([c['optical_volume_um3'] for c in cells]):.0f}", "B"),
                 ("Сухая масса, медиана, пг",
                  f"{_np.median([c['dry_mass_pg'] for c in cells]):.1f}", "B")]
    w = max(len(r[0]) for r in rows) + 2
    for label, val, cat in rows:
        print(f"  {label:<{w}s} {val:>12s}   [{cat}]")
    print("\n  A — измерено из карты фазы, B — требует калибровки прибора,")
    print("  C — вычислено ГОЛОЦИТом (в таблице клеток)")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    if ex.skipped:
        mark = "⚠" if can_print_unicode() else "!"
        print(f"\n  {mark} Обработано {len(ex.fields)} из {len(ex.records)} кадров, "
              f"пропущено {len(ex.skipped)}:")
        for f, why in ex.skipped[:5]:
            print(f"      {f} — {why}")

    from .export import export_all
    res = export_all(ex, out)
    print(f"\n  Таблица объектов: {res['csv']}")
    print(f"                    {res['rows']} строк, {res['cols']} колонок")
    if res["metadata"]:
        print(f"  Метаданные:       {res['metadata']}")
    if not a.no_report:
        from .report import build_report
        pdf = build_report(ex, out / f"{ex.name}_отчёт.pdf")
        print(f"  Отчёт:            {pdf}")
    return 0


def cmd_image(a):
    cfg = _optics_from_args(a)
    phase = read_phase(a.path, a.phase_unit)
    t = time.time()
    fr = analyze_field(phase, name=Path(a.path).name, cfg=cfg, method=a.method,
                       min_area_um2=a.min_area, with_baseline=a.compare)
    print(f"{Path(a.path).name}: {fr.n_cells} клеток за {time.time() - t:.1f} с")
    print(f"  жизнеспособность   {fr.viability_pct:6.1f} %")
    print(f"  конфлюентность     {fr.confluence_pct:6.1f} %")
    print(f"  сухая масса всего  {fr.total_dry_mass_pg:8.0f} пг")
    if fr.n_cells:
        print(f"  средняя на клетку  {fr.total_dry_mass_pg / fr.n_cells:8.1f} пг")
    print("  состав популяции:")
    for k, v in sorted(fr.state_counts().items(), key=lambda kv: -kv[1]):
        print(f"    {CLASS_RU[k]:>10s}  {v:4d}  ({100 * v / fr.n_cells:.1f} %)")
    if a.compare and fr.baseline_labels is not None:
        n_base = int(fr.baseline_labels.max())
        print(f"\n  для сравнения, пороговый метод (Оцу): {n_base} клеток "
              f"({n_base - fr.n_cells:+d} к результату ГОЛОЦИТа)")

    if a.save_overlay:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from .report import overlay_axes, _legend_handles
        fig, ax = plt.subplots(figsize=(11, 8))
        overlay_axes(ax, fr.phase, fr.labels, fr.states, title=fr.name)
        fig.legend(handles=_legend_handles(set(fr.states)), loc="lower center",
                   ncol=5, frameon=False)
        fig.tight_layout(rect=[0, 0.05, 1, 1])
        fig.savefig(a.save_overlay, dpi=130); plt.close(fig)
        print(f"\n  разметка сохранена: {a.save_overlay}")
    return 0


def cmd_import(a):
    """Импорт эксперимента Hstudio: разбор, отчёт о происхождении, манифест."""
    from .importers.hstudio import detect, load_experiment, read_phase_matrix, write_manifest
    from . import __product__, __version__
    path = Path(a.path)
    print(f"{__product__} {__version__} — импорт данных Hstudio\n")
    kind = detect(path)
    if kind is None:
        print(f"  {path} не распознан как данные Hstudio.")
        print("  Ожидается каталог с imagedb.xml и Storage/, либо с")
        print("  DBTransferInfo.xml, либо просто с файлами *.fmx / *.bin.")
        return 1

    ex = load_experiment(path)
    print(f"  Раскладка:        {kind}")
    print(f"  Эксперимент:      {ex.name}")
    print(f"  Карт фазы:        {ex.n_frames}")
    if ex.database:
        print(f"  База Hstudio:     {ex.database.name} (не читается, см. ниже)")
    pm = read_phase_matrix(ex.phase_files[0])
    print(f"  Версия формата:   {pm.version}")
    print(f"  Размер кадра:     {pm.width} x {pm.height} пикселей")
    print(f"  Диапазон фазы:    {pm.phase.min():+.3f} .. {pm.phase.max():+.3f} "
          f"долей длины волны\n")

    print("  ПРОИСХОЖДЕНИЕ ВЕЛИЧИН")
    for line in ex.provenance.report().splitlines():
        print("  " + line)
    w = ex.warnings()
    if w:
        mark = "⚠" if can_print_unicode() else "!"
        print(f"\n  {mark} Подставленные значения — НЕ измерения прибора:")
        for x in w:
            print(f"    - {x}")

    if not a.no_manifest:
        out, n = write_manifest(ex)
        print(f"\n  Манифест: {out}  ({n} кадров)")
        print(f"  Запуск анализа:  python3 -m holocyt analyze \"{path}\"")
    return 0


def cmd_demo(a):
    root = Path(__file__).resolve().parent.parent
    demo = root / "demo_data" / "cytotox_demo"
    if not (demo / "manifest.csv").exists():
        print("Демонстрационные данные не найдены, генерирую…\n")
        # Вызываем напрямую, без порождения процесса: в переносимой сборке
        # sys.executable указывает на лаунчер, а не на интерпретатор.
        sys.path.insert(0, str(root / "scripts"))
        import make_demo
        make_demo.main(out=str(demo))
    a.path = str(demo)
    return cmd_analyze(a)


def cmd_selftest(a):
    from .selftest import run
    return 1 if run(verbose=not a.brief) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="holocyt",
        description=f"{__product__} {__version__} — анализ безмаркерных "
                    f"голографических изображений клеточных культур")
    ap.add_argument("--version", action="version", version=f"{__product__} {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = dict(method=dict(choices=list(METHOD_RU), default="ml",
                              help="метод сегментации"))

    p = sub.add_parser("analyze", help="проанализировать эксперимент Hstudio")
    p.add_argument("path", help="каталог эксперимента Hstudio")
    p.add_argument("--method", **common["method"])
    p.add_argument("--min-area-px", type=int, default=500,
                   help="минимальная площадь объекта, пикселей")
    p.add_argument("-o", "--out", default="out", help="каталог для результатов")
    p.add_argument("--no-report", action="store_true", help="не формировать PDF")
    _add_optics_args(p); p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("image", help="проанализировать одно изображение")
    p.add_argument("path")
    p.add_argument("--method", **common["method"])
    p.add_argument("--min-area", type=float, default=40.0)
    p.add_argument("--compare", action="store_true",
                   help="дополнительно посчитать пороговым методом")
    p.add_argument("--save-overlay", metavar="ФАЙЛ.png",
                   help="сохранить изображение с разметкой")
    _add_optics_args(p); p.set_defaults(func=cmd_image)

    p = sub.add_parser("import-hstudio",
                       help="разобрать эксперимент Hstudio и составить манифест")
    p.add_argument("path", help="каталог эксперимента или выгрузки базы")
    p.add_argument("--no-manifest", action="store_true",
                   help="только отчёт, без создания manifest.csv")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("selftest", help="проверить работоспособность на этой машине")
    p.add_argument("--brief", action="store_true", help="кратко, без подробностей")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("demo", help="запустить демонстрационный эксперимент")
    p.add_argument("--method", **common["method"])
    p.add_argument("--min-area", type=float, default=40.0)
    p.add_argument("-o", "--out", default="out")
    p.add_argument("--no-report", action="store_true")
    _add_optics_args(p); p.set_defaults(func=cmd_demo)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
