"""Локальный веб-интерфейс ГОЛОЦИТа.

Один сценарий: выбрать эксперимент Hstudio, посмотреть, что в нём
нашлось, запустить анализ, получить отчёт. Всё остальное убрано.

Работает на стандартной библиотеке Python: ни веб-сервера, ни
дополнительных пакетов не требуется. Наружу ничего не передаётся.
"""

import csv as csvmod
import io
import json
import math
import mimetypes
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import numpy as np

from . import __product__, __version__
from . import parameters as pm
from .calibration import Calibration, from_user
from .experiment import Experiment
from .features import DIRECT_COLUMNS, CALIBRATED_COLUMNS, DERIVED_COLUMNS
from .importers.hstudio import (detect, load_experiment, read_phase_matrix,
                                UnsupportedFormat)
from .report import build_report, overlay_axes
from .synth import CLASS_RU, CLASS_COLOR, DISPLAY_CLASSES

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
DEMO = ROOT / "demo_data" / "M4_demo_8"

# Читаемые ресурсы (интерфейс, демо) лежат внутри сборки, рядом с модулем,
# поэтому для них годится ROOT. Результаты работы — нет: в упакованном виде
# ROOT указывает на служебный каталог _internal, и выгрузка уходила бы туда,
# а пользователь смотрел бы в пустую папку out рядом с программой.
from .diagnostics.logs import app_root as _app_root   # noqa: E402

OUT = _app_root() / "out"

STATE = {"running": False, "done": False, "error": None, "progress": 0,
         "total": 0, "message": "Готов к работе", "experiment": None,
         "report": None, "csv": None}
LOCK = threading.Lock()


