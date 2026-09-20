"""Сегментация клеток на фазовом изображении.

Два метода, которые система показывает рядом:

  * `segment_threshold` — пороговый (Otsu и др.), как в штатном ПО
    микроскопа. Оставлен намеренно: он служит точкой отсчёта и
    наглядно показывает, что даёт машинное обучение.

  * `segment_ml` — обученный попиксельный классификатор по банку
    многомасштабных фильтров с последующим разделением слипшихся
    клеток методом водоразделов. Подход того же семейства, что и в
    ilastik: работает на процессоре, обучается за секунды, модель
    весит килобайты — это важно для автономного рабочего места.
"""

import numpy as np
from scipy import ndimage as ndi
from skimage import feature, filters, measure, morphology, segmentation

from .optics import OpticalConfig

# Масштабы банка фильтров, пиксели.
SCALES = (1.0, 2.0, 4.0, 8.0)
N_FEATURES = 2 + 4 * len(SCALES)


def flatten_background(phase, bg_percentile=45.0, order=2, n_iter=2):
    """Убирает медленный дрейф фона.

    Дрейф возникает из-за неидеальной компенсации опорного пучка и
    температурных эффектов в инкубаторе. Подгоняем полиномиальную
    поверхность по пикселям, уверенно отнесённым к фону, и вычитаем.
    """
    phase = np.asarray(phase, dtype=np.float64)
    H, W = phase.shape
    yy, xx = np.mgrid[0:H, 0:W]
    y = (yy / H - 0.5).ravel()
    x = (xx / W - 0.5).ravel()

    terms = [np.ones_like(x)]
    for total in range(1, order + 1):
        for i in range(total + 1):
            terms.append((x ** (total - i)) * (y ** i))
    A = np.stack(terms, axis=1)

    flat = phase.ravel()
    mask = flat <= np.percentile(flat, bg_percentile)
    for _ in range(n_iter):
        coef, *_ = np.linalg.lstsq(A[mask], flat[mask], rcond=None)
        bg = A @ coef
        resid = flat - bg
        thr = np.percentile(resid, bg_percentile)
        new_mask = resid <= thr
        if new_mask.sum() < 1000:
            break
        mask = new_mask

    out = (flat - bg).reshape(H, W)
    # Нулевой уровень — мода распределения остатка. Медиана сместилась бы
    # вверх из-за вклада клеток, а мода устойчива к любой их доле в кадре.
    return out - _background_mode(out)


def _background_mode(resid, bins=512):
    """Наиболее вероятный уровень фона по сглаженной гистограмме остатка."""
    lo, hi = np.percentile(resid, [0.5, 70.0])
    sel = resid[(resid >= lo) & (resid <= hi)]
    if sel.size < 100:
        return float(np.median(resid))
    hist, edges = np.histogram(sel, bins=bins)
    hist = ndi.gaussian_filter1d(hist.astype(float), 3.0)
    k = int(np.argmax(hist))
    return float(0.5 * (edges[k] + edges[k + 1]))


def pixel_features(phase):
    """Банк признаков для попиксельного классификатора.

    Возвращает массив (H, W, N_FEATURES): сглаживания, модуль градиента,
    лапласиан и локальный разброс на четырёх масштабах. Такой набор
    описывает и «есть ли здесь вещество», и «край это или середина».
    """
    phase = np.asarray(phase, dtype=np.float32)
    feats = [phase, ndi.median_filter(phase, size=3)]
    for s in SCALES:
        g = ndi.gaussian_filter(phase, s)
        gy, gx = np.gradient(g)
        grad = np.hypot(gy, gx)
        lap = ndi.gaussian_laplace(phase, s)
        mean = ndi.uniform_filter(phase, size=int(4 * s) | 1)
        sq = ndi.uniform_filter(phase ** 2, size=int(4 * s) | 1)
        std = np.sqrt(np.clip(sq - mean ** 2, 0, None))
        feats += [g, grad, lap, std]
    return np.stack(feats, axis=-1).astype(np.float32)


