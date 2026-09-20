"""Самопроверка рабочего места.

Запускается на машине заказчика после копирования и отвечает на вопрос
«работает ли здесь всё», не требуя ни данных, ни микроскопа. Каждая
проверка печатает результат сразу: если что-то отказало, видно, что
именно, а не общий сбой в конце.
"""

import platform
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("Интерпретатор Python")
def _python():
    v = sys.version_info
    if v < (3, 9):
        raise RuntimeError(f"нужен Python 3.9 или новее, найден {v.major}.{v.minor}")
    return f"{v.major}.{v.minor}.{v.micro}, {platform.machine()}, {platform.system()}"


@check("Числовые библиотеки")
def _numeric():
    import numpy, scipy, skimage, sklearn, matplotlib
    return (f"numpy {numpy.__version__}, scipy {scipy.__version__}, "
            f"scikit-image {skimage.__version__}, scikit-learn {sklearn.__version__}, "
            f"matplotlib {matplotlib.__version__}")


@check("Чтение изображений")
def _imaging():
    import tifffile, PIL
    import numpy as np
    import tempfile, os
    a = (np.random.rand(24, 24) * 0.3).astype("float32")
    fd, p = tempfile.mkstemp(suffix=".tif"); os.close(fd)
    try:
        tifffile.imwrite(p, a)
        b = tifffile.imread(p)
        if b.shape != a.shape:
            raise RuntimeError("прочитанное изображение не совпало по размеру")
    finally:
        os.unlink(p)
    return f"tifffile {tifffile.__version__}, Pillow {PIL.__version__} — запись и чтение TIFF"


@check("Кодировка вывода")
def _encoding():
    from ._compat import can_print_unicode
    enc = getattr(sys.stdout, "encoding", "неизвестна")
    ok = can_print_unicode()
    return (f"{enc}, псевдографика {'поддерживается' if ok else 'заменяется на ASCII'}")


@check("Совпадение версий с моделями")
def _versions():
    import json
    from .pipeline import check_model_environment, MODELS_DIR
    check_model_environment()
    stamp = MODELS_DIR / "versions.json"
    if not stamp.exists():
        return "отпечаток среды не записан — проверка пропущена"
    d = json.loads(stamp.read_text(encoding="utf-8"))
    return "обучены на " + ", ".join(f"{k} {v}" for k, v in d.items())


@check("Обученные модели")
def _models():
    from .pipeline import load_model
    sizes = []
    for n in ("segmenter", "cellstate", "novelty"):
        load_model(n)
        sizes.append(f"{n} {(ROOT / 'models' / (n + '.joblib')).stat().st_size / 1e6:.1f} МБ")
    return ", ".join(sizes)


@check("Анализ изображения")
def _analysis():
    from .synth import synth_field
    from .pipeline import analyze_field
    f = synth_field(n_cells=40, shape=(384, 512), seed=12345)
    t = time.time()
    fr = analyze_field(f["phase"], name="самопроверка", cfg=f["cfg"])
    dt = time.time() - t
    if fr.n_cells < 10:
        raise RuntimeError(f"найдено всего {fr.n_cells} клеток из ~40 — модель работает неверно")
    if not (0 <= fr.viability_pct <= 100):
        raise RuntimeError("некорректная доля жизнеспособных клеток")
    return (f"найдено {fr.n_cells} клеток за {dt:.1f} с, "
            f"сухая масса {fr.total_dry_mass_pg:.0f} пг")


@check("Импорт данных Hstudio")
def _hstudio():
    """Проверяет чтение реального эксперимента и отсечение по калибровке."""
    from .importers.hstudio import detect, load_experiment, read_phase_matrix
    from .features import measure_cells
    from .calibration import Calibration, from_user
    import numpy as np
    demo = ROOT / "demo_data" / "M4_demo_8"
    if not demo.exists():
        return "демонстрационный эксперимент не установлен, проверка пропущена"
    if detect(demo) is None:
        raise RuntimeError(f"каталог не распознан как эксперимент Hstudio: {demo}")
    ex = load_experiment(demo)
    pmx = read_phase_matrix(ex.phase_files[0])
    if pmx.width < 64 or pmx.height < 64:
        raise RuntimeError(f"подозрительный размер кадра: {pmx.width}x{pmx.height}")

    # Ключевое свойство: без калибровки физических величин быть не должно.
    lab = np.zeros(pmx.phase.shape, dtype=np.int32)
    lab[10:60, 10:60] = 1
    no_cal = measure_cells(lab, pmx.phase, cal=Calibration())[0]
    with_cal = measure_cells(lab, pmx.phase,
                             cal=from_user(0.336, 0.633, 1.38, 1.34))[0]
    if "dry_mass_pg" in no_cal or "area_um2" in no_cal:
        raise RuntimeError("без калибровки вычислены физические величины — "
                           "это недопустимо")
    if "dry_mass_pg" not in with_cal:
        raise RuntimeError("с калибровкой физические величины не вычислены")
    return (f"{ex.name}: {ex.n_frames} кадров {pmx.width}x{pmx.height}, "
            f"формат {pmx.version}; отсечение по калибровке работает")


