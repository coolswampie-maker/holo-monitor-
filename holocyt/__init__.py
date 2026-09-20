"""ГОЛОЦИТ — анализ данных цифровой голографической микроскопии.

Работает с выгрузкой штатного ПО микроскопа HoloMonitor M4 (Hstudio).

Версия задаётся ровно в одном месте — holocyt/version.py. Всё
остальное, включая VERSION.txt, порождается из неё.
"""

from .version import VERSION as __version__, PRODUCT as __product__, SUBTITLE

__all__ = ["__version__", "__product__", "SUBTITLE"]
