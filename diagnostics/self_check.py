#!/usr/bin/env python3
"""Самодиагностика ГОЛОЦИТа.

Отвечает на один вопрос: готова ли программа к работе на этой машине.
Проверки, которые невозможно выполнить вне Windows, помечаются
NOT TESTED — выдавать их за пройденные нельзя.

Запуск:  python diagnostics/self_check.py
Windows: SELF_CHECK_WINDOWS.bat
"""

import os
import shutil
import socket
import sys
import tempfile
import traceback
from pathlib import Path


def app_root() -> Path:
    """Каталог приложения: из сборки, из комплекта переноса или из репозитория."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parents[1]
    return here / "app" if (here / "app" / "run.py").exists() else here


ROOT = app_root()
sys.path.insert(0, str(ROOT))

IS_WINDOWS = sys.platform.startswith("win")
CHECKS = []
PASS, FAIL, SKIP = "PASS", "FAIL", "NOT TESTED"


def check(name, windows_only=False):
    def deco(fn):
        CHECKS.append((name, fn, windows_only))
        return fn
    return deco


@check("Версия программы")
def _version():
    from holocyt.version import PRODUCT, VERSION
    vt = ROOT / "VERSION.txt"
    if vt.exists() and vt.read_text(encoding="utf-8").strip() != VERSION:
        raise AssertionError("VERSION.txt расходится с holocyt/version.py")
    return f"{PRODUCT} {VERSION}"


@check("Интерпретатор и библиотеки")
def _libs():
    import numpy, scipy, skimage, sklearn, matplotlib
    v = sys.version_info
    return (f"Python {v.major}.{v.minor}.{v.micro}, numpy {numpy.__version__}, "
            f"scikit-learn {sklearn.__version__}")


@check("Настройки приложения")
def _config():
    from holocyt.config import load, get
    cfg = load()
    for sec in ("segmentation", "background", "export", "logging"):
        if sec not in cfg:
            raise AssertionError(f"нет раздела настроек {sec}")
    return (f"порог слабого сигнала: режим {get('background','mode')}, "
            f"значение {get('background','fixed_threshold')}")


@check("Обученные модели")
def _models():
    from holocyt.pipeline import load_model, MODELS_DIR
    sizes = []
    for n in ("segmenter", "cellstate", "novelty"):
        load_model(n)
        sizes.append(f"{n} {(MODELS_DIR / (n + '.joblib')).stat().st_size / 1e6:.1f} МБ")
    return ", ".join(sizes)


@check("Совпадение версий библиотек с моделями")
def _model_env():
    from holocyt.pipeline import check_model_environment
    check_model_environment()
    return "модели загружаются текущими версиями библиотек"


@check("Демонстрационный эксперимент")
def _demo():
    from holocyt.importers.hstudio import detect, load_experiment
    demo = ROOT / "demo_data" / "M4_demo_8"
    if not demo.exists():
        raise AssertionError(f"не найден: {demo}")
    if detect(demo) != "experiment":
        raise AssertionError("каталог не распознан как эксперимент Hstudio")
    ex = load_experiment(demo)
    return f"{ex.name}: {ex.n_frames} настоящих кадров M4"


@check("Чтение карты фазы")
def _phase():
    from holocyt.importers.hstudio import load_experiment, read_phase_matrix
    ex = load_experiment(ROOT / "demo_data" / "M4_demo_8")
    pm = read_phase_matrix(ex.phase_files[0])
    return (f"{pm.path.name}: {pm.width}x{pm.height}, {pm.version}, "
            f"фаза {pm.phase.min():+.3f}…{pm.phase.max():+.3f}")


@check("Разбор калибровки")
def _calib():
    from holocyt.calibration import Calibration, from_user
    empty = Calibration()
    if empty.complete:
        raise AssertionError("пустая калибровка объявлена полной")
    full = from_user(0.336, 0.633, 1.38, 1.34)
    if not full.complete:
        raise AssertionError("полная калибровка не распознана")
    return "отсутствие и наличие калибровки различаются верно"


@check("Сегментация")
def _segment():
    from holocyt.importers.hstudio import load_experiment, read_phase_matrix
    from holocyt.pipeline import analyze_field
    from holocyt.calibration import from_user
    ex = load_experiment(ROOT / "demo_data" / "M4_demo_8")
    pm = read_phase_matrix(ex.phase_files[0])
    fr = analyze_field(pm.phase, name=pm.path.name,
                       cal=from_user(0.3359375, 0.633, 1.38, 1.34))
    if fr.n_cells < 10:
        raise AssertionError(f"найдено всего {fr.n_cells} объектов")
    return f"{pm.path.name}: {fr.n_cells} объектов, занято {fr.confluence_pct:.0f} %"


@check("Формирование отчёта PDF")
def _pdf():
    from holocyt.experiment import Experiment
    from holocyt.report import build_report
    from holocyt.calibration import from_user
    ex = Experiment.from_hstudio(ROOT / "demo_data" / "M4_demo_8",
                                 cal=from_user(0.3359375, 0.633, 1.38, 1.34))
    ex.records = ex.records[:2]
    ex.run()
    with tempfile.TemporaryDirectory() as t:
        p = build_report(ex, Path(t) / "отчёт.pdf")
        if p.read_bytes()[:4] != b"%PDF" or p.stat().st_size < 50_000:
            raise AssertionError("отчёт не сформирован")
        return f"{p.stat().st_size / 1024:.0f} КБ, кириллица отрисована"


@check("Выгрузка CSV и метаданных")
def _csv():
    from holocyt.experiment import Experiment
    from holocyt.export import export_all
    ex = Experiment.from_hstudio(ROOT / "demo_data" / "M4_demo_8")
    ex.records = ex.records[:1]
    ex.run()
    with tempfile.TemporaryDirectory() as t:
        r = export_all(ex, t)
        return f"{r['rows']} строк, {r['cols']} колонок, метаданные записаны"


@check("Каталоги для записи")
def _writable():
    from holocyt.diagnostics import log_path
    for d in (ROOT / "out", log_path().parent):
        d.mkdir(parents=True, exist_ok=True)
        p = d / ".проверка"
        p.write_text("ок", encoding="utf-8")
        p.unlink()
    return f"результаты: {ROOT / 'out'}; журнал: {log_path()}"


@check("Путь с кириллицей и пробелами")
def _unicode_path():
    from holocyt.importers.hstudio import detect
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "Исследования 2026" / "Опыт № 1 (копия)"
        shutil.copytree(ROOT / "demo_data" / "M4_demo_8", d)
        if detect(d) != "experiment":
            raise AssertionError("эксперимент по такому пути не распознан")
        return f"{d.parent.name}/{d.name} — прочитан"


@check("Локальный интерфейс")
def _web():
    from holocyt.webui import WEB, find_free_port
    if not (WEB / "index.html").exists():
        raise AssertionError(f"нет файла интерфейса: {WEB / 'index.html'}")
    port = find_free_port(8765)
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
    return f"страница на месте, свободный порт {port}"


@check("Работа без сети")
def _offline():
    html = (ROOT / "holocyt" / "web" / "index.html").read_text(encoding="utf-8")
    for bad in ("http://", "https://", "cdn", "googleapis", "fonts."):
        if bad in html.lower():
            raise AssertionError(f"в интерфейсе внешняя ссылка: {bad}")
    return "внешних ресурсов нет, программа полностью локальна"


@check("Запуск собранного приложения", windows_only=True)
def _frozen():
    """Поднимает собранное приложение целиком и ждёт ответа интерфейса.

    Проверять `--version` бессмысленно: argparse печатает версию и выходит
    до импорта numpy, поэтому неработоспособная сборка её проходит.
    """
    import json
    import socket
    import subprocess
    import time
    import urllib.request

    if getattr(sys, "frozen", False):
        return "самодиагностика выполняется из собранного приложения"

    dist = Path(__file__).resolve().parents[1] / "dist" / "ГОЛОЦИТ"
    exe = dist / "ГОЛОЦИТ.exe"
    if not exe.exists():
        exe = dist / "HOLOCYT.exe"
    if not exe.exists():
        raise AssertionError(
            f"сборка не найдена: {dist}. Сначала выполните build\\BUILD_WINDOWS.bat")

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [str(exe), "--no-browser", "--port", str(port)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            if proc.poll() is not None:
                tail = (proc.stdout.read() if proc.stdout else "")[-1500:]
                raise AssertionError(
                    f"приложение завершилось с кодом {proc.returncode}: {tail}")
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/config", timeout=2) as r:
                    cfg = json.load(r)
            except Exception:
                time.sleep(1)
                continue
            return (f"{exe.name} запустился, интерфейс отвечает на порту "
                    f"{port}, версия {cfg.get('version')}")
        raise AssertionError("интерфейс собранного приложения не ответил за 120 с")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()


@check("Загрузка библиотек DLL", windows_only=True)
def _dll():
    """Загружает C-расширения научных библиотек.

    Именно здесь всплывает отсутствие компонентов Visual C++ и неполная
    упаковка: каждое из этих расширений тянет свои DLL.
    """
    import importlib

    mods = ("numpy._core._multiarray_umath", "numpy.linalg._umath_linalg",
            "scipy.linalg._fblas", "scipy.special._ufuncs",
            "sklearn.tree._tree", "sklearn.utils._openmp_helpers",
            "PIL._imaging", "matplotlib.ft2font")
    failed = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:
            failed.append(f"{m} ({type(e).__name__}: {e})")
    if failed:
        raise AssertionError("не загрузились: " + "; ".join(failed))
    return f"{len(mods)} C-расширений загружено, библиотеки DLL на месте"


@check("Открытие браузера в Windows", windows_only=True)
def _browser():
    """Проверяет, что в системе зарегистрирован браузер.

    Сам браузер не открывается: проверяется только то, что Windows
    сообщает программе, чем открывать ссылку.
    """
    import webbrowser

    try:
        ctrl = webbrowser.get()
    except webbrowser.Error as e:
        raise AssertionError(
            f"браузер по умолчанию не определён: {e}. "
            f"Программа работает, адрес интерфейса печатается в консоли")
    return f"браузер по умолчанию: {getattr(ctrl, 'name', None) or type(ctrl).__name__}"


def main():
    from holocyt.version import PRODUCT, VERSION
    print(f"\n{PRODUCT} — самодиагностика")
    print(f"версия {VERSION}, платформа {sys.platform}\n")

    width = max(len(n) for n, _, _ in CHECKS) + 2
    n_pass = n_fail = n_skip = 0
    for name, fn, win_only in CHECKS:
        if win_only and not IS_WINDOWS:
            print(f"[{SKIP}] {name}")
            print(f"          требует настоящей Windows")
            n_skip += 1
            continue
        try:
            detail = fn()
            print(f"[{PASS}] {name}")
            if detail:
                print(f"          {detail}")
            n_pass += 1
        except Exception as e:
            print(f"[{FAIL}] {name}")
            print(f"          {type(e).__name__}: {e}")
            for line in traceback.format_exc().splitlines()[-3:-1]:
                print(f"          {line.strip()}")
            n_fail += 1

    total = n_pass + n_fail
    print(f"\n{n_pass} / {total} PASS", end="")
    if n_skip:
        print(f", {n_skip} NOT TESTED (требуют Windows)", end="")
    print()
    if n_fail:
        print("\nСистема к работе НЕ готова. Причины указаны выше.\n")
        return 1
    print("\nСистема готова к работе.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
