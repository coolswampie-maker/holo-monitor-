#!/usr/bin/env python3
"""Сборка переносимой версии ГОЛОЦИТа для Windows.

Собирает каталог, который достаточно скопировать на рабочую станцию и
запустить. Ничего не устанавливается: ни Python в систему, ни записи в
реестр, ни права администратора. Подходит для машины без доступа в сеть
и для запуска прямо с флешки.

Скрипт запускается на любой системе (в том числе на macOS и Linux):
колёса для Windows и встраиваемый Python скачиваются как файлы.

    python3 scripts/build_windows.py

Результат: dist/ГОЛОЦИТ-windows/
"""

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_VERSION = "3.11.9"
PY_TAG = "311"
EMBED_URL = (f"https://www.python.org/ftp/python/{PY_VERSION}/"
             f"python-{PY_VERSION}-embed-amd64.zip")

# Что кладём в сборку из исходного дерева.
COPY_TREE = ["holocyt", "models", "scripts"]
# Демонстрационные данные кладём в сборку: на показе у заказчика
# всё должно работать сразу, без генерации и без ожидания.
COPY_DEMO = True
COPY_FILE = ["run.py", "README.md", "requirements.txt"]

# ВАЖНО: внутри .bat только ASCII.
# cmd.exe читает файл сценария в кодовой странице системы (866 для русской
# Windows), а не в UTF-8. Русский текст в echo вывелся бы искажённым.
# Поэтому всё, что видит пользователь по-русски, печатает Python — там
# кодировку задаём мы сами через PYTHONUTF8 и _compat.force_utf8_output().

LAUNCHER = """@echo off
rem HOLOCYT launcher. Installs nothing, writes nothing outside this folder.
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
title HOLOCYT
python\\python.exe run.py
if errorlevel 1 (
  echo.
  echo   [!] Program exited with an error. See the message above.
  echo.
  pause
)
"""

SELFTEST_LAUNCHER = """@echo off
rem HOLOCYT self-check.
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
title HOLOCYT - self check
python\\python.exe -m holocyt selftest
echo.
pause
"""

CONSOLE_LAUNCHER = """@echo off
rem HOLOCYT command line.
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
python\\python.exe -m holocyt %*
if errorlevel 1 pause
"""


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def fetch_embedded_python(dest: Path, cache: Path):
    """Скачивает и распаковывает встраиваемый Python для Windows x64."""
    cache.mkdir(parents=True, exist_ok=True)
    zpath = cache / Path(EMBED_URL).name
    if not zpath.exists():
        print(f"  скачиваю {EMBED_URL}")
        urllib.request.urlretrieve(EMBED_URL, zpath)
    print(f"  распаковываю {zpath.name}")
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)

    # Встраиваемая сборка по умолчанию не подхватывает сторонние пакеты:
    # в файле ._pth строка import site закомментирована, а пути к нашим
    # каталогам отсутствуют. Дописываем.
    pth = dest / f"python{PY_TAG}._pth"
    lines = pth.read_text().splitlines() if pth.exists() else []
    out = []
    for ln in lines:
        out.append("import site" if ln.strip() == "#import site" else ln)
    if "import site" not in out:
        out.append("import site")
    for extra in ("..", "../lib"):
        if extra not in out:
            out.insert(0, extra)
    pth.write_text("\n".join(out) + "\n")
    print(f"  настроен {pth.name}")


def fetch_wheels(lib: Path, cache: Path):
    """Скачивает колёса под Windows x64 и распаковывает их в lib/."""
    cache.mkdir(parents=True, exist_ok=True)
    print("  скачиваю пакеты для Windows x64")
    run([sys.executable, "-m", "pip", "download",
         "-r", str(ROOT / "requirements.txt"),
         "-d", str(cache),
         "--only-binary=:all:",
         "--platform", "win_amd64",
         "--python-version", PY_TAG,
         "--implementation", "cp",
         "--no-cache-dir"])

    lib.mkdir(parents=True, exist_ok=True)
    wheels = sorted(cache.glob("*.whl"))
    print(f"  распаковываю {len(wheels)} пакетов")
    for w in wheels:
        with zipfile.ZipFile(w) as z:
            z.extractall(lib)
    return wheels


def strip_fat(lib: Path):
    """Убирает то, что рабочей станции не нужно: тесты и заголовки."""
    removed = 0
    for pat in ("**/tests", "**/test", "**/testing", "**/__pycache__",
                "**/*.dist-info/RECORD", "**/include"):
        for p in lib.glob(pat):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True); removed += 1
            elif p.is_file():
                p.unlink(missing_ok=True)
    return removed


