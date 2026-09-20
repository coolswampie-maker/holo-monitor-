#!/usr/bin/env python3
"""Регрессионный набор ГОЛОЦИТа.

Запуск:  python tests/test_release.py

Проверяет то, что можно проверить без микроскопа и без Windows:
импорт реальных данных, поведение с калибровкой и без, устойчивость
к повреждённым файлам, пути с кириллицей и пробелами, выгрузку,
детерминированность.

Ничего не имитирует: все проверки идут на настоящих кадрах M4.
"""

import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

_here = Path(__file__).resolve().parents[1]
ROOT = _here / "app" if (_here / "app" / "run.py").exists() else _here
sys.path.insert(0, str(ROOT))

from holocyt._compat import setup as _setup        # noqa: E402
_setup()

DEMO = ROOT / "demo_data" / "M4_demo_8"
FULL = ROOT / "demo_data" / "M4 Example woundhealing"
MCF = ROOT / "recovery" / "extracted_1"

TESTS = []


class Skip(Exception):
    """Проверку выполнить нечем: нет данных, на которых она держится.

    Пройденной такая проверка не считается. Раньше подобные случаи
    возвращали строку «проверка пропущена» и попадали в число PASS,
    из-за чего приёмочный итог был завышен.
    """


def test(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


def need_demo():
    """Каталог настоящих кадров M4 или SKIP, если его нет."""
    if not DEMO.exists():
        raise Skip(f"нет демонстрационного эксперимента: {DEMO}")
    return DEMO


def _cal():
    from holocyt.calibration import from_user
    return from_user(0.3359375, 0.633, 1.38, 1.34)


def _run(path, cal=None, limit=3):
    from holocyt.experiment import Experiment
    if not Path(path).exists():
        raise Skip(f"нет данных для прогона: {path}")
    ex = Experiment.from_hstudio(path, cal=cal)
    ex.records = ex.records[:limit]
    return ex.run()


# --- импорт и распознавание ------------------------------------------------
@test("Распознавание каталога Hstudio")
def _detect():
    from holocyt.importers.hstudio import detect
    got = detect(need_demo())
    if got != "experiment":
        raise AssertionError(f"ожидалось 'experiment', получено {got!r}")
    if detect(ROOT / "holocyt") is not None:
        raise AssertionError("обычный каталог принят за эксперимент")
    return f"{DEMO.name} -> experiment"


@test("Чтение настоящей карты фазы .fmx")
def _read():
    from holocyt.importers.hstudio import load_experiment, read_phase_matrix
    ex = load_experiment(need_demo())
    pm = read_phase_matrix(ex.phase_files[0])
    if (pm.width, pm.height) != (1024, 1024):
        raise AssertionError(f"неожиданный размер {pm.width}x{pm.height}")
    if not (-2 < pm.phase.min() < pm.phase.max() < 5):
        raise AssertionError(f"неправдоподобный диапазон фазы "
                             f"{pm.phase.min()}..{pm.phase.max()}")
    return f"{ex.n_frames} кадров, {pm.width}x{pm.height}, {pm.version}"


@test("Отказ от неподдержанного формата .bin")
def _bin_refused():
    from holocyt.importers.hstudio import load_experiment, UnsupportedFormat
    if not MCF.exists():
        raise Skip(f"нет набора MCF-10A с файлами .bin: {MCF}")
    try:
        load_experiment(MCF)
    except UnsupportedFormat:
        return "каталог с .bin корректно отклонён с пояснением"
    raise AssertionError("программа приняла неподдержанный формат")


@test("Импорт калибровки из DBTransferInfo.xml")
def _cal_import():
    from holocyt.importers.hstudio import read_transfer_info
    from holocyt.calibration import from_transfer_xml, MEASURED, CALCULATED
    if not (MCF / "DBTransferInfo.xml").exists():
        raise Skip(f"нет файла паспорта: {MCF / 'DBTransferInfo.xml'}")
    _, optics = read_transfer_info(MCF)
    cal = from_transfer_xml(optics, str(MCF / "DBTransferInfo.xml"))
    if not cal.complete:
        raise AssertionError(f"калибровка неполная: {cal.missing}")
    if cal.pixel_size_um.status != CALCULATED:
        raise AssertionError("размер пикселя должен быть выведен из измеренных")
    if cal.wavelength_um.status != MEASURED:
        raise AssertionError("длина волны должна быть измеренной")
    return (f"пиксель {cal.pixel_size_um.value:.4f} мкм [{cal.pixel_size_um.status}], "
            f"длина волны {cal.wavelength_um.value} мкм [{cal.wavelength_um.status}]")


# --- поведение с калибровкой и без ----------------------------------------
@test("Работа БЕЗ калибровки: физических величин нет")
def _no_cal():
    ex = _run(DEMO, cal=None, limit=2)
    if ex.calibrated:
        raise AssertionError("калибровка не должна быть найдена")
    cells = [c for f in ex.fields for c in f.cells]
    if not cells:
        raise AssertionError("объекты не найдены")
    forbidden = [k for k in ("area_um2", "dry_mass_pg", "optical_volume_um3",
                             "thickness_avg_um") if k in cells[0]]
    if forbidden:
        raise AssertionError(f"вычислены величины без калибровки: {forbidden}")
    if "area_px" not in cells[0] or "phase_sum_waves" not in cells[0]:
        raise AssertionError("не вычислены величины категории A")
    return f"{len(cells)} объектов, {len(cells[0])} колонок, ни одной физической"


@test("Работа С калибровкой: физические величины появились")
def _with_cal():
    ex = _run(DEMO, cal=_cal(), limit=2)
    if not ex.calibrated:
        raise AssertionError("калибровка должна быть полной")
    cells = [c for f in ex.fields for c in f.cells]
    for k in ("area_um2", "dry_mass_pg", "optical_volume_um3"):
        if k not in cells[0]:
            raise AssertionError(f"не вычислено: {k}")
    import numpy as np
    m = float(np.median([c["dry_mass_pg"] for c in cells]))
    if not (10 < m < 2000):
        raise AssertionError(f"неправдоподобная сухая масса: {m:.1f} пг")
    return f"{len(cells)} объектов, медиана сухой массы {m:.1f} пг"


# --- устойчивость ----------------------------------------------------------
@test("Повреждённый кадр пропускается, остальные считаются")
def _damaged():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "опыт"
        shutil.copytree(need_demo(), work)
        files = sorted((work / "Storage" / "PhaseMatrixStorage").rglob("*.fmx"))
        files[1].write_bytes(b"\x00" * 4096)          # ломаем один кадр
        ex = _run(work, cal=_cal(), limit=4)
        if not ex.skipped:
            raise AssertionError("повреждённый файл не был пропущен")
        if not ex.fields:
            raise AssertionError("из-за одного файла рухнул весь эксперимент")
        return (f"обработано {len(ex.fields)} из 4, пропущен "
                f"{len(ex.skipped)}: {Path(ex.skipped[0][0]).name}")


@test("Каталог без данных: понятное сообщение, не traceback")
def _empty_dir():
    from holocyt.importers.hstudio import detect, load_experiment
    with tempfile.TemporaryDirectory() as tmp:
        if detect(Path(tmp)) is not None:
            raise AssertionError("пустой каталог принят за эксперимент")
        try:
            load_experiment(Path(tmp))
        except FileNotFoundError as e:
            if "Hstudio" not in str(e) and "не похож" not in str(e):
                raise AssertionError(f"невнятное сообщение: {e}")
            return "пустой каталог отклонён с пояснением"
    raise AssertionError("ошибка не возникла")


@test("Посторонний каталог с .bin не принимается за эксперимент")
def _stray_bin():
    """Регрессия: .bin сам по себе не признак выгрузки Hstudio.

    Файлы .bin лежат в множестве системных каталогов, и C:\\Windows\\System32
    опознавался как эксперимент: detect() возвращал 'unsupported', а запрос
    к интерфейсу заканчивался HTTP 500 без пояснения. Поддержку .bin эта
    проверка не подразумевает — формат по-прежнему отклоняется.
    """
    from holocyt.importers.hstudio import detect
    from holocyt.webui import inspect
    with tempfile.TemporaryDirectory() as tmp:
        stray = Path(tmp) / "посторонний каталог"
        (stray / "вложенный").mkdir(parents=True)
        (stray / "вложенный" / "данные.bin").write_bytes(b"\x00" * 64)

        if detect(stray) is not None:
            raise AssertionError(
                f"каталог без признаков Hstudio принят за эксперимент: "
                f"{detect(stray)!r}")
        r = inspect(str(stray))
        if r.get("ok") is not False:
            raise AssertionError("посторонний каталог принят как годный")
        if "не распознан" not in r.get("error", ""):
            raise AssertionError(f"невнятное сообщение: {r.get('error')}")

        # А вот выгрузка Hstudio с картами .bin должна отклоняться
        # именно с пояснением про формат, и тоже без исключения наружу.
        real = Path(tmp) / "выгрузка Hstudio"
        (real / "Storage" / "PhaseMatrixStorage").mkdir(parents=True)
        (real / "DBTransferInfo.xml").write_text("<x/>", encoding="utf-8")
        (real / "Storage" / "PhaseMatrixStorage" / "0.bin").write_bytes(b"\x00" * 64)
        r2 = inspect(str(real))
        if r2.get("ok") is not False:
            raise AssertionError("каталог с .bin принят как годный")
        if ".fmx" not in r2.get("error", ""):
            raise AssertionError(f"нет пояснения про формат: {r2.get('error')}")
    return "посторонний каталог отклонён, выгрузка с .bin — с пояснением"


@test("Повреждённый imagedb.xml не мешает анализу")
def _bad_xml():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "опыт"
        shutil.copytree(need_demo(), work)
        (work / "imagedb.xml").write_text("<не xml вовсе", encoding="utf-8")
        ex = _run(work, cal=_cal(), limit=2)
        if not ex.fields:
            raise AssertionError("анализ не выполнился")
        return f"анализ прошёл, {sum(f.n_cells for f in ex.fields)} объектов"


# --- пути ------------------------------------------------------------------
@test("Путь с кириллицей")
def _cyrillic():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "Исследования" / "Клеточные культуры" / "Опыт 01"
        work.parent.mkdir(parents=True)
        shutil.copytree(need_demo(), work)
        ex = _run(work, cal=_cal(), limit=2)
        if not ex.fields:
            raise AssertionError("анализ не выполнился")
        from holocyt.export import export_all
        res = export_all(ex, work / "результаты")
        if not res["csv"].exists():
            raise AssertionError("выгрузка не создана")
        return f"{work.relative_to(tmp)} — прочитано и выгружено"


@test("Путь с пробелами и точками")
def _spaces():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "My Data 1.0" / "Эксперимент M4 (копия)"
        work.parent.mkdir(parents=True)
        shutil.copytree(need_demo(), work)
        ex = _run(work, cal=None, limit=2)
        if not ex.fields:
            raise AssertionError("анализ не выполнился")
        return f"{work.name} — прочитано"


# --- выгрузка --------------------------------------------------------------
@test("Выгрузка CSV и метаданных")
def _export():
    from holocyt.export import export_all
    import json
    ex = _run(DEMO, cal=_cal(), limit=2)
    with tempfile.TemporaryDirectory() as tmp:
        res = export_all(ex, tmp)
        if res["rows"] < 10:
            raise AssertionError(f"подозрительно мало строк: {res['rows']}")
        head = res["csv"].read_text(encoding="utf-8-sig").splitlines()[0]
        if "[A]" not in head or "[B]" not in head:
            raise AssertionError("в заголовке нет пометок категорий")
        if "_tmp" in head or "object at 0x" in head:
            raise AssertionError("в заголовке служебный мусор")
        meta = json.loads(res["metadata"].read_text(encoding="utf-8"))
        for key in ("software", "analysis", "calibration", "parameter_categories"):
            if key not in meta:
                raise AssertionError(f"в метаданных нет раздела {key}")
        if meta["software"]["version"] != __import__(
                "holocyt.version", fromlist=["VERSION"]).VERSION:
            raise AssertionError("версия в метаданных не совпадает")
        return f"{res['rows']} строк, {res['cols']} колонок, метаданные на месте"


@test("Формирование отчёта PDF")
def _pdf():
    from holocyt.report import build_report
    ex = _run(DEMO, cal=_cal(), limit=3)
    with tempfile.TemporaryDirectory() as tmp:
        p = build_report(ex, Path(tmp) / "отчёт.pdf")
        size = p.stat().st_size
        if size < 50_000:
            raise AssertionError(f"отчёт подозрительно мал: {size} байт")
        head = p.read_bytes()[:5]
        if head[:4] != b"%PDF":
            raise AssertionError("это не PDF")
        return f"{size / 1024:.0f} КБ"


@test("Отчёт без калибровки тоже формируется")
def _pdf_no_cal():
    from holocyt.report import build_report
    ex = _run(DEMO, cal=None, limit=2)
    with tempfile.TemporaryDirectory() as tmp:
        p = build_report(ex, Path(tmp) / "отчёт.pdf")
        if p.stat().st_size < 50_000:
            raise AssertionError("отчёт пуст")
        return f"{p.stat().st_size / 1024:.0f} КБ"


# --- воспроизводимость -----------------------------------------------------
@test("Повторный анализ даёт тот же результат")
def _deterministic():
    import numpy as np
    runs = []
    for _ in range(2):
        ex = _run(DEMO, cal=_cal(), limit=2)
        cells = [c for f in ex.fields for c in f.cells]
        runs.append((len(cells),
                     round(float(np.sum([c["area_px"] for c in cells])), 6),
                     round(float(np.sum([c["dry_mass_pg"] for c in cells])), 6)))
    if runs[0] != runs[1]:
        raise AssertionError(f"результаты различаются: {runs[0]} против {runs[1]}")
    return f"объектов {runs[0][0]}, сумма площадей и масс совпали побитно"


@test("Версия определяется из одного места")
def _version():
    from holocyt.version import VERSION, PRODUCT
    from holocyt.export import analysis_metadata
    ex = _run(DEMO, cal=None, limit=1)
    if analysis_metadata(ex)["software"]["version"] != VERSION:
        raise AssertionError("версия в метаданных расходится")
    vt = ROOT / "VERSION.txt"
    if vt.exists() and vt.read_text(encoding="utf-8").strip() != VERSION:
        raise AssertionError("VERSION.txt расходится с holocyt/version.py")
    return f"{PRODUCT} {VERSION}"


def main():
    from holocyt.version import PRODUCT, VERSION
    print(f"\n  {PRODUCT} {VERSION} — регрессионный набор")
    print(f"  данные: {DEMO}\n")
    width = max(len(n) for n, _ in TESTS) + 2
    failed, skipped, t0 = [], [], time.time()
    for name, fn in TESTS:
        print(f"  {name:.<{width}}", end=" ", flush=True)
        try:
            detail = fn()
        except Skip as e:
            print("SKIP")
            print(f"       {e}")
            skipped.append(name)
            continue
        except Exception as e:
            print("FAIL")
            print(f"       {type(e).__name__}: {e}")
            for line in traceback.format_exc().splitlines()[-3:-1]:
                print(f"       {line.strip()}")
            failed.append(name)
            continue
        print("PASS")
        if detail:
            print(f"       {detail}")

    # Пропущенная проверка не засчитывается пройденной: приёмочный итог
    # должен показывать, сколько проверок действительно выполнялось.
    total = len(TESTS)
    executed = total - len(skipped)
    n_pass = executed - len(failed)
    print(f"\n  {total} проверок")
    print(f"  {executed} выполнено")
    print(f"  {n_pass} PASS")
    print(f"  {len(failed)} FAIL")
    print(f"  {len(skipped)} SKIP")
    print(f"  за {time.time() - t0:.0f} с")
    if failed:
        print(f"\n  Отказы: {', '.join(failed)}\n")
        return 1
    if skipped:
        print(f"\n  Не выполнялись: {', '.join(skipped)}")
        print("  Приёмка неполная: часть проверок пропущена.\n")
        return 0
    print("\n  Все проверки пройдены.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
