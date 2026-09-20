#!/usr/bin/env python3
"""Сборка комплекта для переноса на Windows.

Собирает чистую папку, в которой есть всё необходимое и нет ничего
лишнего: ни синтетических данных, ни образа флешки, ни установщика
чужой программы, ни временных файлов разработки.

    python scripts/make_release.py
"""

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from holocyt.version import VERSION, PRODUCT          # noqa: E402

NAME = f"HOLOCYT_WINDOWS_TRANSFER_{VERSION}"
RELEASE = ROOT / "release"
DEST = RELEASE / NAME

# Что кладём. Слева — источник, справа — место в комплекте.
APP_TREE = ["holocyt", "models", "scripts"]
APP_FILES = ["run.py", "VERSION.txt", "ABOUT_SOFTWARE.txt"]
ROOT_FILES = ["README_FIRST.txt", "VERSION.txt", "RELEASE_NOTES.md",
              "KNOWN_LIMITATIONS.md", "WINDOWS_ACCEPTANCE.md",
              "THIRD_PARTY_LICENSES.txt", "ABOUT_SOFTWARE.txt",
              "WINDOWS_DEPENDENCY_AUDIT.md", "VALIDATION_REAL_DATA.md"]

# Что не кладём ни при каких условиях.
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".DS_Store", ".git*",
    ".venv*", "build_cache", "dist", "release", "out", "logs",
    "*.cdr", "*.exe", "recovery", "vendor", "demo_data",
    # Скрипты исследований — в комплект не нужны.
    "train_models.py", "make_demo.py", "match_real.py",
    "compare_hstudio.py", "benchmark_segmentation.py",
    "build_windows.py", "make_release.py", "make_docs.py",
)


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def build():
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    print(f"{PRODUCT} {VERSION} — сборка комплекта\n  {DEST}\n")

    # --- код ---------------------------------------------------------
    app = DEST / "app"
    app.mkdir()
    for d in APP_TREE:
        src = ROOT / d
        if src.exists():
            shutil.copytree(src, app / d, ignore=IGNORE)
    for f in APP_FILES:
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, app / f)
    # Скрипты разработки в комплект не идут; каталог может опустеть.
    sc = app / "scripts"
    if sc.exists() and not any(sc.iterdir()):
        sc.rmdir()
    print(f"  app/            {sum(1 for _ in app.rglob('*') if _.is_file())} файлов")

    # --- демонстрационные данные ---------------------------------------
    # Кладём внутрь app/: программа ищет их относительно себя, и лишних
    # преобразований путей не возникает.
    demo = app / "demo_data"
    shutil.copytree(ROOT / "demo_data" / "M4_demo_8", demo / "M4_demo_8",
                    ignore=IGNORE)
    n_fmx = len(list(demo.rglob("*.fmx")))
    print(f"  app/demo_data/  {n_fmx} настоящих кадров M4, "
          f"{sum(f.stat().st_size for f in demo.rglob('*') if f.is_file()) / 1e6:.0f} МБ")

    # --- сборка, диагностика, зависимости, тесты ----------------------
    for name in ("build", "diagnostics", "requirements", "tests"):
        src = ROOT / name
        if src.exists():
            shutil.copytree(src, DEST / name, ignore=IGNORE)
            print(f"  {name + '/':15s} {sum(1 for _ in (DEST / name).rglob('*') if _.is_file())} файлов")

    # --- документация --------------------------------------------------
    docs = DEST / "docs"
    docs.mkdir()
    for f in (ROOT / "docs").glob("*.pdf"):
        shutil.copy2(f, docs / f.name)
    for f in (ROOT / "docs").glob("*.png"):
        shutil.copy2(f, docs / f.name)
    print(f"  docs/           {sum(1 for _ in docs.iterdir())} файлов")

    # --- корневые документы ---------------------------------------------
    for f in ROOT_FILES:
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, DEST / f)

    # --- каталоги, куда пишет программа ----------------------------------
    # Программа пишет рядом с собой, то есть внутрь app/. Дублировать
    # пустые out/ и logs/ в корне комплекта незачем — это сбивало бы
    # с толку: файлы появлялись бы не там, где их ждут.
    for d in ("out", "logs"):
        (app / d).mkdir(exist_ok=True)
        (app / d / ".gitkeep").write_text("", encoding="utf-8")

    # --- контрольные суммы ------------------------------------------------
    rows = []
    for p in sorted(DEST.rglob("*")):
        if p.is_file() and p.name != "CHECKSUMS.sha256":
            rows.append((sha256(p), p.relative_to(DEST).as_posix()))
    (DEST / "CHECKSUMS.sha256").write_text(
        "# Контрольные суммы комплекта " + NAME + "\n"
        "# Проверка на Windows:  certutil -hashfile <файл> SHA256\n"
        "# Проверка на macOS:    shasum -a 256 -c CHECKSUMS.sha256\n\n"
        + "\n".join(f"{h}  {n}" for h, n in rows) + "\n", encoding="utf-8")
    print(f"\n  CHECKSUMS.sha256  {len(rows)} файлов")

    total = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file())
    n_files = sum(1 for p in DEST.rglob("*") if p.is_file())
    print(f"\n  Итого: {n_files} файлов, {total / 1e6:.0f} МБ")
    return DEST, n_files, total


