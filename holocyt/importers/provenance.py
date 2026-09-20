"""Происхождение величины: измерено, предположено или вычислено.

Зачем. При импорте чужих данных часть величин приходит из файлов
прибора, а часть приходится подставлять — например, размер пикселя,
которого в карте фазы нет. Если не различать их явно, подставленное
значение попадёт в протокол наравне с измеренным, и отличить их будет
невозможно. Это прямой путь к ложным выводам.

Три источника:

  MEASURED  — прочитано из файла, созданного прибором или его ПО;
  ASSUMED   — подставлено нами, в файле отсутствует;
  COMPUTED  — вычислено нами из измеренного.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

MEASURED = "measured"
ASSUMED = "assumed"
COMPUTED = "computed"

SOURCE_RU = {
    MEASURED: "из файла прибора",
    ASSUMED: "подставлено нами",
    COMPUTED: "вычислено нами",
}


@dataclass(frozen=True)
class Value:
    """Величина вместе с указанием, откуда она взялась."""

    value: Any
    source: str
    origin: Optional[str] = None     # конкретный файл или поле
    note: Optional[str] = None

    @property
    def is_measured(self) -> bool:
        return self.source == MEASURED

    def __repr__(self):
        tail = f", {self.origin}" if self.origin else ""
        return f"{self.value!r} [{SOURCE_RU[self.source]}{tail}]"


@dataclass
class Provenance:
    """Набор величин с происхождением."""

    values: dict = field(default_factory=dict)

    def set(self, key, value, source, origin=None, note=None):
        self.values[key] = Value(value, source, origin, note)
        return self

    def measured(self, key, value, origin=None, note=None):
        return self.set(key, value, MEASURED, origin, note)

    def assumed(self, key, value, origin=None, note=None):
        return self.set(key, value, ASSUMED, origin, note)

    def get(self, key, default=None):
        v = self.values.get(key)
        return v.value if v is not None else default

    def by_source(self, source):
        return {k: v for k, v in self.values.items() if v.source == source}

    def report(self):
        """Текстовая сводка: что измерено, что подставлено."""
        lines = []
        for src in (MEASURED, ASSUMED, COMPUTED):
            items = self.by_source(src)
            if not items:
                continue
            lines.append(f"{SOURCE_RU[src].capitalize()}:")
            for k, v in sorted(items.items()):
                tail = f"   ({v.origin})" if v.origin else ""
                lines.append(f"    {k} = {v.value}{tail}")
                if v.note:
                    lines.append(f"        {v.note}")
        return "\n".join(lines)

    def warnings(self):
        """Предупреждения о подставленных значениях."""
        out = []
        for k, v in sorted(self.by_source(ASSUMED).items()):
            out.append(f"{k}: значение в данных прибора отсутствует, "
                       f"подставлено {v.value}"
                       + (f". {v.note}" if v.note else ""))
        return out

    def to_dict(self):
        return {k: {"value": v.value, "source": v.source, "origin": v.origin,
                    "note": v.note} for k, v in self.values.items()}
