"""Совместимость с Windows.

Рабочее место у заказчика — Windows: штатное ПО микроскопа работает
только там. Этот модуль убирает три типовые причины отказа.

1. Кодировка вывода. В консоли Windows по умолчанию действует кодовая
   страница 866 или 1251. Символы вроде «█» или «⚠» в них отсутствуют,
   и печать падает с UnicodeEncodeError — особенно при перенаправлении
   вывода в файл. Принудительно переводим потоки в UTF-8.

2. Число потоков. Библиотеки линейной алгебры и sklearn независимо
   создают пулы потоков. На многоядерной машине это даёт кратную
   перегрузку вместо ускорения.

3. Кодировка файлов. Без явного указания Python на Windows читает и
   пишет текст в кодировке системы, а не в UTF-8.

Модуль импортируется первым, до numpy и sklearn: часть настроек
действует только до их загрузки.
"""

import os
import sys

IS_WINDOWS = sys.platform.startswith("win")

# Ограничение пулов потоков в библиотеках линейной алгебры. Должно быть
# выставлено ДО импорта numpy, иначе не подействует.
_BLAS_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")


def limit_blas_threads(n=4):
    """Ограничивает потоки BLAS, чтобы они не конкурировали с sklearn."""
    n = str(max(1, min(n, os.cpu_count() or 1)))
    for v in _BLAS_VARS:
        os.environ.setdefault(v, n)


def worker_count(cap=4):
    """Разумное число рабочих потоков для sklearn."""
    return max(1, min(cap, os.cpu_count() or 1))


def force_utf8_output():
    """Переводит stdout/stderr в UTF-8 и включает UTF-8 в консоли Windows."""
    if IS_WINDOWS:
        try:
            import ctypes
            # 65001 — кодовая страница UTF-8.
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def ascii_safe(text):
    """Заменяет символы псевдографики на безопасные.

    Запасной путь на случай, если перевести поток в UTF-8 не удалось.
    """
    return (text.replace("█", "#").replace("·", ".").replace("⚠", "!")
                .replace("²", "2").replace("³", "3").replace("—", "-")
                .replace("«", '"').replace("»", '"').replace("…", "..."))


def can_print_unicode():
    """Выдержит ли текущий поток вывода псевдографику."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "█⚠²".encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def silence_known_deprecations():
    """Гасит два известных предупреждения scikit-image 0.26.

    `remove_small_objects(min_size=...)` и
    `remove_small_holes(area_threshold=...)` объявлены устаревшими.
    Переход на `max_size` — не переименование: у нового параметра другая
    граница (отбрасывается «меньше или равно» вместо «меньше»), поэтому
    менять вызовы без перепроверки сегментации нельзя. Задача записана
    в FUTURE.md.

    До неё эти два предупреждения печатаются по два на кадр и забивают
    окно программы: на восьми кадрах — шестнадцать абзацев поверх
    полезного вывода. Гасим строго их, по тексту сообщения и версии
    библиотеки. Всё остальное — RuntimeWarning, ошибки чтения,
    исключения — проходит как обычно.
    """
    import warnings
    for param in ("min_size", "area_threshold"):
        warnings.filterwarnings(
            "ignore",
            message=r"Parameter `%s` is deprecated since version 0\.26" % param,
            category=FutureWarning,
        )


def setup(blas_threads=4):
    """Полная подготовка окружения. Вызывается первой строкой в точках входа."""
    limit_blas_threads(blas_threads)
    force_utf8_output()
    silence_known_deprecations()
