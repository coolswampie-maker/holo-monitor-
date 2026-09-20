#!/usr/bin/env python3
"""Запуск ГОЛОЦИТа: поднимает локальный интерфейс и открывает браузер.

    python3 run.py                  обычный запуск
    python3 run.py --port 9000      другой порт
    python3 run.py --no-browser     не открывать браузер
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Настройка окружения выполняется до импорта numpy и sklearn.
from holocyt._compat import setup as _setup
_setup()

from holocyt.webui import serve

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ГОЛОЦИТ — локальный интерфейс")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    serve(host=a.host, port=a.port, open_browser=not a.no_browser)
