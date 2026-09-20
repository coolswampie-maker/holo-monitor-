"""Реестр показателей: что мы измеряем, из чего и с какой уверенностью.

Единственный источник истины о показателях. Интерфейс, протокол и
выгрузка берут названия, единицы и категории отсюда — чтобы нигде не
разошлось.

Три категории
-------------
A (DIRECT)      Считается прямо из карты фазы, калибровка не нужна.
                Статистика фазы, геометрия в пикселях, счёт объектов.
                Эти величины верны всегда.

B (CALIBRATED)  Требует калибровки прибора: размера пикселя, длины
                волны, показателей преломления. Без них НЕ показывается
                вовсе — подставлять значения по умолчанию нельзя, иначе
                в протоколе появятся микрометры и пикограммы, которых
                прибор не измерял.

C (DERIVED)     Наши производные показатели: оценки формы, шероховатость,
                текстура, состояние клетки. Считаются нами, к параметрам
                Hstudio отношения не имеют, даже если название похоже.

Сопоставление с Hstudio
-----------------------
Вердикты присваивались так:

MATCHES              формула приведена в руководстве M4 (стр. 106-112)
                     и воспроизведена буквально;
APPROXIMATES         величина та же по смыслу, но детали реализации в
                     руководстве не описаны;
DIFFERENT_DEFINITION проверено численно: определения расходятся;
CANNOT_VALIDATE      сверить не с чем — нет ни формулы, ни данных;
NOT_IN_HSTUDIO       наш показатель, в штатном ПО отсутствует.
"""

from dataclasses import dataclass

DIRECT = "A"
CALIBRATED = "B"
DERIVED = "C"

CATEGORY_RU = {
    DIRECT: "измерено из карты фазы",
    CALIBRATED: "требует калибровки прибора",
    DERIVED: "вычислено ГОЛОЦИТом",
}

MATCHES = "MATCHES"
APPROXIMATES = "APPROXIMATES"
DIFFERENT = "DIFFERENT_DEFINITION"
CANNOT_VALIDATE = "CANNOT_VALIDATE"
NOT_IN_HSTUDIO = "NOT_IN_HSTUDIO"

VERDICT_RU = {
    MATCHES: "формула из руководства, воспроизведена",
    APPROXIMATES: "тот же смысл, детали реализации неизвестны",
    DIFFERENT: "определения расходятся, проверено численно",
    CANNOT_VALIDATE: "сверить не с чем",
    NOT_IN_HSTUDIO: "в штатном ПО отсутствует",
}


@dataclass(frozen=True)
class Parameter:
    key: str                 # имя колонки в таблице
    ru: str                  # как показывать пользователю
    unit: str                # единица, пусто если безразмерная
    category: str            # A / B / C
    hstudio: str = ""        # имя в штатном ПО, пусто если нет
    verdict: str = NOT_IN_HSTUDIO
    note: str = ""

    @property
    def needs_calibration(self):
        return self.category == CALIBRATED

    @property
    def display(self):
        """Название для интерфейса и протокола."""
        base = f"{self.ru}, {self.unit}" if self.unit else self.ru
        return base + (" (ГОЛОЦИТ)" if self.category == DERIVED else "")


