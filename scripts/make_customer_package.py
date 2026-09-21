#!/usr/bin/env python3
"""Сборка поставки для покупателя.

Отличается от комплекта переноса тем, чего в ней НЕТ: ни исходного
кода, ни сценариев сборки, ни тестов разработчика, ни упоминаний
Python и PyInstaller. Покупатель распаковывает папку и запускает
программу.

    python scripts/make_customer_package.py

Требует готовой сборки в dist/ГОЛОЦИТ — её делает build/BUILD_WINDOWS.bat.
"""

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from holocyt.version import VERSION, PRODUCT          # noqa: E402

BUILT = ROOT / "dist" / "ГОЛОЦИТ"
RELEASE = ROOT / "release"
NAME = f"{PRODUCT}_{VERSION}_Windows"
DEST = RELEASE / NAME

#: Руководства пользователя: исходное имя -> имя в поставке.
DOCS = {
    "Quick_Start_RU.pdf": "Быстрый старт.pdf",
    "User_Manual_RU.pdf": "Руководство пользователя.pdf",
}

README = """\
{product} {version}
Программное обеспечение анализа данных цифровой голографической
микроскопии HoloMonitor M4.

С ЧЕГО НАЧАТЬ

  1. Откройте папку «{product}» и запустите «{product}.exe».
  2. Откроется окно программы. Устанавливать и настраивать ничего
     не нужно.
  3. Нажмите «Открыть демонстрационный эксперимент» — это настоящие
     кадры прибора, на них видно, как программа работает.
  4. Нажмите «Анализировать», дождитесь окончания и посмотрите
     результат. Внизу — «Экспорт CSV» и «Сформировать PDF-отчёт».

Чтобы посмотреть свои данные, укажите в первом поле путь к каталогу
эксперимента Hstudio и нажмите «Открыть».

ЧТО ГДЕ

  {product}\\          сама программа, запускается «{product}.exe»
  {product}\\out\\      сюда попадают отчёты и таблицы
  {product}\\logs\\     журнал работы, пригодится при обращении в поддержку
  Демо\\               настоящий демонстрационный эксперимент, 8 кадров
  Документация\\       быстрый старт и руководство пользователя

ЧТО ВАЖНО ЗНАТЬ

Без калибровки прибора программа не показывает микрометры, кубические
микрометры и пикограммы — только пиксели и сдвиг фазы. Это сделано
намеренно: подставлять размер пикселя «по умолчанию» означало бы
выдавать выдуманные числа за измеренные. Калибровку можно ввести
вручную в разделе «Калибровка прибора».

Графики подписаны «по порядку файлов», а не по времени: порядок
съёмки из данных прибора не восстанавливается.

Программа работает полностью на вашем компьютере. Никуда ничего не
передаётся, интернет не нужен.

Поддерживаются карты фазы .fmx. Формат .bin программа не читает и
честно об этом сообщает.

НАЗНАЧЕНИЕ

Исследовательское программное обеспечение. Не является медицинским
изделием и не предназначено для постановки диагноза.

Подробности об ограничениях — в файле {product}\\KNOWN_LIMITATIONS.md
"""


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
    if not BUILT.exists():
        print(f"  [!] Нет готовой сборки: {BUILT}")
        print("      Сначала выполните build\\BUILD_WINDOWS.bat")
        return None
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    print(f"{PRODUCT} {VERSION} — поставка для покупателя\n  {DEST}\n")

    # --- программа -------------------------------------------------------
    # docs/ из сборки не берём: руководства лежат отдельной папкой, а
    # docs/src — это исходники документации, покупателю они не нужны.
    app = DEST / PRODUCT
    shutil.copytree(BUILT, app, ignore=shutil.ignore_patterns(
        "docs", "out", "logs", "__pycache__", "*.bak", "*.txt.bak"))
    # Второй исполняемый файл с латинским именем — след сборки. Оставляем
    # один, чтобы не гадать, какой запускать.
    latin = app / "HOLOCYT.exe"
    if latin.exists():
        latin.unlink()
    for d in ("out", "logs"):
        (app / d).mkdir(exist_ok=True)
    n = sum(1 for _ in app.rglob("*") if _.is_file())
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"  {PRODUCT}/{' ' * 8} {n} файлов, {size / 1e6:.0f} МБ")

    # --- демонстрационные данные -----------------------------------------
    demo_src = ROOT / "demo_data" / "M4_demo_8"
    demo = DEST / "Демо" / "M4_demo_8"
    shutil.copytree(demo_src, demo)
    n_fmx = len(list(demo.rglob("*.fmx")))
    print(f"  Демо/            {n_fmx} настоящих кадров M4")

    # --- документация -----------------------------------------------------
    docs = DEST / "Документация"
    docs.mkdir()
    for src_name, dst_name in DOCS.items():
        src = ROOT / "docs" / src_name
        if src.exists():
            shutil.copy2(src, docs / dst_name)
    print(f"  Документация/    {sum(1 for _ in docs.iterdir())} файла")

    # --- README -----------------------------------------------------------
    (DEST / "README.txt").write_text(
        README.format(product=PRODUCT, version=VERSION), encoding="utf-8")

    total = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file())
    n_files = sum(1 for p in DEST.rglob("*") if p.is_file())
    print(f"\n  Итого: {n_files} файлов, {total / 1e6:.0f} МБ")
    return DEST


def check(dest):
    """Проверяет, что покупателю не досталось лишнего."""
    problems = []
    for p in dest.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(dest).as_posix()
        if p.suffix in (".bat", ".spec"):
            problems.append(f"сценарий сборки: {rel}")
        if p.suffix == ".py" and "_internal" not in rel:
            problems.append(f"исходный код: {rel}")
        if "test" in p.name.lower() and "_internal" not in rel:
            problems.append(f"тест разработчика: {rel}")
        if "synth" in p.name.lower():
            problems.append(f"синтетические данные: {rel}")
        if p.name.startswith("._") or p.name == ".DS_Store":
            problems.append(f"служебный файл macOS: {rel}")
    for need in (f"{PRODUCT}/{PRODUCT}.exe", "README.txt",
                 "Демо/M4_demo_8/imagedb.xml"):
        if not (dest / need).exists():
            problems.append(f"в поставке нет: {need}")
    return problems


def make_zip(folder):
    out = folder.parent / f"{folder.name}.zip"
    if out.exists():
        out.unlink()
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and not p.is_symlink():
                z.write(p, Path(folder.name) / p.relative_to(folder))
                n += 1
    return out, n


if __name__ == "__main__":
    RELEASE.mkdir(exist_ok=True)
    dest = build()
    if dest is None:
        sys.exit(1)

    problems = check(dest)
    if problems:
        print("\n  ЛИШНЕЕ В ПОСТАВКЕ:")
        for p in problems:
            print(f"    - {p}")
        sys.exit(1)
    print("  Проверка состава пройдена: лишнего нет")

    print("\n  Создание архива…")
    zip_path, n = make_zip(dest)
    print(f"  {zip_path.name}: {n} файлов, "
          f"{zip_path.stat().st_size / 1e6:.0f} МБ")
    print(f"  SHA256: {sha256(zip_path)}")
    print(f"\n  Готово. Всё в {RELEASE}")
