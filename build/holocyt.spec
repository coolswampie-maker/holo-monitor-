# -*- mode: python ; coding: utf-8 -*-
"""Описание сборки ГОЛОЦИТа для PyInstaller.

Запускается скриптом BUILD_WINDOWS.bat, вручную вызывать не нужно.

Собирается ПАПКА, а не один файл. Так надёжнее: один файл распаковывает
себя во временный каталог при каждом запуске, что медленнее и чаще
вызывает подозрения у антивируса.
"""

import sys
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
# Код приложения лежит в подпапке app/ комплекта переноса. Если её нет
# (сборка прямо из репозитория), берём каталог уровнем выше.
_pkg = spec_dir.parent
root = _pkg / "app" if (_pkg / "app" / "run.py").exists() else _pkg

block_cipher = None

# Данные, которые обязаны попасть в сборку.
datas = [
    (str(root / "holocyt" / "web"), "holocyt/web"),
    (str(root / "holocyt" / "config"), "holocyt/config"),
    (str(root / "models"), "models"),
    (str(root / "demo_data"), "demo_data"),
    (str(root / "VERSION.txt"), "."),
    (str(root / "ABOUT_SOFTWARE.txt"), "."),
]
datas = [(src, dst) for src, dst in datas if Path(src).exists()]

hiddenimports = [
    "sklearn.ensemble._forest",
    "sklearn.ensemble._hist_gradient_boosting.predictor",
    "sklearn.covariance",
    "sklearn.preprocessing",
    "sklearn.tree._utils",
    "scipy.special._cdflib",
    "skimage.feature._basic_features",
    "matplotlib.backends.backend_agg",
    "matplotlib.backends.backend_pdf",
]

# Тяжёлое и ненужное в runtime.
excludes = [
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "IPython", "jupyter", "notebook", "pytest", "sphinx",
    "pandas", "torch", "tensorflow",
]

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon = root / "assets" / "holocyt.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HOLOCYT",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX часто вызывает ложные срабатывания антивируса
    console=True,              # окно консоли показывает адрес и журнал
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HOLOCYT",
)
