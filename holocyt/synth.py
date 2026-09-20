"""Генератор синтетических фазовых изображений клеточных культур.

Нужен для трёх вещей:
  1. демонстрация системы без микроскопа и без клеток;
  2. обучение моделей сегментации и классификации до появления
     размеченных реальных данных;
  3. воспроизводимое регрессионное тестирование.

Модель изображения физическая: фаза от перекрывающихся объектов
складывается вдоль луча, фон содержит медленный дрейф и шум камеры.

ВНИМАНИЕ. Модели, обученные только на синтетике, годятся для
демонстрации и как стартовая точка. Перед применением к реальным
измерениям их необходимо дообучить на снимках конкретной клеточной
линии и валидировать (см. README, раздел «Ограничения»).
"""

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

from .optics import OpticalConfig

# Классы состояния клетки. Порядок фиксирован — по нему обучаются модели.
CELL_CLASSES = ("norm", "mitosis", "apoptosis", "necrosis", "debris")

# Псевдокласс: модель отказалась определять состояние, потому что клетка
# не похожа на обучающие данные (см. holocyt/novelty.py).
UNDETERMINED = "unknown"

CLASS_RU = {
    "unknown": "не определено",
    "norm": "норма",
    "mitosis": "митоз",
    "apoptosis": "апоптоз",
    "necrosis": "некроз",
    "debris": "дебрис",
}

CLASS_COLOR = {
    "unknown": "#C9D1DC",
    "norm": "#2E9E5B",
    "mitosis": "#2F6FD0",
    "apoptosis": "#E0A32E",
    "necrosis": "#D1495B",
    "debris": "#8A8A8A",
}

# Живыми считаются нормальные и делящиеся клетки.
VIABLE_CLASSES = ("norm", "mitosis")

# Классы, которые НЕ являются клетками и потому исключаются из
# знаменателя при расчёте жизнеспособности. Одна погибшая клетка
# распадается на несколько апоптотических телец, и если считать каждое
# отдельной мёртвой клеткой, доля гибели завышается тем сильнее, чем
# выше доза. На дозовой кривой это даёт систематический сдвиг IC50
# в меньшую сторону (проверено: 14,2 вместо заложенных 18,0).
# Обломки учитываются отдельным показателем.
NON_CELL_CLASSES = ("debris",)

# Порядок классов на графиках и в легендах. В отличие от CELL_CLASSES
# включает «не определено», иначе столбцы состава не дают в сумме 100 %.
DISPLAY_CLASSES = CELL_CLASSES + (UNDETERMINED,)


@dataclass
class CellProfile:
    """Диапазоны параметров морфотипа.

    area_um2      — площадь проекции;
    phi_peak      — максимальный сдвиг фазы, в длинах волн;
    elong         — вытянутость (1.0 — круг);
    lobes         — амплитуда гармоник контура (изрезанность);
    roughness     — амплитуда шероховатости поверхности;
    nucleus       — относительная высота ядерного пика.
    """

    area_um2: tuple
    phi_peak: tuple
    elong: tuple
    lobes: tuple
    roughness: tuple
    nucleus: tuple
    dome_power: tuple = (0.6, 1.2)


# Параметры подобраны по описаниям из руководства M4 (стр. 109-111):
# здоровая клетка распластана и гладкая, гибнущая — округляется и
# приобретает выраженную шероховатость; некротическая набухает и теряет
# содержимое, то есть даёт большую площадь при малом сдвиге фазы.
PROFILES = {
    # Параметры подогнаны по реальным снимкам HoloMonitor M4
    # (эксперимент «Example woundhealing», 56 кадров) при размере
    # пикселя 0,336 мкм. Инструмент подгонки — scripts/match_real.py.
    "norm": CellProfile(
        area_um2=(120.0, 380.0), phi_peak=(0.13, 0.29), elong=(1.10, 1.75),
        lobes=(0.22, 0.46), roughness=(0.010, 0.023), nucleus=(0.35, 0.70),
        dome_power=(0.7, 1.3),
    ),
    # Митоз: клетка округляется, сохраняя удвоенное содержимое.
    # Объём тот же -> площадь падает втрое, толщина втрое растёт.
    # Площадь и масса подогнаны по 1215 округлившимся клеткам (толщина
    # не менее 10 мкм) на реальных снимках: медиана площади 189 мкм²,
    # массы 221 пг. Прежние значения были вдвое меньше.
    "mitosis": CellProfile(
        area_um2=(110.0, 300.0), phi_peak=(0.55, 0.92), elong=(1.0, 1.22),
        lobes=(0.08, 0.22), roughness=(0.007, 0.018), nucleus=(0.0, 0.15),
        dome_power=(0.45, 0.62),
    ),
    # Апоптоз: округление, блеббинг и ПОТЕРЯ сухой массы.
    # Апоптотическая клетка тоже округляется, поэтому её толщина должна
    # попадать в тот же диапазон, что у реальных округлившихся, —
    # отличают её изрезанный контур от блеббинга и потеря массы.
    "apoptosis": CellProfile(
        area_um2=(60.0, 220.0), phi_peak=(0.38, 0.72), elong=(1.0, 1.40),
        lobes=(0.40, 0.82), roughness=(0.037, 0.082), nucleus=(0.0, 0.25),
        dome_power=(0.5, 0.9),
    ),
    # Некроз: набухание с потерей содержимого — большая площадь при
    # очень малом сдвиге фазы, плоское плато, рваный контур.
    "necrosis": CellProfile(
        area_um2=(210.0, 500.0), phi_peak=(0.038, 0.100), elong=(1.05, 1.55),
        lobes=(0.34, 0.66), roughness=(0.018, 0.040), nucleus=(0.0, 0.10),
        dome_power=(0.30, 0.55),
    ),
    # Дебрис: апоптотические тельца и обломки.
    "debris": CellProfile(
        area_um2=(6.0, 30.0), phi_peak=(0.07, 0.33), elong=(1.0, 1.7),
        lobes=(0.45, 0.90), roughness=(0.021, 0.062), nucleus=(0.0, 0.10),
        dome_power=(0.4, 0.9),
    ),
}


