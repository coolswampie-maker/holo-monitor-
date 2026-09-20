"""Сквозной конвейер анализа: изображение -> клетки -> состояния -> сводка."""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import joblib

from ._compat import worker_count
from .optics import OpticalConfig
from .segment import segment_ml, segment_threshold, flatten_background
from .features import measure_cells, CLASSIFIER_FEATURES
from .novelty import reliability, UNDETERMINED
from .synth import CLASS_RU, VIABLE_CLASSES, NON_CELL_CLASSES

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

_CACHE = {}
_VERSION_CHECKED = False

# Версии, расхождение по которым делает файлы моделей нечитаемыми.
_CRITICAL = ("sklearn", "numpy")


def check_model_environment():
    """Сверяет текущие версии библиотек с теми, которыми обучены модели.

    Файлы joblib несовместимы между версиями scikit-learn и numpy.
    Без этой проверки несовпадение проявляется невнятной ошибкой о
    структуре массива узлов дерева уже в середине анализа.
    """
    global _VERSION_CHECKED
    if _VERSION_CHECKED:
        return
    _VERSION_CHECKED = True
    stamp_path = MODELS_DIR / "versions.json"
    if not stamp_path.exists():
        return
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except Exception:
        return

    import sklearn
    current = {"sklearn": sklearn.__version__, "numpy": np.__version__}
    bad = [(k, stamp[k], current[k]) for k in _CRITICAL
           if k in stamp and stamp[k] != current[k]]
    if bad:
        rows = "\n".join(f"    {k}: модели обучены на {was}, установлена {now}"
                          for k, was, now in bad)
        raise RuntimeError(
            "Версии библиотек не совпадают с теми, которыми обучены модели.\n"
            f"{rows}\n"
            "  Файлы моделей несовместимы между версиями. Решения:\n"
            "    - установить версии из requirements.txt, либо\n"
            "    - переобучить: python -m scripts.train_models")


def load_model(name):
    """Загружает модель из models/ с кэшированием."""
    check_model_environment()
    if name not in _CACHE:
        path = MODELS_DIR / f"{name}.joblib"
        if not path.exists():
            raise FileNotFoundError(
                f"Модель не найдена: {path}\n"
                f"Обучите её командой: python3 scripts/train_models.py")
        model = joblib.load(path)
        # Предсказание в sklearn идёт в потоках (require="sharedmem"), новых
        # процессов не порождается. Но число потоков ограничиваем, иначе на
        # многоядерной машине пулы sklearn и BLAS начинают мешать друг другу.
        if hasattr(model, "n_jobs"):
            model.n_jobs = worker_count()
        _CACHE[name] = model
    return _CACHE[name]


@dataclass
class FieldResult:
    """Результат анализа одного поля зрения."""

    name: str
    phase: np.ndarray            # фазовое изображение с вычтенным фоном
    labels: np.ndarray           # карта меток клеток
    cells: list                  # морфометрия по клеткам
    states: list                 # состояние каждой клетки
    cfg: OpticalConfig = None     # None означает, что калибровки нет
    known: np.ndarray = None      # попала ли клетка в область обученного
    method: str = "ml"
    baseline_labels: np.ndarray = None   # результат порогового метода, для сравнения
    meta: dict = field(default_factory=dict)

    @property
    def n_cells(self):
        return len(self.cells)

    @property
    def calibrated(self):
        """Известна ли калибровка прибора для этого кадра."""
        return self.cfg is not None

    @property
    def image_area_px(self):
        return float(self.labels.size)

    @property
    def image_area_um2(self):
        if not self.calibrated:
            return float("nan")
        return float(self.labels.size) * self.cfg.pixel_area_um2

    @property
    def total_area_px(self):
        return float(np.sum([c["area_px"] for c in self.cells])) if self.cells else 0.0

    @property
    def confluence_pct(self):
        return 100.0 * float((self.labels > 0).sum()) / float(self.labels.size)

    @property
    def reliability(self):
        """Можно ли доверять определению состояний на этом кадре."""
        if not self.calibrated:
            return {"n": len(self.states), "n_known": 0,
                    "unknown_fraction": 1.0, "reliable": False,
                    "note": "состояние клеток не определялось: нет калибровки "
                            "прибора, а классификатор обучен на признаках "
                            "в физических единицах"}
        k = self.known if self.known is not None else np.ones(len(self.states), dtype=bool)
        return reliability(self.states, k)

    @property
    def viability_pct(self):
        """Доля жизнеспособных среди клеток с определённым состоянием.

        Если состояние не определено у слишком многих, величина не имеет
        смысла и возвращается как NaN.
        """
        if not self.states or not self.reliability["reliable"]:
            return float("nan")
        # Обломки — не клетки, в знаменатель не входят.
        determined = [s for s in self.states
                      if s != UNDETERMINED and s not in NON_CELL_CLASSES]
        if not determined:
            return float("nan")
        return 100.0 * sum(1 for s in determined if s in VIABLE_CLASSES) / len(determined)

    @property
    def total_dry_mass_pg(self):
        if not self.calibrated or not self.cells:
            return float("nan")
        return float(np.sum([c["dry_mass_pg"] for c in self.cells]))

    def state_counts(self):
        out = {}
        for s in self.states:
            out[s] = out.get(s, 0) + 1
        return out

    def summary(self):
        counts = self.state_counts()
        return {
            "поле": self.name,
            "клеток": self.n_cells,
            "жизнеспособность_%": round(self.viability_pct, 1),
            "конфлюентность_%": round(self.confluence_pct, 1),
            "сухая_масса_пг": round(self.total_dry_mass_pg, 1),
            "средняя_масса_пг": round(self.total_dry_mass_pg / self.n_cells, 1) if self.n_cells else float("nan"),
            **{CLASS_RU[k]: v for k, v in sorted(counts.items())},
        }


