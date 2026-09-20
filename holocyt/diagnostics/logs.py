"""Журнал работы программы.

Пишется рядом с приложением, в logs/holocyt.log. Полный текст ошибки
с трассировкой попадает сюда — пользователю показывается только
понятное сообщение.

Массивы в журнал не пишутся: только имена файлов, числа и состояния.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

_READY = False


def app_root() -> Path:
    """Каталог приложения. Работает и из исходников, и из сборки."""
    if getattr(sys, "frozen", False):          # упаковано PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def log_dir() -> Path:
    """Каталог журналов. Если рядом с программой писать нельзя —
    уходим в пользовательский каталог, чтобы не падать."""
    d = app_root() / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".w"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return d
    except Exception:
        alt = Path(os.path.expanduser("~")) / ".holocyt" / "logs"
        alt.mkdir(parents=True, exist_ok=True)
        return alt


def log_path() -> Path:
    return log_dir() / "holocyt.log"


def setup_logging(level=None, keep=None):
    """Настраивает журнал. Вызывается один раз при запуске."""
    global _READY
    if _READY:
        return logging.getLogger("holocyt")
    from ..config import get
    from ..version import PRODUCT, VERSION, BUILD_DATE

    level = level or get("logging", "level", "INFO")
    keep = keep or get("logging", "keep_files", 5)

    log = logging.getLogger("holocyt")
    log.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    log.handlers.clear()

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=2_000_000, backupCount=int(keep), encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        pass                                   # без журнала работать всё равно можно

    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)               # в консоль — только важное
    sh.setFormatter(logging.Formatter("  %(levelname)s: %(message)s"))
    log.addHandler(sh)

    _READY = True
    log.info("=" * 60)
    log.info("%s %s (сборка %s) запущена", PRODUCT, VERSION, BUILD_DATE)
    log.info("Python %s, платформа %s", sys.version.split()[0], sys.platform)
    log.info("Каталог приложения: %s", app_root())
    log.info("Журнал: %s", log_path())
    return log


def get_logger(name="holocyt"):
    setup_logging()
    return logging.getLogger(name if name.startswith("holocyt") else f"holocyt.{name}")