def _uni(rng, rng_pair):
    lo, hi = rng_pair
    return rng.uniform(lo, hi)


def _render_cell(cls, cfg: OpticalConfig, rng):
    """Возвращает (patch_phase, patch_mask) — локальный фрагмент клетки."""
    p = PROFILES[cls]

    area_px = _uni(rng, p.area_um2) / cfg.pixel_area_um2
    r0 = np.sqrt(area_px / np.pi)
    elong = _uni(rng, p.elong)
    lobe_amp = _uni(rng, p.lobes)
    phi_peak = _uni(rng, p.phi_peak)
    rough = _uni(rng, p.roughness)
    nuc = _uni(rng, p.nucleus)
    power = _uni(rng, p.dome_power)
    theta0 = rng.uniform(0, np.pi)

    # Габарит патча с запасом на изрезанность контура и сглаживание.
    half = int(np.ceil(r0 * np.sqrt(elong) * (1 + 2.0 * lobe_amp) + 6))
    half = max(half, 4)
    yy, xx = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float64)

    # Поворот и анизотропное сжатие -> эллиптическая основа.
    ct, st = np.cos(theta0), np.sin(theta0)
    xr = xx * ct + yy * st
    yr = -xx * st + yy * ct
    # Полуоси a = r0*sqrt(elong), b = r0/sqrt(elong) — площадь сохраняется.
    se = np.sqrt(elong)
    xe, ye = xr / se, yr * se

    r = np.sqrt(xe ** 2 + ye ** 2)
    ang = np.arctan2(ye, xe)

    # Контур: радиус модулируется гармониками со 2-й по 10-ю. Высокие
    # гармоники дают рваный край — так выглядит блеббинг при апоптозе.
    amps, pert = [], np.zeros_like(r)
    for k in range(2, 21):
        # Показатель 0,9 вместо 1,2: высокие гармоники затухают медленнее,
        # и контур получается мелко изрезанным, как у настоящей клетки
        # с ламеллоподиями и контактами с соседями. Подобрано по замеру
        # изрезанности на реальных снимках (scripts/match_real.py).
        a_k = lobe_amp / (k - 1) ** 0.9
        amps.append(a_k)
        pert += a_k * np.cos(k * ang + rng.uniform(0, 2 * np.pi))
    # Нормировка сохраняет заданную площадь: <R^2> = r0^2 (1 + sum a_k^2 / 2).
    rad = r0 * (1.0 + pert) / np.sqrt(1.0 + 0.5 * float(np.sum(np.square(amps))))
    rad = np.maximum(rad, 0.25 * r0)

    inside = r <= rad
    if not inside.any():
        inside = r <= r0

    # Купол фазы: гладко спадает от центра к краю.
    with np.errstate(invalid="ignore", divide="ignore"):
        rn = np.clip(r / np.maximum(rad, 1e-6), 0.0, 1.0)
    dome = np.clip(1.0 - rn ** 2, 0.0, None) ** power

    # Ядро — смещённый гауссов пик (в руководстве: пик толщины обычно
    # соответствует ядру и ядрышкам, стр. 109).
    nx, ny = rng.normal(0, r0 * 0.18, 2)
    nucleus_sigma = max(r0 * 0.30, 1.5)
    nucleus = np.exp(-(((xx - nx) ** 2 + (yy - ny) ** 2) / (2 * nucleus_sigma ** 2)))

    phase = phi_peak * (dome + nuc * nucleus * dome)

    # Шероховатость: полосовой шум, обрезанный маской.
    noise = rng.normal(0, 1, phase.shape)
    noise = ndi.gaussian_filter(noise, 1.0) - ndi.gaussian_filter(noise, 3.0)
    nstd = noise.std() or 1.0
    phase = phase + rough * (noise / nstd) * (dome > 0.05)

    mask = inside & (phase > phi_peak * 0.02)
    mask = ndi.binary_fill_holes(ndi.binary_closing(mask, np.ones((3, 3))))
    if mask is None or not mask.any():
        mask = inside

    phase = np.where(mask, np.clip(phase, 0.0, None), 0.0)
    # Лёгкое сглаживание — конечное разрешение оптики.
    phase = ndi.gaussian_filter(phase, 0.8) * mask
    return phase, mask


