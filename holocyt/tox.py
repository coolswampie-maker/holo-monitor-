"""Оценка цитотоксичности: кривые «доза — эффект» и расчёт IC50.

Методическая рамка соответствует логике ГОСТ ISO 10993-5-2011
(исследования на цитотоксичность in vitro, определение IC50), но
показатель отклика измеряется безмаркерно — по изображению живых
клеток, без МТТ, нейтрального красного и разрушения культуры.
Это позволяет снимать кинетику на одной и той же лунке многократно.

Показатели отклика (endpoints), которые считает система:
  viability   — доля жизнеспособных клеток (норма + митоз), %;
  cell_count  — число клеток в поле;
  dry_mass    — суммарная сухая биомасса, пг;
  confluence  — доля площади, занятой клетками, %;
  mitotic_idx — митотический индекс, %.
"""

import numpy as np
from scipy.optimize import curve_fit

from .synth import VIABLE_CLASSES, NON_CELL_CLASSES

ENDPOINTS = {
    "viability": "Жизнеспособность, %",
    "cell_count": "Число клеток",
    "dry_mass": "Суммарная сухая масса, пг",
    "mean_dry_mass": "Средняя сухая масса клетки, пг",
    "confluence": "Конфлюентность, %",
    "mitotic_idx": "Митотический индекс, %",
    "debris_idx": "Доля обломков, %",
}


def hill4(x, bottom, top, ic50, hill):
    """Четырёхпараметрическая логистическая модель (Hill).

    x — концентрация (в тех же единицах, что и ic50), не логарифм.
    """
    x = np.maximum(np.asarray(x, dtype=float), 0.0)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        # При x = 0 отношение равно нулю (hill > 0), и функция даёт `top` —
        # то есть отклик нулевой дозы совпадает с контролем.
        ratio = np.where(x > 0, np.power(np.where(x > 0, x, 1.0) / ic50, hill), 0.0)
    ratio = np.where(np.isfinite(ratio), ratio, 1e300)
    return bottom + (top - bottom) / (1.0 + ratio)


def fit_dose_response(conc, response, n_boot=400, seed=0):
    """Подгоняет модель Хилла и возвращает IC50 с доверительным интервалом.

    conc     — концентрации (>0 для подгонки; нулевой контроль задаёт `top`);
    response — отклик в тех же единицах, что и endpoint.

    Доверительный интервал IC50 — бутстрэп по остаткам (n_boot повторов).
    """
    conc = np.asarray(conc, dtype=float)
    resp = np.asarray(response, dtype=float)
    ok = np.isfinite(conc) & np.isfinite(resp)
    conc, resp = conc[ok], resp[ok]

    pos = conc > 0
    if pos.sum() < 4 or len(np.unique(conc[pos])) < 4:
        return {"ok": False, "reason": "нужно не менее 4 ненулевых концентраций"}

    top0 = float(np.max(resp))
    bot0 = float(np.min(resp))
    # Стартовое приближение IC50 — концентрация, ближайшая к полуэффекту.
    half = 0.5 * (top0 + bot0)
    ic0 = float(conc[pos][np.argmin(np.abs(resp[pos] - half))])
    p0 = [bot0, top0, max(ic0, 1e-9), 1.0]
    lo = [-np.inf, -np.inf, conc[pos].min() / 1e3, 0.1]
    hi = [np.inf, np.inf, conc[pos].max() * 1e3, 10.0]

    try:
        popt, pcov = curve_fit(hill4, conc, resp, p0=p0, bounds=(lo, hi), maxfev=30000)
    except Exception as e:
        return {"ok": False, "reason": f"подгонка не сошлась: {e}"}

    pred = hill4(conc, *popt)
    ss_res = float(np.sum((resp - pred) ** 2))
    ss_tot = float(np.sum((resp - resp.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Бутстрэп остатков — честнее, чем ковариация, при малом числе точек.
    rng = np.random.default_rng(seed)
    resid = resp - pred
    boots = []
    for _ in range(n_boot):
        y = pred + rng.choice(resid, size=resid.size, replace=True)
        try:
            pb, _ = curve_fit(hill4, conc, y, p0=popt, bounds=(lo, hi), maxfev=8000)
            boots.append(pb[2])
        except Exception:
            continue
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) \
        if len(boots) >= 40 else (float("nan"), float("nan"))

    bottom, top, ic50, hill = (float(v) for v in popt)
    in_range = conc[pos].min() <= ic50 <= conc[pos].max()
    return {"ok": True, "bottom": bottom, "top": top, "ic50": ic50,
            "hill": hill, "r2": r2, "ci95": ci, "n_points": int(len(conc)),
            "in_range": bool(in_range),
            "conc_min": float(conc[pos].min()), "conc_max": float(conc[pos].max())}


def summarize_group(cells, states, image_area_px, field_count=1, known=None):
    """Сводные показатели по одной экспериментальной группе (лунке / дозе).

    cells  — список словарей морфометрии;
    states — список меток состояния той же длины.
    """
    n = len(cells)
    if n == 0:
        return {"cell_count": 0, "viability": float("nan"),
                "calibrated": False, "dry_mass": float("nan"),
                "mean_dry_mass": float("nan"), "confluence": 0.0,
                "mitotic_idx": float("nan"), "n_fields": field_count,
                "state_reliable": False, "unknown_fraction": float("nan"),
                "state_note": "клеток не найдено"}

    states = list(states)
    # Оценка надёжности определения состояний по всей группе.
    from .novelty import reliability, UNDETERMINED
    if known is None:
        known = [s != UNDETERMINED for s in states]
    rel = reliability(states, list(known))

    # Обломки исключаются из знаменателя: это не клетки.
    determined = [s for s in states
                  if s != UNDETERMINED and s not in NON_CELL_CLASSES]
    n_debris = sum(1 for s in states if s in NON_CELL_CLASSES)
    if rel["reliable"] and determined:
        viable = sum(1 for s in determined if s in VIABLE_CLASSES)
        mitotic = sum(1 for s in determined if s == "mitosis")
        n_state = len(determined)
    else:
        viable = mitotic = n_state = 0
    # Физические величины считаем только если они реально есть в данных.
    calibrated = bool(cells) and "dry_mass_pg" in cells[0]
    mass = float(np.sum([c["dry_mass_pg"] for c in cells])) if calibrated else float("nan")
    area_px = float(np.sum([c["area_px"] for c in cells]))

    nanv = float("nan")
    return {
        "cell_count": n / field_count,
        "state_reliable": rel["reliable"],
        "unknown_fraction": rel["unknown_fraction"],
        "state_note": rel["note"],
        "viability": (100.0 * viable / n_state) if n_state else nanv,
        "calibrated": calibrated,
        "dry_mass": (mass / field_count) if calibrated else nanv,
        "mean_dry_mass": (mass / n) if calibrated else nanv,
        "confluence": 100.0 * area_px / (image_area_px * field_count),
        "mitotic_idx": (100.0 * mitotic / n_state) if n_state else nanv,
        "debris_idx": 100.0 * n_debris / n,
        "n_fields": field_count,
    }


def normalize_to_control(values, control_value):
    """Приводит отклик к контролю: 100 % = необработанные клетки."""
    if control_value is None or not np.isfinite(control_value) or abs(control_value) < 1e-12:
        return np.full(len(values), np.nan)
    return 100.0 * np.asarray(values, dtype=float) / float(control_value)
