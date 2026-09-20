#!/usr/bin/env python3
"""Сравнение сегментации ГОЛОЦИТа с пороговыми методами штатного ПО.

Поля для теста генерируются с другими зёрнами, чем обучающие.
"""
import sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holocyt.synth import synth_field
from holocyt.segment import segment_ml, segment_threshold
from holocyt.evaluate import filter_labels, match_iou
from holocyt.pipeline import load_model

MIXED = {"norm": 0.55, "mitosis": 0.15, "apoptosis": 0.14, "necrosis": 0.08, "debris": 0.08}
METHODS = ["otsu", "minimum_error", "adaptive_gaussian", "ГОЛОЦИТ (ML)"]


def main(n_fields=8, density="mixed"):
    seg = load_model("segmenter")
    rng = np.random.default_rng(777)
    acc = {m: [] for m in METHODS}
    print(f"полей: {n_fields}, плотность: {density}\n")

    for k in range(n_fields):
        n_cells = int(rng.integers(60, 140)) if density == "mixed" else 170
        clu = float(rng.uniform(0.35, 0.7)) if density == "mixed" else 0.8
        f = synth_field(n_cells=n_cells, composition=MIXED, clustering=clu,
                        noise_std=float(rng.uniform(0.003, 0.007)),
                        drift=float(rng.uniform(0.006, 0.020)), seed=90000 + k)
        gt = filter_labels(f["labels"], min_area_px=int(40 / f["cfg"].pixel_area_um2))

        for m in METHODS:
            t = time.time()
            if m.startswith("ГОЛОЦИТ"):
                lab, _ = segment_ml(f["phase"], seg, cfg=f["cfg"])
            else:
                lab, _ = segment_threshold(f["phase"], cfg=f["cfg"], method=m)
            r = match_iou(gt, lab)
            r["sec"] = time.time() - t
            acc[m].append(r)

    hdr = f"{'метод':>22s} {'F1':>7s} {'точн.':>7s} {'полн.':>7s} {'IoU':>7s} {'ошибка счёта':>13s} {'с/кадр':>7s}"
    print(hdr); print("-" * len(hdr))
    for m in METHODS:
        rs = acc[m]
        print(f"{m:>22s} "
              f"{np.mean([r['f1'] for r in rs]):7.3f} "
              f"{np.mean([r['precision'] for r in rs]):7.3f} "
              f"{np.mean([r['recall'] for r in rs]):7.3f} "
              f"{np.mean([r['mean_iou'] for r in rs]):7.3f} "
              f"{np.mean([r['count_error'] for r in rs]) * 100:+12.1f}% "
              f"{np.mean([r['sec'] for r in rs]):7.2f}")





def benchmark_morphometry(n_fields=6):
    """Насколько ошибка границы искажает измеряемые параметры.

    Для совпавших клеток сравниваем измеренные величины с эталонными.
    Это главный практический довод: точность границы напрямую определяет
    точность площади, сдвига фазы и, следовательно, сухой массы.
    """
    from holocyt.features import measure_cells
    from holocyt.segment import flatten_background

    seg = load_model("segmenter")
    rng = np.random.default_rng(31337)
    methods = ["minimum_error", "adaptive_gaussian", "ГОЛОЦИТ (ML)"]
    err = {m: {"area_um2": [], "dry_mass_pg": [], "perimeter_um": []} for m in methods}

    for k in range(n_fields):
        f = synth_field(n_cells=int(rng.integers(60, 120)), composition=MIXED,
                        clustering=float(rng.uniform(0.35, 0.65)),
                        noise_std=0.005, drift=0.012, seed=70000 + k)
        cfg = f["cfg"]
        flat = flatten_background(f["phase"])
        gt = filter_labels(f["labels"], min_area_px=int(40 / cfg.pixel_area_um2))
        truth_rows = {r["label"]: r for r in measure_cells(gt, flat, cfg=cfg)}

        for m in methods:
            if m.startswith("ГОЛОЦИТ"):
                lab, _ = segment_ml(f["phase"], seg, cfg=cfg)
            else:
                lab, _ = segment_threshold(f["phase"], cfg=cfg, method=m)
            rows = {r["label"]: r for r in measure_cells(lab, flat, cfg=cfg)}

            # Сопоставляем по максимальному перекрытию.
            for t_id, t_row in truth_rows.items():
                mask = gt == t_id
                ov = np.bincount(lab[mask], minlength=int(lab.max()) + 1)
                ov[0] = 0
                if ov.max() == 0:
                    continue
                p_id = int(ov.argmax())
                inter = ov[p_id]
                union = mask.sum() + (lab == p_id).sum() - inter
                if inter / union < 0.5:
                    continue
                p_row = rows.get(p_id)
                if p_row is None:
                    continue
                for key in err[m]:
                    tv = t_row[key]
                    if tv > 1e-9:
                        err[m][key].append(abs(p_row[key] - tv) / tv * 100.0)

    print("\nОшибка измерения параметров у совпавших клеток "
          "(медиана относительной ошибки, %):\n")
    hdr = f"{'метод':>22s} {'площадь':>10s} {'сухая масса':>13s} {'периметр':>10s} {'n клеток':>9s}"
    print(hdr); print("-" * len(hdr))
    for m in methods:
        e = err[m]
        print(f"{m:>22s} "
              f"{np.median(e['area_um2']):9.1f}% "
              f"{np.median(e['dry_mass_pg']):12.1f}% "
              f"{np.median(e['perimeter_um']):9.1f}% "
              f"{len(e['area_um2']):9d}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Сравнение сегментации с пороговыми методами")
    ap.add_argument("-n", "--fields", type=int, default=8)
    ap.add_argument("--density", default="mixed", choices=["mixed", "dense"])
    ap.add_argument("--morphometry", action="store_true",
                    help="дополнительно оценить ошибку измеряемых параметров")
    a = ap.parse_args()
    main(n_fields=a.fields, density=a.density)
    if a.morphometry:
        benchmark_morphometry(n_fields=max(4, a.fields // 2))