def synth_field(
    n_cells=70,
    shape=(768, 1024),
    composition=None,
    cfg: OpticalConfig = None,
    clustering=0.45,
    max_overlap=0.18,
    noise_std=0.004,
    drift=0.012,
    seed=None,
):
    """Синтезирует одно поле зрения.

    Параметры
    ---------
    n_cells      : сколько клеток разместить;
    composition  : dict {класс: доля}; по умолчанию здоровая культура;
    clustering   : доля клеток, подсаживаемых вплотную к уже размещённым
                   (создаёт касающиеся клетки — основную трудность
                   для порогового метода);
    max_overlap  : предельная доля площади клетки, которую разрешено
                   перекрыть соседям (контактное торможение в монослое);
    noise_std    : шум камеры в единицах фазы (длины волн);
    drift        : амплитуда медленного дрейфа фона.

    Возвращает
    ----------
    dict с ключами: phase, labels, truth (список записей о клетках), cfg.
    """
    cfg = cfg or OpticalConfig()
    rng = np.random.default_rng(seed)
    # Доли по наблюдению на реальных снимках M4: округлившихся клеток
    # (митоз плюс гибнущие) около 9 %, обломков заметная часть.
    composition = composition or {"norm": 0.62, "mitosis": 0.05,
                                  "apoptosis": 0.05, "necrosis": 0.12,
                                  "debris": 0.16}

    classes = list(composition.keys())
    probs = np.array([composition[c] for c in classes], dtype=float)
    probs = probs / probs.sum()

    H, W = shape
    phase = np.zeros((H, W), dtype=np.float64)
    labels = np.zeros((H, W), dtype=np.int32)
    truth = []
    placed = []

    for i in range(n_cells):
        cls = classes[rng.choice(len(classes), p=probs)]
        patch, mask = _render_cell(cls, cfg, rng)
        ph, pw = patch.shape
        half_h, half_w = ph // 2, pw // 2

        for _attempt in range(24):
            # Часть клеток сажаем вплотную к уже размещённым.
            if placed and rng.random() < clustering:
                cy0, cx0 = placed[rng.integers(len(placed))]
                d = rng.uniform(0.75, 1.25) * max(half_h, half_w) * 2
                a = rng.uniform(0, 2 * np.pi)
                cy = int(cy0 + d * np.sin(a))
                cx = int(cx0 + d * np.cos(a))
            else:
                cy = int(rng.integers(half_h, H - half_h))
                cx = int(rng.integers(half_w, W - half_w))

            cy = int(np.clip(cy, half_h, H - half_h - 1))
            cx = int(np.clip(cx, half_w, W - half_w - 1))
            sl = (slice(cy - half_h, cy - half_h + ph), slice(cx - half_w, cx - half_w + pw))
            # Прикреплённые клетки контактно ингибируются: они соприкасаются
            # краями, но почти не наползают друг на друга. Ограничиваем
            # перекрытие, иначе эталон становится физически недостижимым.
            occl = float((labels[sl][mask] > 0).mean())
            if occl <= max_overlap:
                break
        else:
            continue

        phase[sl] += patch
        lab = labels[sl]
        lab[mask] = i + 1
        # Сильно перекрытые ранее размещённые клетки помечаем как затенённые.
        labels[sl] = lab
        placed.append((cy, cx))
        truth.append({"id": i + 1, "cls": cls, "cy": cy, "cx": cx})

    # Фон: медленный дрейф (неидеальная компенсация опорного пучка).
    gy, gx = np.mgrid[0:H, 0:W]
    gy = gy / H - 0.5
    gx = gx / W - 0.5
    bg = (drift * (rng.normal() * gx + rng.normal() * gy
                   + 0.6 * rng.normal() * (gx ** 2 - gy ** 2)
                   + 0.6 * rng.normal() * gx * gy))
    coarse = ndi.gaussian_filter(rng.normal(0, 1, (H, W)), 60)
    coarse = coarse / (coarse.std() or 1.0)
    phase = phase + bg + drift * 0.5 * coarse

    # Шум камеры.
    phase = phase + rng.normal(0, noise_std, (H, W))

    # Убираем метки клеток, которые оказались полностью перекрыты.
    keep = set(np.unique(labels)) - {0}
    truth = [t for t in truth if t["id"] in keep]

    return {"phase": phase.astype(np.float32), "labels": labels,
            "truth": truth, "cfg": cfg}
