"""Оценка качества сегментации: сопоставление объектов по IoU."""

import numpy as np
from skimage import measure, morphology, segmentation


def filter_labels(labels, min_area_px=160, drop_edge=True):
    """Приводит эталон к тем же правилам отбора, что и результат системы."""
    out = morphology.remove_small_objects(np.asarray(labels).astype(np.int32),
                                          min_size=min_area_px)
    if drop_edge:
        out = segmentation.clear_border(out)
    return measure.label(out)


def match_iou(truth, pred, iou_threshold=0.5):
    """Жадное сопоставление эталонных и найденных объектов по IoU.

    Возвращает словарь с precision, recall, F1, средним IoU совпавших
    объектов и относительной ошибкой подсчёта клеток.
    """
    truth = np.asarray(truth, dtype=np.int64)
    pred = np.asarray(pred, dtype=np.int64)
    t_ids = np.unique(truth); t_ids = t_ids[t_ids > 0]
    p_ids = np.unique(pred); p_ids = p_ids[p_ids > 0]
    n_t, n_p = len(t_ids), len(p_ids)

    if n_t == 0 or n_p == 0:
        return {"n_truth": n_t, "n_pred": n_p, "tp": 0,
                "precision": 0.0, "recall": 0.0, "f1": 0.0,
                "mean_iou": 0.0, "count_error": float(n_p - n_t)}

    t_idx = {v: i for i, v in enumerate(t_ids)}
    p_idx = {v: i for i, v in enumerate(p_ids)}

    # Матрица пересечений через совместную гистограмму.
    both = (truth > 0) & (pred > 0)
    ti = np.array([t_idx[v] for v in truth[both]])
    pi = np.array([p_idx[v] for v in pred[both]])
    inter = np.zeros((n_t, n_p), dtype=np.int64)
    np.add.at(inter, (ti, pi), 1)

    t_area = np.array([(truth == v).sum() for v in t_ids])
    p_area = np.array([(pred == v).sum() for v in p_ids])
    union = t_area[:, None] + p_area[None, :] - inter
    iou = np.where(union > 0, inter / np.maximum(union, 1), 0.0)

    # Жадное сопоставление от наибольшего IoU.
    pairs = sorted(zip(*np.nonzero(iou >= iou_threshold)),
                   key=lambda ij: -iou[ij])
    used_t, used_p, matched = set(), set(), []
    for i, j in pairs:
        if i in used_t or j in used_p:
            continue
        used_t.add(i); used_p.add(j); matched.append(iou[i, j])

    tp = len(matched)
    precision = tp / n_p
    recall = tp / n_t
    f1 = 2 * precision * recall / (precision + recall) if tp else 0.0
    return {"n_truth": n_t, "n_pred": n_p, "tp": tp,
            "precision": precision, "recall": recall, "f1": f1,
            "mean_iou": float(np.mean(matched)) if matched else 0.0,
            "count_error": (n_p - n_t) / n_t}
