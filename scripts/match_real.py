#!/usr/bin/env python3
"""Сравнение синтетических клеток с реальными по морфометрии.

Инструмент настройки генератора. Синтетика нужна не сама по себе, а как
замена реальным данным при обучении, поэтому её признаки должны
совпадать с признаками настоящих клеток. Скрипт показывает, по каким
признакам расхождение наибольшее.

Мерой служит статистика Колмогорова — Смирнова: 0 — распределения
совпадают, 1 — не пересекаются.

    python3 scripts/match_real.py
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from holocyt.features import measure_cells, CLASSIFIER_FEATURES
from holocyt.importers.hstudio import load_experiment as _le, read_phase_matrix


def list_phase_matrices(p):
    return _le(p).phase_files
from holocyt.optics import OpticalConfig
from holocyt.segment import flatten_background, segment_ml
from holocyt.pipeline import load_model
from holocyt.synth import synth_field

# Та же смесь классов, что используется при обучении моделей.
MIXED = {"norm": 0.62, "mitosis": 0.05, "apoptosis": 0.05,
         "necrosis": 0.12, "debris": 0.16}

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "recovery" / "extracted" / "Example woundhealing"

# Признаки, по которым идёт настройка. Безразмерные не зависят от
# размера пикселя, поэтому сравнение по ним самое надёжное.
KEY = ["shape_irregularity", "shape_convexity", "eccentricity", "aspect_ratio",
       "phase_peak_ratio", "surface_roughness_avg", "surface_roughness_rms",
       "texture_homogeneity", "texture_entropy", "texture_energy",
       "texture_contrast", "area_um2", "perimeter_um", "phase_avg_waves",
       "phase_max_waves", "dry_mass_pg", "mass_density_pg_um2"]


def real_features(cfg, min_area, step=6, limit=None):
    seg = load_model("segmenter")
    files = list_phase_matrices(REAL)[::step]
    if limit:
        files = files[:limit]
    X, cov = [], []
    for p in files:
        ph, _ = read_phase_matrix(p)
        lab, flat = segment_ml(ph, seg, cfg=cfg, min_area_um2=min_area)
        cov.append(float((lab > 0).mean()))
        X += [[r[k] for k in KEY] for r in measure_cells(lab, flat, cfg=cfg)]
    return np.nan_to_num(np.array(X)), float(np.mean(cov))


def synth_features(cfg, min_area, n_fields=6, n_cells=150, clustering=0.5,
                   use_truth=True):
    seg = None if use_truth else load_model("segmenter")
    X, cov = [], []
    for k in range(n_fields):
        f = synth_field(n_cells=n_cells, shape=(768, 1024), cfg=cfg,
                        clustering=clustering, seed=30000 + k,
                        composition=MIXED)
        flat = flatten_background(f["phase"])
        lab = f["labels"] if use_truth else segment_ml(f["phase"], seg, cfg=cfg,
                                                       min_area_um2=min_area)[0]
        cov.append(float((lab > 0).mean()))
        X += [[r[k2] for k2 in KEY] for r in measure_cells(lab, flat, cfg=cfg)]
    return np.nan_to_num(np.array(X)), float(np.mean(cov))


def compare(Xs, Xr, cov_s, cov_r):
    rows = []
    for i, name in enumerate(KEY):
        ks = stats.ks_2samp(Xs[:, i], Xr[:, i]).statistic
        rows.append((ks, name, float(np.median(Xs[:, i])), float(np.median(Xr[:, i]))))
    rows.sort(reverse=True)
    print(f"\n  покрытие кадра клетками: синтетика {100 * cov_s:.0f} %, "
          f"реальные {100 * cov_r:.0f} %")
    print(f"  клеток: синтетика {len(Xs)}, реальные {len(Xr)}\n")
    print(f"  {'признак':<24s} {'KS':>6s} {'синтетика':>12s} {'реальные':>12s} {'отн.':>7s}")
    print("  " + "-" * 66)
    for ks, n, a, b in rows:
        rel = b / a if abs(a) > 1e-9 else float("inf")
        print(f"  {n:<24s} {ks:6.3f} {a:12.3f} {b:12.3f} {rel:7.2f}")
    print(f"\n  средний KS по всем признакам: {np.mean([r[0] for r in rows]):.3f}")
    print(f"  признаков с KS > 0,4: {sum(1 for r in rows if r[0] > 0.4)} из {len(rows)}")
    return float(np.mean([r[0] for r in rows]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-area", type=float, default=60.0)
    ap.add_argument("--n-cells", type=int, default=150)
    ap.add_argument("--clustering", type=float, default=0.5)
    ap.add_argument("--segmented", action="store_true",
                    help="брать синтетику через сегментатор, а не по эталону")
    a = ap.parse_args()
    cfg = OpticalConfig()
    print(f"размер пикселя {cfg.pixel_size_um:.4f} мкм, "
          f"минимальная площадь {a.min_area} мкм²")
    Xr, cr = real_features(cfg, a.min_area)
    Xs, cs = synth_features(cfg, a.min_area, n_cells=a.n_cells,
                            clustering=a.clustering, use_truth=not a.segmented)
    compare(Xs, Xr, cs, cr)
