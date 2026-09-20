"""Импорт данных из чужих систем.

Каждый импортёр обязан помечать происхождение каждой величины: взята
она из файла прибора или подставлена нами. Смешивать нельзя — иначе
подставленное значение в отчёте неотличимо от измеренного.
"""

from .provenance import Provenance, Value, MEASURED, ASSUMED, COMPUTED

__all__ = ["Provenance", "Value", "MEASURED", "ASSUMED", "COMPUTED"]
