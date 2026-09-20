"""Выгрузка результатов: таблица объектов и метаданные анализа.

Таблица предназначена для передачи пользователю, поэтому колонки
названы по-русски и с единицами. Технические идентификаторы кадра и
объекта сохраняются — по ним результат воспроизводится.

Рядом кладётся analysis_metadata.json: версия программы, путь к данным,
калибровка с происхождением каждой величины, настройки анализа,
пропущенные файлы. Без него таблица через полгода нечитаема.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

from . import parameters as pm
from .config import get
from .version import PRODUCT, VERSION, BUILD_DATE

# Технические колонки: остаются как есть, они нужны для воспроизводимости.
TECHNICAL = {
    "file": "Файл кадра",
    "frame": "Номер кадра (порядок файлов)",
    "label": "Номер объекта в кадре",
    "group": "Группа",
    "cell_state_ru": "Состояние объекта (ГОЛОЦИТ)",
    "in_training_domain": "В области обученного (ГОЛОЦИТ)",
}

# Служебные колонки, которые пользователю не нужны.
DROP = {"time_h", "concentration", "replicate", "field", "capture_time",
        "cell_state"}


def column_title(key):
    """Человекочитаемое имя колонки."""
    if key in TECHNICAL:
        return TECHNICAL[key]
    p = pm.of(key)
    if p is None:
        return key
    cat = {"A": "A", "B": "B", "C": "C"}[p.category]
    return f"{p.display} [{cat}]"


def write_cells_csv(rows, path, delimiter=None, encoding=None):
    """Пишет таблицу объектов. Возвращает (путь, строк, колонок)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("нет объектов для выгрузки")

    keys = [k for k in rows[0].keys() if k not in DROP]
    # Порядок: сначала технические, потом A, потом B, потом C.
    def rank(k):
        if k in TECHNICAL:
            return (0, list(TECHNICAL).index(k))
        p = pm.of(k)
        return ({"A": 1, "B": 2, "C": 3}.get(p.category, 4) if p else 4, k)
    keys.sort(key=rank)

    delimiter = delimiter or get("export", "csv_delimiter", ";")
    encoding = encoding or get("export", "csv_encoding", "utf-8-sig")
    with open(path, "w", newline="", encoding=encoding) as fh:
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow([column_title(k) for k in keys])
        for r in rows:
            w.writerow([r.get(k, "") for k in keys])
    return path, len(rows), len(keys)


def analysis_metadata(ex, csv_path=None, pdf_path=None):
    """Метаданные анализа — то, без чего таблица через полгода мертва."""
    cells = [c for f in ex.fields for c in f.cells]
    cal = ex.cal
    h = getattr(ex, "hstudio", None)
    return {
        "software": {"product": PRODUCT, "version": VERSION,
                     "build_date": BUILD_DATE},
        "analysis": {
            "datetime": datetime.now().isoformat(timespec="seconds"),
            "experiment": ex.name,
            "source_directory": str(ex.root),
            "frames_total": len(ex.records),
            "frames_processed": len(ex.fields),
            "frames_skipped": [{"file": f, "reason": why}
                               for f, why in getattr(ex, "skipped", [])],
            "objects_found": len(cells),
            "random_seed": get("analysis", "random_seed", 20260920),
        },
        "settings": {
            "segmentation": dict(get("segmentation", "min_area_px") and
                                 {"min_area_px": get("segmentation", "min_area_px"),
                                  "typical_area_px": get("segmentation", "typical_area_px"),
                                  "probability_threshold": get("segmentation", "probability_threshold")}),
            "background": {"mode": get("background", "mode"),
                           "fixed_threshold": get("background", "fixed_threshold")},
        },
        "calibration": {
            "complete": cal.complete, "status": cal.status_line(),
            "values": [{"key": r["key"], "name": r["name"], "value": r["value"],
                        "status": r["status"], "source": r["source"]}
                       for r in cal.rows()],
        },
        "instrument_metadata": (
            {k: str(v.value) for k, v in h.provenance.values.items()
             if v.source == "measured"} if h is not None else {}),
        "parameter_categories": {
            "A": {"meaning": pm.CATEGORY_RU[pm.DIRECT],
                  "parameters": [p.key for p in pm.by_category(pm.DIRECT)]},
            "B": {"meaning": pm.CATEGORY_RU[pm.CALIBRATED],
                  "available": cal.complete,
                  "parameters": [p.key for p in pm.by_category(pm.CALIBRATED)]},
            "C": {"meaning": pm.CATEGORY_RU[pm.DERIVED],
                  "parameters": [p.key for p in pm.by_category(pm.DERIVED)]},
        },
        "outputs": {"cells_csv": str(csv_path) if csv_path else None,
                    "report_pdf": str(pdf_path) if pdf_path else None},
    }


def write_metadata(ex, path, csv_path=None, pdf_path=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis_metadata(ex, csv_path, pdf_path),
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def export_all(ex, out_dir, base_name=None):
    """Пишет таблицу, метаданные и возвращает пути."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    name = base_name or ex.name
    rows = ex.cells_table()
    csv_path, n_rows, n_cols = write_cells_csv(rows, out_dir / f"{name}_объекты.csv")
    meta_path = None
    if get("export", "write_metadata", True):
        meta_path = write_metadata(ex, out_dir / f"{name}_метаданные.json",
                                   csv_path=csv_path)
    return {"csv": csv_path, "rows": n_rows, "cols": n_cols, "metadata": meta_path}
