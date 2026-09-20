#!/usr/bin/env python3
"""Обучение моделей ГОЛОЦИТа на синтетических данных.

Запуск:  python3 scripts/train_models.py

Создаёт в models/:
  segmenter.joblib  — попиксельный классификатор «клетка / фон»;
  cellstate.joblib  — классификатор состояния клетки.

Обе модели работают на процессоре и весят единицы мегабайт: рабочее
место не требует видеокарты и доступа в интернет.
"""

import argparse, json, sys, time
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
import joblib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from holocyt.synth import synth_field, CELL_CLASSES, CLASS_RU
from holocyt.segment import flatten_background, pixel_features, N_FEATURES
from holocyt.features import measure_cells, CLASSIFIER_FEATURES
from holocyt.novelty import NoveltyDetector

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"

# Доли по наблюдению на реальных снимках: округлившихся клеток
# (митоз плюс гибнущие) около 9 %, остальное — распластанные и обломки.
MIXED = {"norm": 0.62, "mitosis": 0.05, "apoptosis": 0.05,
         "necrosis": 0.12, "debris": 0.16}


def train_segmenter(n_fields=14, px_per_field=26000, seed=0):
    """Попиксельный классификатор по банку многомасштабных фильтров."""
    rng = np.random.default_rng(seed)
    Xs, ys = [], []
    for k in range(n_fields):
        f = synth_field(n_cells=int(rng.integers(45, 130)),
                        composition=MIXED,
                        clustering=float(rng.uniform(0.25, 0.65)),
                        noise_std=float(rng.uniform(0.002, 0.007)),
                        drift=float(rng.uniform(0.004, 0.022)),
                        seed=1000 + k)
        flat = flatten_background(f["phase"])
        F = pixel_features(flat).reshape(-1, N_FEATURES)
        y = (f["labels"] > 0).ravel().astype(np.int8)

        # Граница объектов — самая трудная зона, берём её с запасом.
        from scipy import ndimage as ndi
        fg = f["labels"] > 0
        border = ndi.binary_dilation(fg, iterations=3) & ~ndi.binary_erosion(fg, iterations=3)
        border = border.ravel()

        idx_b = np.flatnonzero(border)
        idx_f = np.flatnonzero((y == 1) & ~border)
        idx_g = np.flatnonzero((y == 0) & ~border)
        take = lambda idx, n: rng.choice(idx, size=min(n, len(idx)), replace=False)
        sel = np.concatenate([take(idx_b, px_per_field // 3),
                              take(idx_f, px_per_field // 3),
                              take(idx_g, px_per_field // 3)])
        Xs.append(F[sel]); ys.append(y[sel])
        print(f"  поле {k + 1}/{n_fields}: клеток {len(f['truth']):3d}, "
              f"пикселей взято {len(sel)}")

    X = np.concatenate(Xs); y = np.concatenate(ys)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=1, stratify=y)
    print(f"  обучающая выборка: {Xtr.shape}")

    clf = RandomForestClassifier(
        n_estimators=60, max_depth=None, max_leaf_nodes=900,
        min_samples_leaf=6, n_jobs=-1, random_state=1, class_weight="balanced_subsample",
    )
    t = time.time(); clf.fit(Xtr, ytr)
    print(f"  обучено за {time.time() - t:.1f} с, точность на отложенной "
          f"выборке: {clf.score(Xte, yte):.4f}")
    return clf


def train_cellstate(n_fields=26, seed=0):
    """Классификатор состояния клетки по морфометрии."""
    rng = np.random.default_rng(seed)
    rows, labels = [], []
    for k in range(n_fields):
        f = synth_field(n_cells=int(rng.integers(90, 190)),
                        composition={c: 0.2 for c in CELL_CLASSES},
                        clustering=float(rng.uniform(0.0, 0.35)),
                        noise_std=float(rng.uniform(0.002, 0.007)),
                        drift=float(rng.uniform(0.004, 0.020)),
                        seed=5000 + k)
        flat = flatten_background(f["phase"])
        cls = {t["id"]: t["cls"] for t in f["truth"]}
        for r in measure_cells(f["labels"], flat, cfg=f["cfg"]):
            if r["label"] in cls:
                rows.append(r); labels.append(cls[r["label"]])
        print(f"  поле {k + 1}/{n_fields}: клеток {len(rows)}")

    X = np.array([[r[c] for c in CLASSIFIER_FEATURES] for r in rows], dtype=np.float64)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    y = np.array(labels)

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=2, stratify=y)
    clf = HistGradientBoostingClassifier(
        max_iter=350, learning_rate=0.08, max_leaf_nodes=31,
        l2_regularization=1.0, random_state=2,
    )
    t = time.time(); clf.fit(Xtr, ytr)
    print(f"  обучено за {time.time() - t:.1f} с")
    pred = clf.predict(Xte)
    names = [CLASS_RU[c] for c in clf.classes_]
    print(classification_report(yte, pred, target_names=names, digits=3, zero_division=0))
    print("матрица ошибок (строки — истина):")
    print("  " + "  ".join(f"{n:>9s}" for n in names))
    for n, row in zip(names, confusion_matrix(yte, pred, labels=clf.classes_)):
        print(f"{n:>9s} " + "  ".join(f"{v:9d}" for v in row))

    # Детектор незнакомого обучается на тех же признаках: он должен знать
    # ровно ту область, в которой классификатор имеет право отвечать.
    det = NoveltyDetector().fit(Xtr, feature_names=CLASSIFIER_FEATURES)
    frac_out = 1.0 - det.is_known(Xte).mean()
    print(f"\n  детектор незнакомого: обучен на {det.n_train} клетках, "
          f"на отложенной выборке вне области {100 * frac_out:.1f} %")
    return clf, det


def write_environment_stamp():
    """Фиксирует версии, которыми обучены модели.

    Формат файлов joblib несовместим между версиями scikit-learn и numpy.
    Отпечаток позволяет при загрузке сразу сказать, что среда не та,
    вместо невнятной ошибки о структуре массива узлов дерева.
    """
    import numpy, scipy, sklearn, joblib as jl
    stamp = {"sklearn": sklearn.__version__, "numpy": numpy.__version__,
             "scipy": scipy.__version__, "joblib": jl.__version__,
             "python": f"{sys.version_info.major}.{sys.version_info.minor}"}
    (MODELS / "versions.json").write_text(
        json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nОтпечаток среды обучения: " +
          ", ".join(f"{k} {v}" for k, v in stamp.items()))
    return stamp


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["seg", "state"], default=None)
    a = ap.parse_args()
    MODELS.mkdir(exist_ok=True)

    if a.only in (None, "seg"):
        print("=== Сегментатор ===")
        m = train_segmenter()
        joblib.dump(m, MODELS / "segmenter.joblib", compress=3)
        print(f"  сохранено: models/segmenter.joblib "
              f"({(MODELS / 'segmenter.joblib').stat().st_size / 1e6:.1f} МБ)\n")

    if a.only in (None, "state"):
        print("=== Классификатор состояния ===")
        m, det = train_cellstate()
        joblib.dump(m, MODELS / "cellstate.joblib", compress=3)
        joblib.dump(det, MODELS / "novelty.joblib", compress=3)
        print(f"  сохранено: models/novelty.joblib "
              f"({(MODELS / 'novelty.joblib').stat().st_size / 1e6:.1f} МБ)")
        print(f"  сохранено: models/cellstate.joblib "
              f"({(MODELS / 'cellstate.joblib').stat().st_size / 1e6:.1f} МБ)")

    write_environment_stamp()