P = [
    # --- A: прямо из карты фазы -------------------------------------
    Parameter("area_px", "Площадь", "пикселей", DIRECT,
              "Area", APPROXIMATES,
              "у нас — число пикселей выше порога; порог у Hstudio иной"),
    Parameter("perimeter_px", "Периметр", "пикселей", DIRECT,
              "Perimeter length", CANNOT_VALIDATE,
              "способ оценки периметра в руководстве не описан"),
    Parameter("centroid_x_px", "Центр масс X", "пикселей", DIRECT),
    Parameter("centroid_y_px", "Центр масс Y", "пикселей", DIRECT),
    Parameter("bbox_length_px", "Длина габарита", "пикселей", DIRECT,
              "Boxed length", APPROXIMATES,
              "минимальный по площади описанный прямоугольник, как в руководстве"),
    Parameter("bbox_breadth_px", "Ширина габарита", "пикселей", DIRECT,
              "Boxed breadth", APPROXIMATES),
    Parameter("eccentricity", "Вытянутость", "", DIRECT,
              "Eccentricity", CANNOT_VALIDATE,
              "определение в руководстве не приведено"),
    Parameter("phase_sum_waves", "Сумма сдвига фазы", "длин волн", DIRECT,
              "Phase shift sum", MATCHES,
              "определение из руководства, стр. 110"),
    Parameter("phase_avg_waves", "Сдвиг фазы средний", "длин волн", DIRECT,
              "Phase shift avg.", MATCHES),
    Parameter("phase_max_waves", "Сдвиг фазы макс.", "длин волн", DIRECT,
              "Phase shift max.", MATCHES),
    Parameter("phase_min_waves", "Сдвиг фазы мин.", "длин волн", DIRECT,
              "Phase shift min.", MATCHES),
    Parameter("phase_std_waves", "Сдвиг фазы, СКО", "длин волн", DIRECT,
              "Phase shift std. dev.", MATCHES),

    # --- B: требуют калибровки --------------------------------------
    Parameter("area_um2", "Площадь", "мкм²", CALIBRATED,
              "Area", APPROXIMATES),
    Parameter("perimeter_um", "Периметр", "мкм", CALIBRATED,
              "Perimeter length", CANNOT_VALIDATE),
    Parameter("bbox_length_um", "Длина габарита", "мкм", CALIBRATED,
              "Boxed length", APPROXIMATES),
    Parameter("bbox_breadth_um", "Ширина габарита", "мкм", CALIBRATED,
              "Boxed breadth", APPROXIMATES),
    Parameter("thickness_avg_um", "Оптическая толщина средняя", "мкм", CALIBRATED,
              "Optical thickness avg", MATCHES,
              "T = λ·φ/(n_кл − n_ср), формула из руководства, стр. 107"),
    Parameter("thickness_max_um", "Оптическая толщина макс.", "мкм", CALIBRATED,
              "Optical thickness max", MATCHES),
    Parameter("opd_avg_um", "Разность хода средняя", "мкм", CALIBRATED,
              "OPD avg", MATCHES, "OPD = λ·φ, стр. 108"),
    Parameter("opd_max_um", "Разность хода макс.", "мкм", CALIBRATED,
              "OPD max", MATCHES),
    Parameter("optical_volume_um3", "Оптический объём", "мкм³", CALIBRATED,
              "Optical volume", MATCHES,
              "V = λ·s²·Σφ/(n_кл − n_ср), стр. 107"),
    Parameter("dry_mass_pg", "Сухая масса", "пг", CALIBRATED,
              "", NOT_IN_HSTUDIO,
              "m = λ·s²·Σφ/α; в штатном ПО не вычисляется"),
    Parameter("mass_density_pg_um2", "Плотность массы", "пг/мкм²", CALIBRATED,
              "", NOT_IN_HSTUDIO),

    # --- C: наши производные ----------------------------------------
    Parameter("shape_irregularity", "Изрезанность контура", "", DERIVED,
              "Irregularity", DIFFERENT,
              "проверено численно: на площади 572 мкм² и периметре 86,1 мкм "
              "наша формула даёт 0,015, Hstudio сообщает 0,097"),
    Parameter("shape_convexity", "Выпуклость контура", "", DERIVED,
              "Shape convexity", CANNOT_VALIDATE),
    Parameter("surface_convexity", "Выпуклость поверхности", "", DERIVED,
              "Hull convexity", DIFFERENT,
              "у нас приближение через морфологическое замыкание, "
              "а не трёхмерная выпуклая оболочка"),
    Parameter("aspect_ratio", "Отношение сторон габарита", "", DERIVED),
    Parameter("phase_peak_ratio", "Отношение пика к среднему", "", DERIVED),
    Parameter("surface_roughness_avg", "Шероховатость средняя", "", DERIVED,
              "Roughness avg.", CANNOT_VALIDATE,
              "способ сглаживания в руководстве не описан"),
    Parameter("surface_roughness_rms", "Шероховатость СКЗ", "", DERIVED,
              "Roughness RMS", CANNOT_VALIDATE),
    Parameter("surface_roughness_skew", "Шероховатость, асимметрия", "", DERIVED,
              "Roughness skewness", CANNOT_VALIDATE),
    Parameter("surface_roughness_kurt", "Шероховатость, эксцесс", "", DERIVED,
              "Roughness kurtosis", CANNOT_VALIDATE),
    Parameter("roughness_ratio", "Шероховатость к фазе", "", DERIVED),
    Parameter("texture_contrast", "Текстура: контраст", "", DERIVED,
              "Texture contrast", APPROXIMATES,
              "признаки Харалика; параметры матрицы смежности "
              "в руководстве не указаны"),
    Parameter("texture_correlation", "Текстура: корреляция", "", DERIVED,
              "Texture correlation", APPROXIMATES),
    Parameter("texture_energy", "Текстура: энергия", "", DERIVED,
              "Texture energy", APPROXIMATES),
    Parameter("texture_entropy", "Текстура: энтропия", "", DERIVED,
              "Texture entropy", APPROXIMATES),
    Parameter("texture_homogeneity", "Текстура: однородность", "", DERIVED,
              "Texture homogeneity", APPROXIMATES),
    Parameter("texture_maxprob", "Текстура: макс. вероятность", "", DERIVED,
              "Texture maxprob", APPROXIMATES),
    Parameter("texture_clustershade", "Текстура: сдвиг кластера", "", DERIVED,
              "Texture clustershade", APPROXIMATES),
    Parameter("cell_state", "Состояние клетки", "", DERIVED,
              "", NOT_IN_HSTUDIO,
              "классификатор ГОЛОЦИТа; в штатном ПО такого показателя нет"),
]

BY_KEY = {p.key: p for p in P}


def of(key):
    return BY_KEY.get(key)


def by_category(cat):
    return [p for p in P if p.category == cat]


def calibrated_keys():
    return [p.key for p in P if p.needs_calibration]


def display_name(key):
    p = BY_KEY.get(key)
    return p.display if p else key


def mapping_table():
    """Сопоставление с Hstudio для документации и протокола."""
    rows = []
    for p in P:
        if not p.hstudio:
            continue
        rows.append({"hstudio": p.hstudio, "holocyt": p.key,
                     "display": p.display, "verdict": p.verdict,
                     "verdict_ru": VERDICT_RU[p.verdict],
                     "category": p.category, "note": p.note})
    return rows