@check("Отказ от угадывания")
def _abstention():
    """Проверяет, что на незнакомых данных программа не выдумывает состав.

    Подаём заведомо чужие признаки и убеждаемся, что детектор их
    отвергает, а на обучающем распределении — пропускает.
    """
    import numpy as np
    from .pipeline import load_model
    from .features import CLASSIFIER_FEATURES
    from .synth import synth_field
    from .segment import flatten_background
    from .features import measure_cells

    det = load_model("novelty")
    f = synth_field(n_cells=60, shape=(384, 512), seed=4242)
    rows = measure_cells(f["labels"], flatten_background(f["phase"]), cfg=f["cfg"])
    X = np.nan_to_num(np.array([[r[k] for k in CLASSIFIER_FEATURES] for r in rows]))
    known_own = det.is_known(X).mean()
    # Явно чужие признаки: значения, умноженные на десять.
    known_alien = det.is_known(X * 10.0 + 5.0).mean()
    if known_own < 0.80:
        raise RuntimeError(f"детектор отвергает своё же обучающее "
                           f"распределение ({100 * known_own:.0f} % принято)")
    if known_alien > 0.20:
        raise RuntimeError(f"детектор принимает заведомо чужие данные "
                           f"({100 * known_alien:.0f} % принято)")
    return (f"на своём распределении принято {100 * known_own:.0f} %, "
            f"на чужом {100 * known_alien:.0f} %")


@check("Расчёт IC50")
def _tox():
    import numpy as np
    from .tox import hill4, fit_dose_response
    conc = np.array([0, 1, 3, 6, 12, 25, 50, 100, 200], dtype=float)
    r = fit_dose_response(conc, hill4(conc, 3.0, 100.0, 18.0, 1.5), n_boot=60)
    if not r["ok"]:
        raise RuntimeError(r["reason"])
    if abs(r["ic50"] - 18.0) > 1.0:
        raise RuntimeError(f"IC50 восстановлен неточно: {r['ic50']:.2f} вместо 18,0")
    return f"IC50 = {r['ic50']:.2f} при заданных 18,0; R² = {r['r2']:.4f}"


@check("Формирование PDF")
def _pdf():
    import tempfile, os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    fd, p = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
    try:
        with PdfPages(p) as pdf:
            fig = plt.figure(figsize=(4, 3))
            fig.text(0.1, 0.5, "Проверка кириллицы: ЖЩЭЮЯ жщэюя — «ёмкость» 12 мкМ")
            pdf.savefig(fig); plt.close(fig)
        size = os.path.getsize(p)
        if size < 1000:
            raise RuntimeError("PDF получился пустым")
    finally:
        os.unlink(p)
    return f"{size / 1024:.0f} КБ, кириллица отрисована"


@check("Веб-интерфейс")
def _web():
    import socket
    from http.server import ThreadingHTTPServer
    from .webui import Handler, WEB
    if not (WEB / "index.html").exists():
        raise RuntimeError(f"не найден файл интерфейса: {WEB / 'index.html'}")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.server_close()
    return f"страница на месте, сокет открывается (проверен порт {port})"


@check("Права на запись")
def _writable():
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    p = out / ".проверка_записи"
    p.write_text("ок", encoding="utf-8")
    p.unlink()
    return f"каталог результатов доступен: {out}"


def run(verbose=True):
    """Выполняет все проверки. Возвращает число отказов."""
    from . import __product__, __version__
    print(f"\n  {__product__} {__version__} — самопроверка рабочего места")
    print(f"  {ROOT}\n")
    width = max(len(n) for n, _ in CHECKS) + 2
    failed = []
    for name, fn in CHECKS:
        print(f"  {name:.<{width}}", end=" ", flush=True)
        try:
            detail = fn()
            print("ОК")
            if verbose and detail:
                print(f"      {detail}")
        except Exception as e:
            print("ОТКАЗ")
            print(f"      {type(e).__name__}: {e}")
            if verbose:
                for line in traceback.format_exc().splitlines()[-4:-1]:
                    print(f"      {line}")
            failed.append(name)
    print()
    if failed:
        print(f"  Отказов: {len(failed)} — {', '.join(failed)}")
        print("  Программа к работе не готова. Сообщение выше указывает причину.\n")
    else:
        print("  Все проверки пройдены. Программа готова к работе.\n")
    return len(failed)
