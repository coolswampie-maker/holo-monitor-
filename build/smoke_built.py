#!/usr/bin/env python3
"""Проверка собранного приложения. Вызывается в конце BUILD_WINDOWS.bat.

Запускает готовый исполняемый файл и убеждается, что он стартует и
сообщает свою версию. Если это не так, дальше проверять нечего.
"""

import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG / "app" if (PKG / "app" / "run.py").exists() else PKG


def main():
    dist = PKG / "dist" / "ГОЛОЦИТ"
    exe = dist / ("ГОЛОЦИТ.exe" if sys.platform.startswith("win") else "HOLOCYT")
    if not exe.exists():
        alt = dist / "HOLOCYT.exe"
        exe = alt if alt.exists() else exe
    if not exe.exists():
        print(f"  [!] Исполняемый файл не найден: {exe}")
        return 1

    expected = (PKG / "VERSION.txt").read_text(encoding="utf-8").strip()
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True,
                             text=True, timeout=120)
    except Exception as e:
        print(f"  [!] Запуск не удался: {type(e).__name__}: {e}")
        return 1
    text = (out.stdout + out.stderr).strip()
    if out.returncode != 0:
        print(f"  [!] Программа завершилась с кодом {out.returncode}: {text}")
        return 1
    if expected not in text:
        print(f"  [!] Версия не совпала: ожидалось {expected}, получено {text!r}")
        return 1

    for need in ("models", "demo_data", "holocyt/web/index.html",
                 "holocyt/config/defaults.yaml"):
        p = dist / "_internal" / need
        if not p.exists():
            p = dist / need
        if not p.exists():
            print(f"  [!] В сборке нет: {need}")
            return 1

    print(f"        Запуск: OK ({text})")
    print(f"        Ресурсы на месте: модели, демо, интерфейс, настройки")
    return 0


if __name__ == "__main__":
    sys.exit(main())
