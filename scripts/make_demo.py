#!/usr/bin/env python3
"""Генерация демонстрационного эксперимента по цитотоксичности.

Создаёт на диске каталог с TIFF-изображениями и manifest.csv — ровно
в том формате, в каком система принимает реальные данные. Это позволяет
показывать работу ГОЛОЦИТа без микроскопа и без клеточной культуры.

Запуск:  python3 scripts/make_demo.py
"""

import argparse, csv, sys
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from holocyt.synth import synth_field
from holocyt.tox import hill4

ROOT = Path(__file__).resolve().parents[1]

# Параметры «истинного» отклика — система должна их восстановить.
TRUE_IC50 = 18.0      # мкМ
TRUE_HILL = 1.5
CONCENTRATIONS = [0.0, 1.0, 3.0, 6.0, 12.0, 25.0, 50.0, 100.0, 200.0]
N_FIELDS = 3
N_CELLS_CONTROL = 105


def composition_at(conc):
    """Как меняется состав популяции с ростом дозы.

    Картина типовая для цитотоксикологии: при низких дозах преобладает
    апоптоз, при высоких добавляется некроз — мембрана рвётся раньше,
    чем успевает отработать программа гибели.
    """
    v = float(hill4(conc, 0.04, 0.96, TRUE_IC50, TRUE_HILL))
    d = 1.0 - v
    # Доля некроза среди погибших растёт с дозой.
    x = conc / TRUE_IC50
    necro_share = 0.10 + 0.45 * x / (1.0 + x)
    comp = {
        "norm": v * 0.90,
        "mitosis": v * 0.10 * v,           # деление тормозится раньше гибели
        "apoptosis": d * (0.85 - necro_share) if d > 0 else 0.0,
        "necrosis": d * necro_share,
        "debris": d * 0.15 + 0.01,
    }
    total = sum(comp.values())
    return {k: val / total for k, val in comp.items()}, v


def main(out, seed=2024, shape=(768, 1024)):
    out_dir = out
    out = Path(out_dir)
    (out / "img").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    rows = []

    print(f"Истинные параметры: IC50 = {TRUE_IC50} мкМ, наклон = {TRUE_HILL}\n")
    for conc in CONCENTRATIONS:
        comp, v = composition_at(conc)
        # Погибшие клетки открепляются — плотность в лунке падает.
        n_base = N_CELLS_CONTROL * (0.20 + 0.80 * v)
        group = "контроль" if conc == 0 else f"{conc:g} мкМ"
        print(f"  {group:>10s}: жизнеспособных {100 * v:5.1f} %, "
              f"клеток в поле ~{n_base:5.0f}")

        for f_i in range(1, N_FIELDS + 1):
            n = max(int(rng.normal(n_base, n_base * 0.10)), 6)
            fld = synth_field(
                n_cells=n, shape=shape, composition=comp,
                clustering=float(np.clip(rng.normal(0.45 * v + 0.10, 0.06), 0.0, 0.8)),
                noise_std=float(rng.uniform(0.0035, 0.0060)),
                drift=float(rng.uniform(0.006, 0.018)),
                seed=int(rng.integers(0, 2 ** 31)),
            )
            fname = f"img/c{conc:06.1f}_f{f_i}.tif"
            tifffile.imwrite(out / fname, fld["phase"].astype(np.float32),
                             compression="zlib")
            rows.append({"file": fname, "group": group, "concentration": conc,
                         "replicate": 1, "field": f_i, "time_h": 24.0})

    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "group", "concentration",
                                           "replicate", "field", "time_h"])
        w.writeheader(); w.writerows(rows)

    size = sum(p.stat().st_size for p in (out / "img").glob("*.tif")) / 1e6
    print(f"\nГотово: {len(rows)} изображений, {size:.1f} МБ -> {out}")
    print(f"Манифест: {out / 'manifest.csv'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(ROOT / "demo_data" / "cytotox_demo"))
    ap.add_argument("--seed", type=int, default=2024)
    main(**vars(ap.parse_args()))
