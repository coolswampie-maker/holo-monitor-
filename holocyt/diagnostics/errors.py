"""Понятные сообщения об ошибках.

Пользователь не должен видеть трассировку Python ни при одной обычной
ошибке. Трассировка идёт в журнал, а на экран — фраза, из которой
понятно, что делать.
"""

import errno
import traceback


class UserError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self):
        return self.message + (f"\n{self.hint}" if self.hint else "")


# Типовые причины и что при них сказать.
_RULES = (
    (FileNotFoundError, "Файл или каталог не найден.",
     "Проверьте путь. Возможно, папку переместили или переименовали."),
    (PermissionError, "Нет прав на чтение или запись.",
     "Выберите другую папку — например, «Документы» — "
     "или запросите доступ у администратора."),
    (IsADirectoryError, "Указан каталог там, где ожидался файл.", None),
    (NotADirectoryError, "Указан файл там, где ожидался каталог.", None),
    (MemoryError, "Не хватает оперативной памяти для обработки.",
     "Закройте другие программы или обрабатывайте эксперимент по частям."),
    (UnicodeDecodeError, "Не удалось прочитать текстовый файл: неизвестная кодировка.",
     "Файл повреждён или создан другой программой."),
)

_ERRNO = {
    errno.ENOSPC: ("На диске нет свободного места.",
                   "Освободите место или выберите другой диск."),
    errno.EROFS: ("Диск доступен только для чтения.",
                  "Выберите другую папку для сохранения."),
    errno.EACCES: ("Доступ запрещён.",
                   "Выберите другую папку или запросите права."),
    errno.ENAMETOOLONG: ("Слишком длинный путь к файлу.",
                         "Перенесите данные ближе к корню диска."),
}


def describe(exc, context=""):
    """Превращает исключение в понятное сообщение.

    Возвращает (текст, подсказка). Трассировку сюда не включаем —
    она пишется в журнал отдельно.
    """
    if isinstance(exc, UserError):
        return exc.message, exc.hint

    code = getattr(exc, "errno", None)
    if code in _ERRNO:
        msg, hint = _ERRNO[code]
        return (f"{context}: {msg}" if context else msg), hint

    for kind, msg, hint in _RULES:
        if isinstance(exc, kind):
            return (f"{context}: {msg}" if context else msg), hint

    base = "Не удалось выполнить операцию."
    return (f"{context}: {base}" if context else base), \
           "Подробности записаны в журнал logs/holocyt.log."


def log_exception(log, exc, context=""):
    """Пишет полную трассировку в журнал и возвращает текст для экрана."""
    log.error("%s: %s: %s", context or "ошибка", type(exc).__name__, exc)
    log.debug("Трассировка:\n%s", "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)))
    return describe(exc, context)
