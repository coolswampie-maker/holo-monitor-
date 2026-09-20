#!/usr/bin/env python3
"""Завершение сборки: русское имя приложения и сопроводительные файлы.

Вызывается из BUILD_WINDOWS.bat. Вынесено в Python, потому что имена
с кириллицей в .bat-сценарии ненадёжны: cmd.exe читает сценарий в
кодовой странице системы, а не в UTF-8.
"""

import shutil
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG / "app" if (PKG / "app" / "run.py").exists() else PKG
DIST = PKG / "dist" / "HOLOCYT"
FINAL = PKG / "dist" / "ГОЛОЦИТ"


def main():
    if not DIST.exists():
        print("  [!] Сборка не найдена:", DIST)
        return 1

    exe = DIST / "HOLOCYT.exe"
    if exe.exists():
        target = DIST / "ГОЛОЦИТ.exe"
        shutil.copy2(exe, target)
        print("  Создан", target.name)

    for name in ("VERSION.txt", "ABOUT_SOFTWARE.txt", "KNOWN_LIMITATIONS.md"):
        src = PKG / name
        if not src.exists():
            src = ROOT / name
        if src.exists():
            shutil.copy2(src, DIST / name)

    docs = PKG / "docs"
    if docs.exists():
        shutil.copytree(docs, DIST / "docs", dirs_exist_ok=True)
        print("  Документация скопирована")

    # Каталоги, куда программа пишет.
    for d in ("out", "logs"):
        (DIST / d).mkdir(exist_ok=True)

    if FINAL.exists():
        shutil.rmtree(FINAL)
    DIST.rename(FINAL)
    print("  Готово:", FINAL)
    print("  Запуск:", FINAL / "ГОЛОЦИТ.exe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