def _split_touching(binary, phase, min_distance_px=9, seed_phase_weight=0.80,
                    typical_area_px=None):
    """Разделяет слипшиеся клетки водоразделом.

    Маркеры ищем по сумме нормированного расстояния до фона и нормированной
    сглаженной фазы: у каждой клетки есть свой купол толщины с максимумом
    около ядра, и это надёжнее, чем одно расстояние, когда клетки
    распластаны и касаются краями.

    Нормировка выполняется ОТДЕЛЬНО для каждой связной компоненты. Иначе
    одна яркая округлившаяся клетка (митоз даёт сдвиг фазы втрое больше
    обычного) подавляет маркеры всех тусклых распластанных клеток в кадре.
    """
    binary = np.asarray(binary, dtype=bool)
    if not binary.any():
        return np.zeros(binary.shape, dtype=np.int32)

    comps, n_comp = ndi.label(binary)
    dist_full = ndi.distance_transform_edt(binary)
    ph_full = ndi.gaussian_filter(np.where(binary, phase, 0.0), 2.0)

    out = np.zeros(binary.shape, dtype=np.int32)
    next_label = 1
    slices = ndi.find_objects(comps)

    for cid, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        # Поля по краю, чтобы водораздел не прилипал к границе выреза.
        sl = tuple(slice(max(a.start - 2, 0), min(a.stop + 2, n))
                   for a, n in zip(sl, binary.shape))
        m = comps[sl] == cid
        area = int(m.sum())
        if area == 0:
            continue

        d = dist_full[sl] * m
        ph = ph_full[sl] * m
        dn = d / (d.max() or 1.0)
        pn = ph / (ph.max() or 1.0)
        score = ndi.gaussian_filter(
            (1.0 - seed_phase_weight) * dn + seed_phase_weight * pn, 1.2) * m

        md = min_distance_px
        # Крупный конгломерат обязан распасться: если маркер один, а площадь
        # намного больше типичной клетки, ищем максимумы плотнее.
        for attempt in range(3):
            peaks = feature.peak_local_max(score, labels=m, min_distance=md,
                                           exclude_border=False, threshold_rel=0.10)
            if typical_area_px is None or len(peaks) >= max(1, area // int(2.2 * typical_area_px)):
                break
            md = max(3, int(md * 0.65))

        markers = np.zeros(m.shape, dtype=np.int32)
        if len(peaks):
            markers[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
            markers = ndi.label(morphology.dilation(markers > 0, morphology.disk(1)))[0]
        else:
            markers = m.astype(np.int32)

        ws = segmentation.watershed(-score, markers, mask=m)
        keep = ws > 0
        out[sl][keep] = ws[keep] + next_label - 1
        next_label += int(ws.max())

    return out


# Порог отсева и типичный размер клетки задаются В ПИКСЕЛЯХ: сегментация
# не должна зависеть от того, известна калибровка прибора или нет.
DEFAULT_MIN_AREA_PX = 500
DEFAULT_TYPICAL_AREA_PX = 2600

# Минимальный средний сдвиг фазы, при котором объект считается клеткой.
# В долях длины волны. При 633 нм это 25 нм разности хода — уровень шума
# восстановления голограммы.
#
# Порог введён после осмотра реальных кадров: в области царапины
# сегментатор выделял пустой фон как объекты. Распределение там
# двугорбое — мусор около 0,025, настоящие клетки от 0,086. Отсечение
# по 0,04 убирает 73 ложных объекта из 178 в редком кадре и лишь один
# из 278 в плотном.
DEFAULT_MIN_PHASE_AVG = 0.04


def _drop_low_signal(labels, phase, min_phase_avg):
    """Убирает объекты со слишком слабым сигналом — это фон, а не клетки."""
    if not min_phase_avg or labels.max() == 0:
        return labels
    n = int(labels.max())
    total = ndi.sum_labels(phase, labels, index=range(1, n + 1))
    count = ndi.sum_labels(np.ones_like(phase), labels, index=range(1, n + 1))
    with np.errstate(invalid="ignore", divide="ignore"):
        avg = np.where(count > 0, total / np.maximum(count, 1), 0.0)
    drop = np.flatnonzero(avg < min_phase_avg) + 1
    if len(drop):
        labels = labels.copy()
        labels[np.isin(labels, drop)] = 0
        labels = measure.label(labels)
    return labels


def _postprocess(labels, min_area_px, drop_edge):
    """Отсев мелочи и, по желанию, клеток на краю кадра."""
    min_px = max(int(min_area_px), 1)
    labels = morphology.remove_small_objects(labels, min_size=min_px)
    if drop_edge:
        labels = segmentation.clear_border(labels)
    return measure.label(labels > 0) * (labels > 0) if False else measure.label(labels)


def segment_threshold(phase, cfg: OpticalConfig = None, method="otsu",
                      min_area_px=DEFAULT_MIN_AREA_PX, drop_edge_cells=True,
                      split=True, pre_smooth=True,
                      typical_area_px=DEFAULT_TYPICAL_AREA_PX,
                      min_phase_avg=DEFAULT_MIN_PHASE_AVG):
    """Пороговая сегментация — воспроизводит логику штатного ПО.

    method: 'otsu' | 'otsu_blocks' | 'minimum_error' | 'adaptive_gaussian'
    """
    flat = flatten_background(phase)
    work = ndi.gaussian_filter(flat, 1.2) if pre_smooth else flat

    if method == "otsu":
        binary = work > filters.threshold_otsu(work)
    elif method == "otsu_blocks":
        binary = work > filters.threshold_local(work, block_size=127, method="mean",
                                                offset=-0.5 * filters.threshold_otsu(work))
    elif method == "minimum_error":
        binary = work > filters.threshold_li(work)
    elif method == "adaptive_gaussian":
        binary = work > filters.threshold_local(work, block_size=101,
                                                method="gaussian", offset=-0.004)
    else:
        raise ValueError(f"неизвестный метод порога: {method}")

    binary = ndi.binary_fill_holes(morphology.opening(binary, morphology.disk(2)))
    labels = (_split_touching(binary, flat, typical_area_px=typical_area_px)
              if split else measure.label(binary))
    labels = _drop_low_signal(labels, flat, min_phase_avg)
    return _postprocess(labels, min_area_px, drop_edge_cells), flat


def segment_ml(phase, model, cfg: OpticalConfig = None, prob_threshold=0.55,
               min_area_px=DEFAULT_MIN_AREA_PX, drop_edge_cells=True,
               min_distance_px=9, return_prob=False,
               typical_area_px=DEFAULT_TYPICAL_AREA_PX,
               min_phase_avg=DEFAULT_MIN_PHASE_AVG):
    """Сегментация обученным попиксельным классификатором.

    Все размеры — в пикселях: калибровка прибора здесь не нужна и не
    используется. Параметр cfg оставлен только для совместимости
    вызовов и на результат не влияет.
    """
    flat = flatten_background(phase)
    X = pixel_features(flat).reshape(-1, N_FEATURES)
    prob = model.predict_proba(X)[:, 1].reshape(flat.shape).astype(np.float32)

    binary = prob > prob_threshold
    binary = morphology.remove_small_holes(binary, area_threshold=64)
    binary = morphology.opening(binary, morphology.disk(1))

    labels = _split_touching(binary, flat, min_distance_px=min_distance_px,
                             typical_area_px=typical_area_px)
    labels = _drop_low_signal(labels, flat, min_phase_avg)
    labels = _postprocess(labels, min_area_px, drop_edge_cells)
    if return_prob:
        return labels, flat, prob
    return labels, flat