def _num(v):
    """None вместо NaN — чтобы в интерфейсе стоял прочерк, а не 'nan'."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if not math.isfinite(float(v)) else round(float(v), 4)
    if isinstance(v, (int, np.integer)):
        return int(v)
    return v


# --- Шаг 2: что нашлось в каталоге ----------------------------------------
def inspect(path):
    path = Path(path)
    kind = detect(path)
    if kind is None:
        return {"ok": False,
                "error": f"{path} не распознан как эксперимент Hstudio. "
                         f"Ожидается каталог с imagedb.xml и Storage/, "
                         f"либо с DBTransferInfo.xml, либо с файлами "
                         f"*.fmx / *.bin."}
    # Неподдержанный формат и нечитаемый каталог — это сообщение
    # пользователю, а не сбой программы. Без этого запрос возвращал
    # HTTP 500 и в интерфейсе не оставалось никакого пояснения.
    try:
        h = load_experiment(path)
    except (UnsupportedFormat, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    pmx = read_phase_matrix(h.phase_files[0])
    cal = h.calibration
    return {
        "ok": True, "path": str(path), "layout": kind,
        "name": h.name, "n_frames": h.n_frames,
        "width": pmx.width, "height": pmx.height,
        "format": pmx.version,
        "phase_range": [round(float(pmx.phase.min()), 4),
                        round(float(pmx.phase.max()), 4)],
        "database": str(h.database) if h.database else None,
        "sources": h.sources_found,
        "calibration": {"complete": cal.complete, "status": cal.status_line(),
                        "rows": [{**r, "value": _num(r["value"])}
                                 for r in cal.rows()]},
        "metadata": {k: str(v.value) for k, v in h.provenance.values.items()
                     if v.source == "measured"},
        "warnings": h.warnings(),
    }


# --- Шаг 3: анализ ---------------------------------------------------------
def _run(path, cal, min_area_px, method):
    try:
        with LOCK:
            STATE.update(running=True, done=False, error=None, progress=0,
                         message="Чтение эксперимента…", experiment=None,
                         report=None, csv=None)
        ex = Experiment.from_hstudio(path, cal=cal)
        with LOCK:
            STATE["total"] = len(ex.records)

        def prog(i, n, name, fr):
            # fr равен None, когда кадр не прочитался: Experiment.run()
            # такие пропускает и сообщает о них отдельно. Обращаться к
            # fr.n_cells без проверки нельзя — иначе один повреждённый
            # файл ронял весь анализ, хотя остальные кадры уже посчитаны.
            tail = (f"объектов {fr.n_cells}" if fr is not None
                    else "пропущен, файл не прочитан")
            with LOCK:
                STATE.update(progress=i, total=n,
                             message=f"Кадр {i} из {n}: {Path(name).name} — {tail}")

        ex.run(method=method, progress=prog, min_area_px=min_area_px)

        with LOCK:
            STATE["message"] = "Формирование отчёта…"
        OUT.mkdir(exist_ok=True)
        pdf = build_report(ex, OUT / f"{ex.name}_отчёт.pdf")
        from .export import export_all
        res = export_all(ex, OUT)
        msg = (f"Готово: {len(ex.fields)} кадров, "
               f"{sum(f.n_cells for f in ex.fields)} объектов")
        if ex.skipped:
            msg += f". Пропущено файлов: {len(ex.skipped)}"
        with LOCK:
            STATE.update(running=False, done=True, experiment=ex,
                         report=str(pdf), csv=str(res["csv"]), message=msg)
    except Exception as e:
        with LOCK:
            STATE.update(running=False, done=False,
                         error=f"{type(e).__name__}: {e}",
                         message="Ошибка анализа")
        traceback.print_exc()


# --- Шаг 4: результаты -----------------------------------------------------
def results():
    ex = STATE["experiment"]
    if ex is None:
        return {"ok": False}
    cal = ex.cal
    fields = ex.fields
    cells = [c for f in fields for c in f.cells]
    calibrated = cal.complete

    def series(fn):
        return [_num(fn(f)) for f in fields]

    areas = [c["area_um2"] if calibrated else c["area_px"] for c in cells]
    hist, edges = np.histogram(areas, bins=30)

    summary = [
        {"label": "Кадров", "value": len(fields), "cat": pm.DIRECT},
        {"label": "Объектов найдено", "value": len(cells), "cat": pm.DIRECT},
        {"label": "Объектов на кадр, медиана",
         "value": _num(float(np.median([f.n_cells for f in fields]))), "cat": pm.DIRECT},
        {"label": "Занято площади кадра, %",
         "value": _num(float(np.mean([f.confluence_pct for f in fields]))), "cat": pm.DIRECT},
        {"label": "Площадь объекта, медиана, пикселей",
         "value": _num(float(np.median([c["area_px"] for c in cells]))), "cat": pm.DIRECT},
        {"label": "Сумма сдвига фазы, медиана, длин волн",
         "value": _num(float(np.median([c["phase_sum_waves"] for c in cells]))), "cat": pm.DIRECT},
    ]
    if calibrated:
        summary += [
            {"label": "Площадь объекта, медиана, мкм²",
             "value": _num(float(np.median([c["area_um2"] for c in cells]))), "cat": pm.CALIBRATED},
            {"label": "Оптическая толщина средняя, мкм",
             "value": _num(float(np.median([c["thickness_avg_um"] for c in cells]))), "cat": pm.CALIBRATED},
            {"label": "Оптический объём, медиана, мкм³",
             "value": _num(float(np.median([c["optical_volume_um3"] for c in cells]))), "cat": pm.CALIBRATED},
            {"label": "Сухая масса, медиана, пг",
             "value": _num(float(np.median([c["dry_mass_pg"] for c in cells]))), "cat": pm.CALIBRATED},
        ]

    comp = None
    rel = None
    if calibrated:
        tot = len(cells) or 1
        counts = {}
        for f in fields:
            for k, v in f.state_counts().items():
                counts[k] = counts.get(k, 0) + v
        comp = [{"name": CLASS_RU[c], "color": CLASS_COLOR[c],
                 "pct": round(100.0 * counts.get(c, 0) / tot, 1)}
                for c in DISPLAY_CLASSES]
        gs = list(ex.group_summary().values())
        rel = {"reliable": all(g.get("state_reliable", False) for g in gs),
               "note": gs[0].get("state_note", "") if gs else ""}

    return {
        "ok": True, "name": ex.name, "calibrated": calibrated,
        "calibration_status": cal.status_line(),
        "calibration_rows": [{**r, "value": _num(r["value"])} for r in cal.rows()],
        "summary": summary,
        "series": {
            "labels": [Path(f.name).name for f in fields],
            "count": series(lambda f: f.n_cells),
            "confluence": series(lambda f: f.confluence_pct),
            "area": series(lambda f: float(np.median(
                [c["area_um2"] if calibrated else c["area_px"] for c in f.cells]))
                if f.cells else None),
            "volume": series(lambda f: float(np.median(
                [c["optical_volume_um3"] for c in f.cells])) if calibrated and f.cells else None),
            "area_unit": "мкм²" if calibrated else "пикселей",
        },
        "hist": {"counts": hist.tolist(),
                 "edges": [round(float(e), 1) for e in edges],
                 "unit": "мкм²" if calibrated else "пикселей"},
        "composition": comp, "reliability": rel,
        "fields": [{"i": i, "name": Path(f.name).name, "cells": f.n_cells}
                   for i, f in enumerate(fields)],
        "columns": {"A": [pm.display_name(k) for k in DIRECT_COLUMNS],
                    "B": [pm.display_name(k) for k in CALIBRATED_COLUMNS] if calibrated else [],
                    "C": [pm.display_name(k) for k in DERIVED_COLUMNS]},
        "report": STATE["report"] is not None, "csv": STATE["csv"] is not None,
    }


def field_png(index, width=900, overlay=True):
    """Кадр для галереи: с разметкой или без неё.

    Без разметки показывается та же карта фазы, только без контуров —
    так видно, что именно программа выделила. Ничего не пересчитывается:
    отрисовка берёт уже готовый результат анализа. Подпись кадра рисует
    интерфейс, поэтому в самой картинке её нет.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fr = STATE["experiment"].fields[index]
    h, w = fr.labels.shape
    fig, ax = plt.subplots(figsize=(width / 100, width / 100 * h / w))
    overlay_axes(ax, fr.phase,
                 fr.labels if overlay else None,
                 fr.states if (overlay and fr.calibrated) else None,
                 title="")
    fig.tight_layout(pad=0.4)
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=100); plt.close(fig)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = f"HoloCyt/{__version__}"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (WEB / "index.html").read_text(encoding="utf-8"),
                                  "text/html; charset=utf-8")
            if u.path == "/api/config":
                return self._send(200, {
                    "product": __product__, "version": __version__,
                    "demo_path": str(DEMO),
                    "demo_exists": DEMO.exists(),
                })
            if u.path == "/api/inspect":
                return self._send(200, inspect(q.get("path", [""])[0]))
            if u.path == "/api/status":
                with LOCK:
                    return self._send(200, {k: STATE[k] for k in
                                            ("running", "done", "error",
                                             "progress", "total", "message")})
            if u.path == "/api/results":
                return self._send(200, results())
            if u.path == "/api/field.png":
                return self._send(200, field_png(
                    int(q.get("i", ["0"])[0]),
                    overlay=q.get("overlay", ["1"])[0] != "0"), "image/png")
            if u.path in ("/api/report.pdf", "/api/cells.csv"):
                key = "report" if u.path.endswith(".pdf") else "csv"
                path = STATE.get(key)
                if not path or not Path(path).exists():
                    return self._send(404, {"error": "файл не готов"})
                data = Path(path).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type",
                                 mimetypes.guess_type(path)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                fn = urllib.parse.quote(Path(path).name)
                self.send_header("Content-Disposition",
                                 f"attachment; filename*=UTF-8''{fn}")
                self.end_headers(); self.wfile.write(data)
                return
            return self._send(404, {"error": "не найдено"})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        if u.path != "/api/run":
            return self._send(404, {"error": "не найдено"})
        with LOCK:
            if STATE["running"]:
                return self._send(409, {"error": "анализ уже выполняется"})

        path = Path(payload.get("path") or "")
        if detect(path) is None:
            return self._send(400, {"error": f"не эксперимент Hstudio: {path}"})

        # Калибровка берётся из данных прибора; поля формы её дополняют,
        # и такие значения помечаются как введённые оператором.
        try:
            base = load_experiment(path).calibration
        except Exception:
            base = Calibration()
        c = payload.get("calibration") or {}
        if any(c.get(k) for k in ("pixel_size_um", "wavelength_um", "n_cell", "n_medium")):
            base = from_user(
                pixel_size_um=c.get("pixel_size_um") or None,
                wavelength_um=c.get("wavelength_um") or None,
                n_cell=c.get("n_cell") or None,
                n_medium=c.get("n_medium") or None, base=base)

        t = threading.Thread(target=_run, daemon=True, args=(
            path, base, int(payload.get("min_area_px") or 500),
            payload.get("method", "ml")))
        t.start()
        return self._send(202, {"started": True})