def verify_versions(wheels, dist: Path):
    """Сверяет версии колёс с requirements.txt и с отпечатком моделей.

    Несовпадение версий scikit-learn или numpy делает файлы моделей
    нечитаемыми. Дешевле поймать это здесь, чем на машине заказчика.
    """
    import json, re
    req = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            n, v = line.split("==", 1)
            req[n.strip().lower().replace("-", "_")] = v.strip()

    got = {}
    for w in wheels:
        m = re.match(r"^(.+?)-(\d[^-]*)-", w.name)
        if m:
            got[m.group(1).lower().replace("-", "_")] = m.group(2)

    problems = []
    for n, v in req.items():
        if n not in got:
            problems.append(f"пакет {n} не скачан")
        elif got[n] != v:
            problems.append(f"{n}: требуется {v}, скачано {got[n]}")

    stamp_path = dist / "models" / "versions.json"
    if stamp_path.exists():
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        for key in ("sklearn", "numpy"):
            pkg = "scikit_learn" if key == "sklearn" else "numpy"
            if key in stamp and pkg in got and stamp[key] != got[pkg]:
                problems.append(
                    f"модели обучены на {key} {stamp[key]}, "
                    f"а в сборку идёт {got[pkg]} — они не загрузятся. "
                    f"Переобучите: python scripts/train_models.py")
    else:
        problems.append("нет models/versions.json — отпечаток среды обучения не записан")
    return problems


def main(out_dir, keep_cache=True):
    dist = Path(out_dir)
    if dist.exists():
        print(f"  очищаю {dist}")
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    cache = ROOT / "build_cache"

    print("\n[1/5] Встраиваемый Python")
    fetch_embedded_python(dist / "python", cache)

    print("\n[2/5] Библиотеки")
    wheels = fetch_wheels(dist / "lib", cache)

    print("\n[3/5] Исходный код и модели")
    for d in COPY_TREE:
        src = ROOT / d
        if src.exists():
            shutil.copytree(src, dist / d,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print(f"  {d}/")
    for f in COPY_FILE:
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, dist / f); print(f"  {f}")
    (dist / "out").mkdir(exist_ok=True)
    demo_src = ROOT / "demo_data"
    if COPY_DEMO and (demo_src / "M4 Example woundhealing").exists():
        shutil.copytree(demo_src, dist / "demo_data")
        n = len(list((dist / "demo_data").rglob("*.fmx")))
        print(f"  demo_data/ ({n} карт фазы, настоящие данные M4)")
    else:
        (dist / "demo_data").mkdir(exist_ok=True)
        print("  demo_data/ пуст — будет создан при первом запуске")

    print("\n[4/5] Пусковые файлы")
    (dist / "ГОЛОЦИТ.bat").write_text(LAUNCHER, encoding="ascii", newline="\r\n")
    (dist / "Проверка.bat").write_text(SELFTEST_LAUNCHER, encoding="ascii", newline="\r\n")
    (dist / "Командная строка.bat").write_text(CONSOLE_LAUNCHER, encoding="ascii", newline="\r\n")
    print("  ГОЛОЦИТ.bat, Проверка.bat, Командная строка.bat")

    print("\n[5/6] Сверка версий")
    problems = verify_versions(wheels, dist)
    if problems:
        print("  ОБНАРУЖЕНЫ РАСХОЖДЕНИЯ:")
        for pr in problems:
            print(f"    - {pr}")
        raise SystemExit("\nСборка остановлена: сборка с такими расхождениями не заработает.")
    print("  версии колёс, requirements.txt и отпечатка моделей совпадают")

    print("\n[6/6] Уборка")
    n = strip_fat(dist / "lib")
    print(f"  удалено лишних каталогов: {n}")
    if not keep_cache:
        shutil.rmtree(cache, ignore_errors=True)

    size = sum(p.stat().st_size for p in dist.rglob("*") if p.is_file())
    files = sum(1 for p in dist.rglob("*") if p.is_file())
    print(f"\nГотово: {dist}")
    print(f"  {files} файлов, {size / 1e6:.0f} МБ")
    print(f"  пакетов: {len(wheels)}")
    print("\n  На рабочей станции: скопировать каталог целиком "
          "и запустить ГОЛОЦИТ.bat")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out-dir", default=str(ROOT / "dist" / "ГОЛОЦИТ-windows"))
    ap.add_argument("--clean-cache", action="store_true")
    a = ap.parse_args()
    main(a.out_dir, keep_cache=not a.clean_cache)
