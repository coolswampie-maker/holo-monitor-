"""Калибровка прибора с явным указанием происхождения каждой величины.

Правило одно: **молча подставлять значения нельзя**. Если размер
пикселя неизвестен, программа не показывает микрометры вовсе. Иначе в
протоколе появятся физические величины, которых прибор не измерял, и
отличить их от настоящих будет невозможно.

Статусы:

    measured     прочитано из файла, созданного прибором
                 (DBTransferInfo.xml: CameraPixelSize, Lens,
                 LaserWaveLength, RefIndexMedium, RefIndexObject);
    imported     задано пользователем явно — он берёт ответственность
                 на себя;
    calculated   выведено из измеренных величин
                 (размер пикселя = пиксель камеры / увеличение);
    unavailable  неизвестно. Зависящие показатели не считаются.
"""

from dataclasses import dataclass, field
from typing import Optional

MEASURED = "measured"
IMPORTED = "imported"
CALCULATED = "calculated"
UNAVAILABLE = "unavailable"

STATUS_RU = {
    MEASURED: "измерено прибором",
    IMPORTED: "задано пользователем",
    CALCULATED: "выведено из измеренных",
    UNAVAILABLE: "отсутствует",
}

# Что обязательно должно быть известно, чтобы считать физические величины.
REQUIRED = ("pixel_size_um", "wavelength_um", "n_cell", "n_medium")

FIELD_RU = {
    "pixel_size_um": "Размер пикселя в плоскости объекта, мкм",
    "wavelength_um": "Длина волны лазера, мкм",
    "n_cell": "Показатель преломления клеток",
    "n_medium": "Показатель преломления среды",
    "camera_pixel_um": "Размер пикселя камеры, мкм",
    "lens": "Увеличение объектива",
    "alpha_um3_pg": "Рефрактометрический инкремент α, мкм³/пг",
}


@dataclass(frozen=True)
class Quantity:
    """Величина со статусом и источником."""

    value: Optional[float]
    status: str
    source: str = ""
    note: str = ""

    @property
    def known(self):
        return self.value is not None and self.status != UNAVAILABLE

    def __repr__(self):
        if not self.known:
            return f"<нет данных: {STATUS_RU[self.status]}>"
        tail = f" из {self.source}" if self.source else ""
        return f"{self.value:g} [{STATUS_RU[self.status]}{tail}]"


def unknown(note=""):
    return Quantity(None, UNAVAILABLE, note=note)


@dataclass
class Calibration:
    """Оптические параметры прибора. Отсутствующие остаются отсутствующими."""

    pixel_size_um: Quantity = field(default_factory=unknown)
    wavelength_um: Quantity = field(default_factory=unknown)
    n_cell: Quantity = field(default_factory=unknown)
    n_medium: Quantity = field(default_factory=unknown)
    camera_pixel_um: Quantity = field(default_factory=unknown)
    lens: Quantity = field(default_factory=unknown)
    # Табличная константа из литературы, не свойство прибора.
    alpha_um3_pg: Quantity = field(
        default_factory=lambda: Quantity(
            0.18, CALCULATED, "Barer 1952; Zangle & Teitell 2014",
            "табличная величина, одинакова для белков, нуклеиновых кислот "
            "и углеводов; от прибора не зависит"))

    @property
    def complete(self):
        """Достаточно ли данных, чтобы считать физические величины."""
        return all(getattr(self, k).known for k in REQUIRED)

    @property
    def missing(self):
        return [k for k in REQUIRED if not getattr(self, k).known]

    @property
    def dn(self):
        if not (self.n_cell.known and self.n_medium.known):
            return None
        return self.n_cell.value - self.n_medium.value

    def status_line(self):
        if self.complete:
            srcs = {getattr(self, k).status for k in REQUIRED}
            if srcs == {MEASURED}:
                return "Калибровка загружена из данных прибора"
            if IMPORTED in srcs:
                return "Калибровка задана пользователем"
            return "Калибровка получена из данных прибора"
        return "Калибровка не найдена — физические величины недоступны"

    def rows(self):
        """Таблица для интерфейса и протокола."""
        out = []
        for k in ("pixel_size_um", "wavelength_um", "n_cell", "n_medium",
                  "camera_pixel_um", "lens", "alpha_um3_pg"):
            q = getattr(self, k)
            out.append({
                "key": k, "name": FIELD_RU[k],
                "value": q.value if q.known else None,
                "status": q.status, "status_ru": STATUS_RU[q.status],
                "source": q.source, "note": q.note,
                "required": k in REQUIRED,
            })
        return out

    def to_optics(self):
        """Переводит в OpticalConfig. Только при полной калибровке."""
        from .optics import OpticalConfig
        if not self.complete:
            raise ValueError(
                "калибровка неполная, физические величины считать нельзя. "
                "Отсутствует: " + ", ".join(FIELD_RU[k] for k in self.missing))
        return OpticalConfig(
            wavelength_um=self.wavelength_um.value,
            pixel_size_um=self.pixel_size_um.value,
            n_cell=self.n_cell.value, n_medium=self.n_medium.value,
            alpha_um3_pg=self.alpha_um3_pg.value)


def from_transfer_xml(optics: dict, source: str) -> Calibration:
    """Строит калибровку по разобранному DBTransferInfo.xml."""
    c = Calibration()
    cam, lens = optics.get("camera_pixel_um"), optics.get("lens")
    if cam:
        c.camera_pixel_um = Quantity(cam, MEASURED, source)
    if lens:
        c.lens = Quantity(lens, MEASURED, source)
    if cam and lens:
        c.pixel_size_um = Quantity(
            cam / lens, CALCULATED, source,
            "размер пикселя камеры, делённый на увеличение объектива")
    for key, xml_name in (("wavelength_um", "LaserWaveLength"),
                          ("n_cell", "RefIndexObject"),
                          ("n_medium", "RefIndexMedium")):
        v = optics.get(key)
        if v:
            setattr(c, key, Quantity(v, MEASURED, f"{source}, {xml_name}"))
    return c


def from_user(pixel_size_um=None, wavelength_um=None, n_cell=None,
              n_medium=None, base: Calibration = None) -> Calibration:
    """Дополняет калибровку значениями, заданными пользователем."""
    c = base or Calibration()
    for key, val in (("pixel_size_um", pixel_size_um),
                     ("wavelength_um", wavelength_um),
                     ("n_cell", n_cell), ("n_medium", n_medium)):
        if val is not None:
            setattr(c, key, Quantity(
                float(val), IMPORTED, "указано при запуске",
                "значение введено оператором, прибором не подтверждено"))
    return c