def find_free_port(preferred=8765, host="127.0.0.1", tries=40):
    """Свободный порт. Сначала привычный, потом любой соседний.

    Жёстко занятый порт — частая причина «программа не запускается»,
    особенно если открыть второй экземпляр.
    """
    import socket
    for port in [preferred] + list(range(preferred + 1, preferred + tries)):
        with socket.socket() as s:
            # SO_REUSEADDR здесь ставить нельзя. На Windows эта опция
            # разрешает двум сокетам занять один и тот же адрес, поэтому
            # привязка к уже слушаемому порту удаётся, и порт всегда
            # объявляется свободным: второй экземпляр программы молча
            # вставал на порт первого и не отвечал. На Windows нужна
            # исключительная привязка, на прочих системах — обычная.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    with socket.socket() as s:          # пусть система выберет сама
        s.bind((host, 0))
        return s.getsockname()[1]


class _Server(ThreadingHTTPServer):
    """HTTP-сервер программы.

    allow_reuse_address на Windows означает SO_REUSEADDR, то есть
    разрешение встать на чужой занятый порт. Оставлять его нельзя по той
    же причине, что и в find_free_port.
    """

    allow_reuse_address = not sys.platform.startswith("win")


def start_server(host="127.0.0.1", port=None):
    """Поднимает интерфейс в отдельном потоке и возвращает (сервер, адрес).

    Нужно окну программы: само окно создаётся в главном потоке, а
    сервер должен работать рядом. Для запуска из консоли есть serve(),
    которая на этом же сервере просто блокируется.
    """
    port = find_free_port(port or 8765, host)
    srv = _Server((host, port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://{host}:{port}/"


def serve(host="127.0.0.1", port=None, open_browser=True):
    from .diagnostics import setup_logging, log_path
    log = setup_logging()
    port = find_free_port(port or 8765, host)
    srv = _Server((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"\n  {__product__} {__version__}")
    print(f"  Интерфейс: {url}")
    print(f"  Журнал:    {log_path()}")
    print(f"  Остановить: закройте это окно или нажмите Ctrl+C\n")
    # Дальше программа уходит в serve_forever и больше ничего не печатает.
    # При перенаправлении вывода поток блочно буферизован, и адрес
    # интерфейса до пользователя не доходил — а это единственное место,
    # где он написан, если браузер не открылся.
    try:
        sys.stdout.flush()
    except Exception:
        pass
    log.info("Веб-интерфейс слушает %s", url)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Остановлено.")
        log.info("Остановлено пользователем")
    finally:
        srv.server_close()
