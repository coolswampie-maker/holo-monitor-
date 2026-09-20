"""Эксперимент: набор полей, сгруппированных по дозам, и его анализ.

Формат входных данных (он же формат выгрузки из штатного ПО микроскопа
после конвертации): каталог с файлом manifest.csv и изображениями.

manifest.csv, обязательные колонки:
    file          — путь к изображению относительно каталога;
    group         — имя группы (например, «контроль» или «ДМСО 10 мкМ»);
Необязательные:
    concentration — числовая концентрация (для кривой «доза — эффект»);
    replicate     — номер повтора;
    field         — номер поля внутри лунки;
    time_h        — время от начала эксперимента, ч.

Изображения — TIFF/PNG с картой сдвига фазы. Единицы задаются
параметром `phase_unit`: 'waves' (как в Hstudio) или 'rad'.
"""

import csv
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import numpy as np

from .calibration import Calibration
from .diagnostics import get_logger
from .diagnostics.errors import log_exception
from .optics import OpticalConfig
from .pipeline import analyze_field, load_model
from .tox import summarize_group, fit_dose_response, normalize_to_control, ENDPOINTS


def read_phase(path, phase_unit="waves"):
    """Читает карту сдвига фазы из файла."""
    path = Path(path)
    if path.suffix.lower() == ".fmx":
        # Родной формат карты фазы штатного ПО микроскопа. Значения уже
        # в долях длины волны, пересчёт не нужен.
        from .importers.hstudio import read_phase_matrix
        return read_phase_matrix(path).phase
    if path.suffix.lower() in (".tif", ".tiff"):
        import tifffile
        img = tifffile.imread(str(path))
    elif path.suffix.lower() == ".npy":
        img = np.load(path)
    else:
        from PIL import Image
        img = np.asarray(Image.open(path))

    img = np.asarray(img, dtype=np.float64)
    if img.ndim == 3:
        img = img.mean(axis=-1)

    if phase_unit == "rad":
        img = img / (2.0 * np.pi)
    elif phase_unit == "waves":
        pass
    else:
        raise ValueError("phase_unit должен быть 'waves' или 'rad'")

    # Целочисленные изображения обычно масштабированы — нормируем
    # в разумный диапазон сдвига фазы.
    if np.issubdtype(np.asarray(img).dtype, np.integer) or img.max() > 50:
        img = img / img.max() * 1.5
    return img