def classify_states(cells, model=None, novelty=None, use_novelty=True):
    """Присваивает каждой клетке состояние.

    Клеткам, не похожим на обучающие данные, вместо класса ставится
    «не определено»: угадывать на незнакомом материале хуже, чем честно
    отказаться. Возвращает (состояния, признак «в пределах обученного»).
    """
    if not cells:
        return [], np.zeros(0, dtype=bool)
    model = model if model is not None else load_model("cellstate")
    X = np.array([[c.get(k, 0.0) for k in CLASSIFIER_FEATURES] for c in cells],
                 dtype=np.float64)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    states = list(model.predict(X))

    known = np.ones(len(cells), dtype=bool)
    if use_novelty:
        try:
            det = novelty if novelty is not None else load_model("novelty")
        except FileNotFoundError:
            det = None
        if det is not None:
            known = np.asarray(det.is_known(X), dtype=bool)
            states = [st if k else UNDETERMINED for st, k in zip(states, known)]
    return states, known


def analyze_field(phase, name="field", cal=None, cfg: OpticalConfig = None,
                  method="ml", min_area_px=None, drop_edge_cells=True,
                  with_baseline=False, seg_model=None, state_model=None,
                  novelty_model=None, time_h=0.0, frame=0, meta=None):
    """Полный анализ одного кадра.

    cal    : Calibration. Без полной калибровки физические величины и
             классификация состояния не вычисляются — см. features.
    method : 'ml' — обученный сегментатор; иначе пороговый метод,
             оставленный для сравнения со штатным ПО.

    Сегментация ведётся в пикселях и от калибровки не зависит.
    """
    from .segment import DEFAULT_MIN_AREA_PX
    if min_area_px is None:
        min_area_px = DEFAULT_MIN_AREA_PX

    # Калибровка либо полная, либо её нет. Полумер не бывает.
    if cfg is None and cal is not None and getattr(cal, "complete", False):
        cfg = cal.to_optics()
    calibrated = cfg is not None

    if method == "ml":
        model = seg_model if seg_model is not None else load_model("segmenter")
        labels, flat = segment_ml(phase, model, min_area_px=min_area_px,
                                  drop_edge_cells=drop_edge_cells)
    else:
        labels, flat = segment_threshold(phase, method=method,
                                         min_area_px=min_area_px,
                                         drop_edge_cells=drop_edge_cells)

    base = None
    if with_baseline and method == "ml":
        base, _ = segment_threshold(phase, method="otsu",
                                    min_area_px=min_area_px,
                                    drop_edge_cells=drop_edge_cells)

    cells = measure_cells(labels, flat, cal=cal, cfg=cfg,
                          frame=frame, time_h=time_h)

    # Классификатор состояния обучен на признаках в физических единицах,
    # поэтому без калибровки он не запускается вовсе.
    if calibrated:
        states, known = classify_states(cells, model=state_model,
                                        novelty=novelty_model)
    else:
        states = [UNDETERMINED] * len(cells)
        known = np.zeros(len(cells), dtype=bool)

    for c, st, k in zip(cells, states, known):
        c["cell_state"] = st
        c["cell_state_ru"] = CLASS_RU.get(st, st)
        c["in_training_domain"] = bool(k)

    return FieldResult(name=name, phase=flat, labels=labels, cells=cells,
                       states=states, cfg=cfg, known=known, method=method,
                       baseline_labels=base, meta=meta or {})
