"""Морфометрия отдельных клеток по фазовому изображению.

Показатели разделены на три категории (см. holocyt/parameters.py):

    A  считается прямо из карты фазы — статистика фазы, геометрия
       в пикселях. Верно всегда;
    B  требует калибровки прибора — всё в мкм, мкм², мкм³ и пг.
       БЕЗ КАЛИБРОВКИ НЕ СЧИТАЕТСЯ ВОВСЕ;
    C  наши производные оценки формы, шероховатости и текстуры.

Названия намеренно НЕ повторяют номенклатуру штатного ПО там, где
определения расходятся. Например, наша «изрезанность контура» — это
не Hstudio Irregularity: на площади 572 мкм² и периметре 86,1 мкм из
реальной выгрузки A549 наша формула даёт 0,015, а Hstudio сообщает
0,097. Сопоставление с вердиктами — в parameters.mapping_table().
"""

import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import ConvexHull
from skimage import measure
from skimage.feature import graycomatrix, graycoprops

from . import optics
from .optics import OpticalConfig

# Колонки категории A: считаются всегда, калибровка не нужна.
DIRECT_COLUMNS = [
    "area_px", "perimeter_px", "centroid_x_px", "centroid_y_px",
    "peak_x_px", "peak_y_px", "bbox_length_px", "bbox_breadth_px",
    "eccentricity",
    "phase_sum_waves", "phase_avg_waves", "phase_max_waves",
    "phase_min_waves", "phase_std_waves",
]

# Колонки категории B: только при полной калибровке прибора.
CALIBRATED_COLUMNS = [
    "area_um2", "perimeter_um", "bbox_length_um", "bbox_breadth_um",
    "centroid_x_um", "centroid_y_um",
    "thickness_avg_um", "thickness_max_um", "opd_avg_um", "opd_max_um",
    "optical_volume_um3", "dry_mass_pg", "mass_density_pg_um2",
]

# Колонки категории C: наши производные, калибровка не нужна.
DERIVED_COLUMNS = [
    "shape_irregularity", "shape_convexity", "surface_convexity",
    "aspect_ratio", "phase_peak_ratio",
    "surface_roughness_avg", "surface_roughness_rms",
    "surface_roughness_skew", "surface_roughness_kurt", "roughness_ratio",
    "texture_contrast", "texture_correlation", "texture_energy",
    "texture_entropy", "texture_homogeneity", "texture_maxprob",
    "texture_clustershade",
]

FEATURE_COLUMNS = DIRECT_COLUMNS + CALIBRATED_COLUMNS + DERIVED_COLUMNS

# Признаки классификатора состояния. Порядок менять нельзя: модели
# обучены на массиве без имён, и перестановка колонок молча сломает
# предсказание. Переименование безопасно, перестановка — нет.
#
# В списке есть величины категории B, поэтому классификатор состояния
# работает только при полной калибровке. Это ограничение, а не ошибка:
# он обучен на признаках в физических единицах.
CLASSIFIER_FEATURES = [
    "area_um2", "perimeter_um", "eccentricity", "shape_irregularity",
    "shape_convexity", "surface_convexity", "aspect_ratio",
    "phase_avg_waves", "phase_max_waves", "phase_std_waves", "phase_peak_ratio",
    "thickness_avg_um", "thickness_max_um",
    "optical_volume_um3", "dry_mass_pg", "mass_density_pg_um2",
    "surface_roughness_avg", "surface_roughness_rms",
    "surface_roughness_skew", "surface_roughness_kurt", "roughness_ratio",
    "texture_contrast", "texture_correlation", "texture_energy",
    "texture_entropy", "texture_homogeneity", "texture_maxprob",
]


def _min_area_rect(coords):
    """Минимальный по площади описанный прямоугольник (вращающиеся штангенциркули).

    Возвращает (длина, ширина) в пикселях.
    """
    pts = np.asarray(coords, dtype=float)[:, ::-1]  # (row, col) -> (x, y)
    if len(pts) < 3:
        span = pts.max(axis=0) - pts.min(axis=0) + 1
        return float(max(span)), float(min(span))
    try:
        hull = pts[ConvexHull(pts).vertices]
    except Exception:
        hull = pts
    if len(hull) < 3:
        span = pts.max(axis=0) - pts.min(axis=0) + 1
        return float(max(span)), float(min(span))

    edges = np.diff(np.vstack([hull, hull[:1]]), axis=0)
    angles = np.unique(np.round(np.arctan2(edges[:, 1], edges[:, 0]) % (np.pi / 2), 6))
    best = None
    for a in angles:
        c, s = np.cos(-a), np.sin(-a)
        rot = hull @ np.array([[c, -s], [s, c]])
        span = rot.max(axis=0) - rot.min(axis=0)
        area = span[0] * span[1]
        if best is None or area < best[0]:
            best = (area, span)
    span = best[1]
    return float(max(span)), float(min(span))