@dataclass
class Experiment:
    """Эксперимент целиком: поля, группы, сводки, кривая доза — эффект."""

    name: str
    root: Path
    records: list = dc_field(default_factory=list)   # строки манифеста
    fields: list = dc_field(default_factory=list)    # FieldResult
    cal: Calibration = dc_field(default_factory=Calibration)
    phase_unit: str = "waves"
    hstudio: object = None        # HstudioExperiment, если импортирован
    skipped: list = dc_field(default_factory=list)   # (файл, причина)

    @property
    def calibrated(self):
        return self.cal.complete

    @classmethod
    def from_hstudio(cls, path, cal: Calibration = None):
        """Открывает каталог эксперимента Hstudio напрямую, без манифеста."""
        from .importers.hstudio import load_experiment
        h = load_experiment(path)
        records = []
        by_file = {Path(f["file"]).name: f for f in h.frames_meta if f.get("file")}
        for i, pth in enumerate(h.phase_files):
            meta = by_file.get(pth.name, {})
            records.append({"file": str(pth.relative_to(h.root)),
                            "group": meta.get("group") or h.name,
                            "concentration": "", "replicate": 1,
                            "field": i + 1, "time_h": "",
                            "capture_time": meta.get("time") or ""})
        ex = cls(name=h.name, root=Path(h.root), records=records,
                 cal=cal or h.calibration)
        ex.hstudio = h
        return ex

    @classmethod
    def from_manifest(cls, root, cal: Calibration = None, phase_unit="waves"):
        root = Path(root)
        man = root / "manifest.csv"
        if not man.exists():
            raise FileNotFoundError(f"Не найден manifest.csv в {root}")
        with open(man, newline="", encoding="utf-8") as fh:
            records = list(csv.DictReader(fh))
        if not records:
            raise ValueError("manifest.csv пуст")
        return cls(name=root.name, root=root, records=records,
                   cal=cal or Calibration(), phase_unit=phase_unit)

    def run(self, method="ml", progress=None, min_area_px=None):
        """Анализирует все поля эксперимента."""
        seg = load_model("segmenter") if method == "ml" else None
        state = load_model("cellstate") if self.calibrated else None
        nov = load_model("novelty") if self.calibrated else None
        log = get_logger("experiment")
        # Зерно фиксировано: повторный анализ тех же данных обязан дать
        # тот же результат.
        import numpy as _np
        from .config import get as _cfg
        _np.random.seed(int(_cfg("analysis", "random_seed", 20260920)))

        log.info("Анализ «%s»: %d кадров, калибровка %s", self.name,
                 len(self.records), "есть" if self.calibrated else "нет")
        self.fields = []
        self.skipped = []
        for i, rec in enumerate(self.records):
            # Один повреждённый файл не должен обрушить весь эксперимент.
            try:
                phase = read_phase(self.root / rec["file"], self.phase_unit)
                fr = analyze_field(
                    phase, name=rec["file"], cal=self.cal, method=method,
                    min_area_px=min_area_px, seg_model=seg, state_model=state,
                    novelty_model=nov, time_h=float(rec.get("time_h") or 0.0),
                    frame=i, meta=dict(rec),
                )
            except Exception as e:
                msg, _ = log_exception(log, e, f"кадр {rec['file']}")
                self.skipped.append((rec["file"], msg))
                if progress:
                    progress(i + 1, len(self.records), rec["file"], None)
                continue
            self.fields.append(fr)
            if progress:
                progress(i + 1, len(self.records), rec["file"], fr)

        log.info("Обработано %d из %d кадров, объектов %d",
                 len(self.fields), len(self.records),
                 sum(f.n_cells for f in self.fields))
        if self.skipped:
            log.warning("Пропущено файлов: %d", len(self.skipped))
            for f, why in self.skipped:
                log.warning("  %s — %s", f, why)
        return self

    # --- сводки ----------------------------------------------------------
    def groups(self):
        """Упорядоченный список имён групп."""
        seen = []
        for r in self.records:
            if r["group"] not in seen:
                seen.append(r["group"])
        return seen

    def group_concentration(self, group):
        for r in self.records:
            if r["group"] == group and r.get("concentration") not in (None, ""):
                return float(r["concentration"])
        return None

    def group_summary(self):
        """Сводка по каждой группе."""
        out = {}
        for g in self.groups():
            fields = [f for f in self.fields if f.meta.get("group") == g]
            if not fields:
                continue
            cells = [c for f in fields for c in f.cells]
            states = [st for f in fields for st in f.states]
            known = [bool(c.get("in_training_domain", True)) for c in cells]
            s = summarize_group(cells, states, fields[0].image_area_px,
                                len(fields), known=known)
            s["group"] = g
            s["concentration"] = self.group_concentration(g)
            s["n_cells_total"] = len(cells)
            out[g] = s
        return out

    def dose_response(self, endpoint="viability", control_group=None, normalize=True):
        """Строит кривую «доза — эффект» и считает IC50.

        control_group — имя контрольной группы; если не задано, берётся
        группа с концентрацией 0 (или с минимальной концентрацией).
        """
        if endpoint not in ENDPOINTS:
            raise ValueError(f"неизвестный показатель: {endpoint}")
        summ = self.group_summary()
        rows = [s for s in summ.values() if s.get("concentration") is not None]
        if len(rows) < 5:
            return {"ok": False, "reason": "нужно не менее 5 групп с заданной концентрацией"}
        rows.sort(key=lambda s: s["concentration"])

        conc = np.array([s["concentration"] for s in rows], dtype=float)
        raw = np.array([s[endpoint] for s in rows], dtype=float)

        if control_group is not None:
            ctrl = summ[control_group][endpoint]
        else:
            zero = [s for s in rows if s["concentration"] == 0]
            ctrl = (zero[0] if zero else rows[0])[endpoint]

        resp = normalize_to_control(raw, ctrl) if normalize else raw
        fit = fit_dose_response(conc, resp)
        fit.update({"endpoint": endpoint, "endpoint_ru": ENDPOINTS[endpoint],
                    "conc": conc.tolist(), "response": resp.tolist(),
                    "raw": raw.tolist(), "control": float(ctrl),
                    "normalized": bool(normalize),
                    "groups": [s["group"] for s in rows]})
        return fit

    def cells_table(self):
        """Все клетки эксперимента одной таблицей."""
        rows = []
        for f in self.fields:
            for c in f.cells:
                r = dict(c)
                r["field"] = f.name
                r["group"] = f.meta.get("group", "")
                r["concentration"] = f.meta.get("concentration", "")
                r["replicate"] = f.meta.get("replicate", "")
                rows.append(r)
        return rows
