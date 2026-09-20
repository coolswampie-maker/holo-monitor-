#!/usr/bin/env python3
"""Запуск ГОЛОЦИТа.

Из исходников:   python run.py
Из сборки:       ГОЛОЦИТ.exe

Поднимает локальный интерфейс и открывает браузер. Наружу программа
не обращается: порт слушается только на петлевом адресе.
"""

import argparse
import sys
from pathlib import Path


def _app_dir() -> Path:
    """Каталог приложения — и для исходников, и для упакованной версии."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


sys.path.insert(0, str(_app_dir()))

# Настройка окружения выполняется до импорта numpy и sklearn.
from holocyt._compat import setup as _setup       # noqa: E402
_setup()

from holocyt.diagnostics import setup_logging, log_path   # noqa: E402
from holocyt.version import PRODUCT, VERSION             # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=f"{PRODUCT} {VERSION}")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=None,
                    help="по умолчанию 8765, при занятости — следующий свободный")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--version", action="version", version=f"{PRODUCT} {VERSION}")
    a = ap.parse_args()

    log = setup_logging()
    try:
        from holocyt.webui import serve
        serve(host=a.host, port=a.port, open_browser=not a.no_browser)
        return 0
    except Exception as exc:
        from holocyt.diagnostics.errors import log_exception
        msg, hint = log_exception(log, exc, "Запуск программы")
        print(f"\n  {msg}")
        if hint:
            print(f"  {hint}")
        print(f"  Журнал: {log_path()}")
        # Пауза нужна при запуске двойным щелчком, чтобы окно не закрылось
        # мгновенно. Если ввода нет (запуск из сценария или службы), поверх
        # понятного сообщения не должно появляться EOFError.
        try:
            input("\n  Нажмите Enter, чтобы закрыть окно…")
        except (EOFError, KeyboardInterrupt):
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