def _roughness_stats(patch, mask):
    """Шероховатость: разность исходной и сглаженной поверхности (стр. 110)."""
    smooth = ndi.gaussian_filter(patch * mask, 2.0)
    norm = ndi.gaussian_filter(mask.astype(float), 2.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        smooth = np.where(norm > 1e-6, smooth / norm, 0.0)
    r = (patch - smooth)[mask]
    if r.size < 8:
        return 0.0, 0.0, 0.0, 0.0
    sd = r.std()
    avg = float(np.mean(np.abs(r)))
    rms = float(np.sqrt(np.mean(r ** 2)))
    if sd < 1e-12:
        return avg, rms, 0.0, 0.0
    z = (r - r.mean()) / sd
    return avg, rms, float(np.mean(z ** 3)), float(np.mean(z ** 4) - 3.0)


def _texture(patch, mask, levels=32):
    """Признаки Харалика по матрице смежности уровней (Haralick et al., 1973)."""
    vals = patch[mask]
    out = dict(texture_contrast=0.0, texture_correlation=0.0, texture_energy=0.0,
               texture_entropy=0.0, texture_homogeneity=0.0, texture_maxprob=0.0,
               texture_clustershade=0.0)
    if vals.size < 16:
        return out

    lo, hi = float(vals.min()), float(vals.max())
    if hi - lo < 1e-9:
        return out
    q = np.zeros(patch.shape, dtype=np.uint8)
    q[mask] = np.clip(((patch[mask] - lo) / (hi - lo) * (levels - 1)).astype(int),
                      0, levels - 1) + 0  # 0-й уровень занят фоном не будет: маска ниже
    glcm = graycomatrix(q, distances=[1], angles=[0, np.pi / 4, np.pi / 2, 3 * np.pi / 4],
                        levels=levels, symmetric=True, normed=True)

    out["texture_contrast"] = float(graycoprops(glcm, "contrast").mean())
    out["texture_correlation"] = float(np.nan_to_num(graycoprops(glcm, "correlation")).mean())
    out["texture_energy"] = float(graycoprops(glcm, "energy").mean())
    out["texture_homogeneity"] = float(graycoprops(glcm, "homogeneity").mean())

    P = glcm[:, :, 0, :].mean(axis=2)
    P = P / (P.sum() or 1.0)
    nz = P[P > 0]
    out["texture_entropy"] = float(-np.sum(nz * np.log(nz)))
    out["texture_maxprob"] = float(P.max())
    idx = np.arange(levels)
    mx = float((P.sum(axis=1) * idx).sum())
    my = float((P.sum(axis=0) * idx).sum())
    i, j = np.meshgrid(idx, idx, indexing="ij")
    out["texture_clustershade"] = float(np.sum((i + j - mx - my) ** 3 * P))
    return out


def measure_cells(labels, phase, cal=None, cfg=None, frame=0, time_h=0.0):
    """Считает параметры каждого объекта.

    labels : карта меток (0 — фон);
    phase  : карта фазы с вычтенным фоном, в долях длины волны;
    cal    : Calibration. Если неполная или не задана, физические
             величины (мкм, мкм³, пг) НЕ вычисляются вовсе.
    cfg    : OpticalConfig — устаревший путь, оставлен для внутренних
             вызовов; равнозначен полной калибровке.

    Возвращает список словарей. Набор ключей зависит от наличия
    калибровки, и это намеренно: отсутствующий ключ честнее, чем
    правдоподобное число, взятое из воздуха.
    """
    from .optics import (area_um2 as _area_um2, thickness_um,
                         optical_path_difference_um, optical_volume_um3,
                         dry_mass_pg)

    if cfg is None and cal is not None and getattr(cal, "complete", False):
        cfg = cal.to_optics()
    calibrated = cfg is not None

    phase = np.asarray(phase, dtype=np.float64)
    rows = []

    for rp in measure.regionprops(labels, intensity_image=phase):
        mask = rp.image
        patch = rp.image_intensity
        vals = patch[mask]
        if vals.size < 4:
            continue

        n_px = int(mask.sum())
        phi_sum = float(vals.sum())
        phi_avg = float(vals.mean())
        phi_max = float(vals.max())
        perim_px = float(rp.perimeter)
        length_px, breadth_px = _min_area_rect(rp.coords)

        shape_convexity = float(rp.area / rp.area_convex) if rp.area_convex else 1.0
        env = ndi.grey_closing(patch * mask, size=5)
        env_sum = float(env[mask].sum())
        surface_convexity = float(phi_sum / env_sum) if env_sum > 1e-12 else 1.0

        rough_avg, rough_rms, rough_skew, rough_kurt = _roughness_stats(patch, mask)
        peak = np.unravel_index(np.argmax(np.where(mask, patch, -np.inf)), patch.shape)

        # --- A: прямо из карты фазы, калибровка не нужна ---------------
        row = {
            "frame": int(frame),
            "time_h": float(time_h),
            "label": int(rp.label),
            "area_px": n_px,
            "perimeter_px": perim_px,
            "centroid_x_px": float(rp.centroid_weighted[1]),
            "centroid_y_px": float(rp.centroid_weighted[0]),
            "peak_x_px": float(rp.bbox[1] + peak[1]),
            "peak_y_px": float(rp.bbox[0] + peak[0]),
            "bbox_length_px": length_px,
            "bbox_breadth_px": breadth_px,
            "eccentricity": float(rp.eccentricity),
            "phase_sum_waves": phi_sum,
            "phase_avg_waves": phi_avg,
            "phase_max_waves": phi_max,
            "phase_min_waves": float(vals.min()),
            "phase_std_waves": float(vals.std()),
        }

        # --- C: наши производные, калибровка не нужна ------------------
        # Изрезанность считается в пикселях: она безразмерна, и результат
        # не зависит от того, известен размер пикселя или нет.
        row["shape_irregularity"] = (
            float(perim_px / (2.0 * np.sqrt(np.pi * n_px)) - 1.0) if n_px > 0 else 0.0)
        row["shape_convexity"] = shape_convexity
        row["surface_convexity"] = surface_convexity
        row["aspect_ratio"] = (length_px / breadth_px) if breadth_px > 1e-9 else 1.0
        row["phase_peak_ratio"] = phi_max / phi_avg if phi_avg > 1e-9 else 0.0
        row["surface_roughness_avg"] = rough_avg
        row["surface_roughness_rms"] = rough_rms
        row["surface_roughness_skew"] = rough_skew
        row["surface_roughness_kurt"] = rough_kurt
        row["roughness_ratio"] = rough_rms / phi_avg if phi_avg > 1e-9 else 0.0
        row.update(_texture(patch, mask))

        # --- B: только при полной калибровке ---------------------------
        if calibrated:
            area = _area_um2(n_px, cfg)
            row.update({
                "area_um2": area,
                "perimeter_um": perim_px * cfg.pixel_size_um,
                "bbox_length_um": length_px * cfg.pixel_size_um,
                "bbox_breadth_um": breadth_px * cfg.pixel_size_um,
                "centroid_x_um": row["centroid_x_px"] * cfg.pixel_size_um,
                "centroid_y_um": row["centroid_y_px"] * cfg.pixel_size_um,
                "thickness_avg_um": thickness_um(phi_avg, cfg),
                "thickness_max_um": thickness_um(phi_max, cfg),
                "opd_avg_um": optical_path_difference_um(phi_avg, cfg),
                "opd_max_um": optical_path_difference_um(phi_max, cfg),
                "optical_volume_um3": optical_volume_um3(phi_sum, cfg),
                "dry_mass_pg": dry_mass_pg(phi_sum, cfg),
            })
            row["mass_density_pg_um2"] = (row["dry_mass_pg"] / area) if area > 0 else 0.0

        rows.append(row)

    return rows


def available_columns(calibrated: bool):
    """Какие колонки реально будут в таблице при данной калибровке."""
    cols = list(DIRECT_COLUMNS) + list(DERIVED_COLUMNS)
    if calibrated:
        cols += list(CALIBRATED_COLUMNS)
    return cols
