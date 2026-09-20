"""Физика количественной фазовой микроскопии.

Все формулы взяты из раздела «Morphological parameters» руководства
HoloMonitor M4 (стр. 106-112) и приведённой там литературы.

Соглашение о фазе, как в Hstudio: массив phase хранит сдвиг фазы,
ПОДЕЛЁННЫЙ на 2*pi, то есть в единицах длин волн ("waves").
Именно в этих единицах Hstudio считает параметр Phase shift sum.
"""

from dataclasses import dataclass, asdict

# --- Значения по умолчанию для HoloMonitor M4 -----------------------------
# Значения ниже взяты из паспорта съёмки самого прибора: файл
# DBTransferInfo.xml в выгрузке базы Hstudio содержит атрибуты
# LaserWaveLength, CameraPixelSize, Lens, RefIndexMedium, RefIndexObject.
# Это единственный найденный в данных источник калибровки — в самих
# картах фазы её нет.

# Длина волны лазера, мкм (LaserWaveLength = 633 нм).
DEFAULT_WAVELENGTH_UM = 0.633
# Размер пикселя в плоскости объекта: пиксель камеры, делённый на
# увеличение объектива (CameraPixelSize = 6,71875 мкм; Lens = 20).
# При 1024 пикселях это даёт поле зрения 344 мкм, что соответствует
# паспортным данным M4. Значение стоит сверить с конкретным прибором:
# камера в разных партиях может отличаться.
DEFAULT_PIXEL_SIZE_UM = 6.71875 / 20.0        # = 0,3359 мкм
# Показатели преломления (RefIndexObject / RefIndexMedium; меняются
# в панели Calibration штатного ПО, стр. 36 руководства).
DEFAULT_N_CELL = 1.38
DEFAULT_N_MEDIUM = 1.34
# Удельный рефрактометрический инкремент биомассы, мкм^3/пг.
# Barer (1952); Zangle & Teitell, Nature Methods 11:1221 (2014).
# Практически одинаков для белков, нуклеиновых кислот и углеводов,
# поэтому сухая масса не зависит от предположения о n_cell.
DEFAULT_ALPHA_UM3_PG = 0.18


@dataclass
class OpticalConfig:
    """Оптические параметры прибора и среды."""

    wavelength_um: float = DEFAULT_WAVELENGTH_UM
    pixel_size_um: float = DEFAULT_PIXEL_SIZE_UM
    n_cell: float = DEFAULT_N_CELL
    n_medium: float = DEFAULT_N_MEDIUM
    alpha_um3_pg: float = DEFAULT_ALPHA_UM3_PG

    @property
    def dn(self) -> float:
        """Разность показателей преломления клетка — среда."""
        return self.n_cell - self.n_medium

    @property
    def pixel_area_um2(self) -> float:
        return self.pixel_size_um ** 2

    def to_dict(self) -> dict:
        return asdict(self)


# --- Пересчёт фазы в физические величины ----------------------------------
# Ниже phi всегда в длинах волн (rad / 2pi), как в Hstudio.

def optical_path_difference_um(phi, cfg: OpticalConfig):
    """Оптическая разность хода OPD = lambda * phi, мкм.

    Не зависит от показателей преломления — самая «честная» величина,
    которую прибор измеряет напрямую.
    """
    return phi * cfg.wavelength_um


def thickness_um(phi, cfg: OpticalConfig):
    """Оптическая толщина T = lambda * phi / (n_cell - n_medium), мкм."""
    return phi * cfg.wavelength_um / cfg.dn


def optical_volume_um3(phi_sum: float, cfg: OpticalConfig) -> float:
    """Оптический объём V = lambda * s_xy^2 * phi_sum / (n_cell - n_medium), мкм^3."""
    return cfg.wavelength_um * cfg.pixel_area_um2 * phi_sum / cfg.dn


def dry_mass_pg(phi_sum: float, cfg: OpticalConfig) -> float:
    """Сухая масса клетки, пикограммы.

        m = dn * V / alpha = lambda * s_xy^2 * phi_sum / alpha

    Ключевая величина ГОЛОЦИТа. Hstudio считает phi_sum (параметр
    Phase shift sum), но не переводит его в массу и не отслеживает
    во времени. Между тем именно скорость набора сухой массы —
    ранний и чувствительный показатель отклика клетки на воздействие.
    """
    return cfg.wavelength_um * cfg.pixel_area_um2 * phi_sum / cfg.alpha_um3_pg


def area_um2(n_pixels: int, cfg: OpticalConfig) -> float:
    """Площадь проекции клетки A = N * s_xy^2, мкм^2."""
    return n_pixels * cfg.pixel_area_um2
