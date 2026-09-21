"""Окно программы.

Интерфейс тот же, что раньше открывался в браузере: локальный сервер и
та же страница. Разница в том, что страница показывается в собственном
окне ГОЛОЦИТа. Браузер пользователя не открывается, адрес и номер порта
ему нигде не показываются.

Окно рисует Microsoft Edge WebView2 — он входит в состав Windows 11 и
современных Windows 10, отдельно ничего ставить не нужно. Если его всё
же нет, программа говорит об этом обычным окном сообщения, а не
трассировкой.

Запуск из браузера остаётся для разработки: `--browser` или
переменная окружения HOLOCYT_BROWSER_MODE=1.
"""

import os
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .version import PRODUCT, VERSION

#: Размер окна. Интерфейс рассчитан на галерею кадров в три столбца.
WIDTH, HEIGHT = 1280, 850
MIN_WIDTH, MIN_HEIGHT = 1050, 700

#: Сколько ждём, пока поднимется локальный сервер.
READY_TIMEOUT = 60.0

WEBVIEW2_MISSING = (
    "Для запуска интерфейса требуется Microsoft Edge WebView2 Runtime.\n\n"
    "Обычно он уже установлен вместе с Windows. Если его нет, установите "
    "«Microsoft Edge WebView2 Runtime» и запустите программу снова."
)


def _app_root() -> Path:
    from .diagnostics.logs import app_root
    return app_root()


def icon_path():
    """Файл значка. В сборке он лежит рядом с ресурсами, в исходниках — в assets."""
    here = Path(__file__).resolve().parent.parent
    for p in (here / "assets" / "holocyt.ico", _app_root() / "assets" / "holocyt.ico"):
        if p.exists():
            return str(p)
    return None


def message_box(text, title=PRODUCT, ask=False):
    """Обычное окно сообщения Windows.

    Нужно до того, как появилось окно программы: если не удалось поднять
    сервер или в системе нет WebView2, показать ошибку больше нечем.
    """
    if not sys.platform.startswith("win"):
        print(f"{title}: {text}")
        return False
    import ctypes

    MB_OK, MB_YESNO, MB_ICONERROR, MB_ICONQUESTION = 0x0, 0x4, 0x10, 0x20
    flags = (MB_YESNO | MB_ICONQUESTION) if ask else (MB_OK | MB_ICONERROR)
    return ctypes.windll.user32.MessageBoxW(None, text, title, flags) == 6


def _wait_ready(url, timeout=READY_TIMEOUT):
    """Ждёт, пока сервер начнёт отвечать. Возвращает True, если дождались."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "api/config", timeout=2):
                return True
        except Exception:
            time.sleep(0.15)
    return False


class Api:
    """Что страница может попросить у окна.

    Только то, чего нельзя сделать внутри страницы: выбрать каталог
    средствами Windows, сохранить готовый файл в место по выбору
    пользователя, открыть папку с результатами. Никаких вычислений
    здесь нет — за них отвечает тот же локальный сервер, что и раньше.
    """

    def __init__(self):
        self._window = None

    # --- выбор каталога эксперимента ---------------------------------
    def pick_experiment_folder(self):
        """Обычный диалог выбора папки Windows. None — если отменили."""
        import webview

        try:
            res = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:
            return None
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else str(res)

    # --- сохранение результатов ---------------------------------------
    def save_result(self, kind):
        """Сохраняет уже сформированный файл туда, куда укажет пользователь.

        Файлы к этому моменту посчитаны и лежат в рабочем каталоге
        программы: здесь только копирование, ничего не пересчитывается.
        """
        import webview

        from .webui import LOCK, STATE

        with LOCK:
            src = STATE.get("csv" if kind == "csv" else "report")
        if not src or not Path(src).exists():
            return {"ok": False, "error": "файл ещё не сформирован"}
        src = Path(src)
        try:
            dst = self._window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=src.name)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not dst:
            return {"ok": False, "cancelled": True}
        dst = Path(dst[0] if isinstance(dst, (list, tuple)) else dst)
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": str(dst)}

    def open_results_folder(self):
        """Открывает папку с результатами в Проводнике."""
        from .webui import OUT

        try:
            OUT.mkdir(parents=True, exist_ok=True)
            os.startfile(str(OUT))          # noqa: S606 — штатный способ Windows
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- сведения о программе ------------------------------------------
    def about(self):
        return {"product": PRODUCT, "version": VERSION}


def run(host="127.0.0.1", port=None):
    """Поднимает сервер и показывает интерфейс в окне программы.

    Возвращает код выхода. Окно закрыли — сервер останавливается, порт
    освобождается, процесс завершается.
    """
    from .diagnostics import log_path, setup_logging

    log = setup_logging()

    try:
        import webview
    except Exception as exc:
        log.error("Не удалось загрузить оболочку окна: %s", exc)
        message_box(WEBVIEW2_MISSING)
        return 1

    from .webui import start_server

    try:
        srv, url = start_server(host, port)
    except Exception as exc:
        log.exception("Не удалось запустить локальный сервер")
        if message_box(
                f"Не удалось запустить {PRODUCT}.\n\n"
                f"Подробности записаны в журнал:\n{log_path()}\n\n"
                f"Открыть журнал?", ask=True):
            _open_log()
        return 1

    log.info("Окно программы: интерфейс на %s", url)

    if not _wait_ready(url):
        log.error("Интерфейс не ответил за %.0f с", READY_TIMEOUT)
        _stop(srv)
        if message_box(
                f"Не удалось запустить {PRODUCT}.\n\n"
                f"Интерфейс не ответил за {READY_TIMEOUT:.0f} секунд.\n"
                f"Подробности записаны в журнал:\n{log_path()}\n\n"
                f"Открыть журнал?", ask=True):
            _open_log()
        return 1

    api = Api()
    window = webview.create_window(
        PRODUCT, url,
        js_api=api,
        width=WIDTH, height=HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        resizable=True,
        text_select=False,
    )
    api._window = window

    try:
        # debug=False — без панели разработчика и без контекстного меню.
        webview.start(gui="edgechromium", debug=False, icon=icon_path())
    except Exception as exc:
        log.exception("Окно программы не открылось")
        _stop(srv)
        message_box(WEBVIEW2_MISSING)
        return 1

    # Сюда попадаем, когда пользователь закрыл окно.
    log.info("Окно закрыто, останавливаю локальный сервер")
    _stop(srv)
    return 0


def _stop(srv):
    """Останавливает сервер и освобождает порт."""
    try:
        srv.shutdown()
    except Exception:
        pass
    try:
        srv.server_close()
    except Exception:
        pass


def _open_log():
    from .diagnostics import log_path

    try:
        os.startfile(str(log_path()))       # noqa: S606
    except Exception:
        pass