def make_zip(folder, out_zip):
    """Архив без символьных ссылок, служебных файлов macOS и кэшей."""
    out_zip = Path(out_zip)
    if out_zip.exists():
        out_zip.unlink()
    n = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_symlink():
                continue
            if any(part in ("__pycache__", ".git") for part in p.parts):
                continue
            if p.name in (".DS_Store",) or p.name.startswith("._"):
                continue
            if p.is_file():
                z.write(p, Path(folder.name) / p.relative_to(folder))
                n += 1
    return out_zip, n


def verify_zip(path):
    """Проверяет архив: открывается, структура цела, мусора нет."""
    problems = []
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            problems.append(f"повреждена запись {bad}")
        names = z.namelist()
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts:
                problems.append(f"путь выходит за пределы архива: {n}")
            if "__MACOSX" in n or n.endswith(".DS_Store") or "/._" in n:
                problems.append(f"служебный файл macOS: {n}")
            if "__pycache__" in n:
                problems.append(f"кэш Python: {n}")
        for need in ("README_FIRST.txt", "VERSION.txt", "app/run.py",
                     "build/BUILD_WINDOWS.bat", "CHECKSUMS.sha256"):
            if not any(x.endswith(need) for x in names):
                problems.append(f"в архиве нет: {need}")
    return problems, len(names)


def make_source_archive():
    """Полный исходный проект для разработки — не для переноса на Windows."""
    out = RELEASE / f"HOLOCYT_SOURCE_FULL_{VERSION}.zip"
    if out.exists():
        out.unlink()
    # В исходный архив не кладём тяжёлое и чужое: образ флешки,
    # установщик Hstudio, полный набор данных, сборки и кэши.
    skip_dirs = {".git", ".venv", ".venv-build", ".venv-run", "__pycache__",
                 "build_cache", "dist", "release", "recovery", "vendor", "logs"}
    skip_names = {".DS_Store"}
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if any(part in skip_dirs for part in rel.parts):
                continue
            if p.name in skip_names or p.name.startswith("._"):
                continue
            if p.suffix in (".pyc", ".pyo", ".cdr"):
                continue
            # Полный набор из 56 кадров в архив не тянем: в поставке
            # достаточно компактного из восьми.
            if "M4 Example woundhealing" in rel.parts:
                continue
            if p.is_file() and not p.is_symlink():
                z.write(p, Path(f"holocyt-{VERSION}") / rel)
                n += 1
    return out, n



if __name__ == "__main__":
    RELEASE.mkdir(exist_ok=True)
    dest, n_files, total = build()

    print("\n  Создание архива…")
    zip_path, n = make_zip(dest, RELEASE / f"{NAME}.zip")
    problems, n_in_zip = verify_zip(zip_path)
    print(f"  {zip_path.name}: {n_in_zip} записей, "
          f"{zip_path.stat().st_size / 1e6:.0f} МБ")
    if problems:
        print("  ПРОБЛЕМЫ В АРХИВЕ:")
        for p in problems:
            print(f"    - {p}")
        sys.exit(1)
    print("  Проверка архива пройдена")
    print(f"  SHA256: {sha256(zip_path)}")

    print("\n  Архив исходников для разработки…")
    src_zip, n_src = make_source_archive()
    print(f"  {src_zip.name}: {n_src} файлов, "
          f"{src_zip.stat().st_size / 1e6:.0f} МБ")
    print(f"  SHA256: {sha256(src_zip)}")

    print(f"\n  Готово. Всё в {RELEASE}")


