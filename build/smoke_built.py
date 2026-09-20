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


def probe_startup(exe):
    """Запускает собранное приложение и убеждается, что интерфейс отвечает.

    Проверки `--version` недостаточно: argparse печатает версию и завершает
    работу ещё до импорта numpy, поэтому заведомо неработоспособная сборка
    её проходит. Здесь программа поднимается целиком, со всеми C-расширениями.
    """
    import json
    import socket
    import time
    import urllib.request

    with socket.socket() as s:                 # свободный порт, чтобы не
        s.bind(("127.0.0.1", 0))               # мешать уже запущенной копии
        port = s.getsockname()[1]

    proc = subprocess.Popen(
        [str(exe), "--no-browser", "--port", str(port)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    try:
        url = f"http://127.0.0.1:{port}/api/config"
        deadline = time.time() + 120
        while time.time() < deadline:
            if proc.poll() is not None:
                out = (proc.stdout.read() if proc.stdout else "")[-2000:]
                return False, ("приложение завершилось с кодом "
                               f"{proc.returncode}: {out}")
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    cfg = json.load(r)
            except Exception:
                time.sleep(1)
                continue
            return True, f"интерфейс отвечает на порту {port}, версия {cfg.get('version')}"
        return False, "интерфейс не ответил за 120 с"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()


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

    # Сначала — стартует ли программа вообще. Иначе отсутствие любого
    # ресурса (например, демо-данных) заслоняет полностью нерабочую сборку.
    ok, detail = probe_startup(exe)
    if not ok:
        print(f"  [!] Собранное приложение не стартует: {detail}")
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
    print(f"        Интерфейс: {detail}")
    print(f"        Ресурсы на месте: модели, демо, интерфейс, настройки")
    return 0


if __name__ == "__main__":
    sys.exit(main())
