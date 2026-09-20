"""Настройки приложения.

Значения по умолчанию заданы в defaults.yaml и разумны: обычному
пользователю править файл не нужно. Правка требуется только для
нестандартных данных — например, если объектив даёт другой масштаб
и типичная клетка занимает иное число пикселей.

Порядок применения: defaults.yaml -> holocyt.yaml рядом с программой
-> переменные окружения HOLOCYT_*. Последнее побеждает.
"""

import os
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent
DEFAULTS = CONFIG_DIR / "defaults.yaml"

_CACHE = None


def _parse_simple_yaml(text):
    """Минимальный разбор YAML: секции, пары ключ-значение, комментарии.

    Полноценный YAML-разбор тянул бы ещё одну зависимость в поставку
    ради файла из двадцати строк. Формат намеренно ограничен.
    """
    out, section = {}, None
    for raw in text.splitlines():
        line = raw.split("#")[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            section = line[:-1].strip()
            out[section] = {}
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.lower() in ("true", "false"):
            val = v.lower() == "true"
        elif v.lower() in ("null", "none", ""):
            val = None
        else:
            try:
                val = int(v)
            except ValueError:
                try:
                    val = float(v)
                except ValueError:
                    val = v.strip('"\'')
        if section is None:
            out[k] = val
        else:
            out[section][k] = val
    return out


def load(reload=False):
    """Возвращает настройки как вложенный словарь."""
    global _CACHE
    if _CACHE is not None and not reload:
        return _CACHE
    cfg = _parse_simple_yaml(DEFAULTS.read_text(encoding="utf-8"))

    # Файл пользователя рядом с программой, если он есть.
    user = Path(__file__).resolve().parents[2] / "holocyt.yaml"
    if user.exists():
        for sec, vals in _parse_simple_yaml(user.read_text(encoding="utf-8")).items():
            if isinstance(vals, dict):
                cfg.setdefault(sec, {}).update(vals)
            else:
                cfg[sec] = vals

    # Переменные окружения: HOLOCYT_SEGMENTATION_MIN_AREA_PX и т. п.
    for key, val in os.environ.items():
        if not key.startswith("HOLOCYT_"):
            continue
        parts = key[len("HOLOCYT_"):].lower().split("_", 1)
        if len(parts) != 2 or parts[0] not in cfg:
            continue
        try:
            val = float(val) if "." in val else int(val)
        except ValueError:
            if val.lower() in ("true", "false"):
                val = val.lower() == "true"
        cfg[parts[0]][parts[1]] = val

    _CACHE = cfg
    return cfg


def get(section, key, default=None):
    return load().get(section, {}).get(key, default)
