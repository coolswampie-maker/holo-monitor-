"""Импорт экспериментов штатного ПО микроскопа (Hstudio, HoloMonitor M4).

Что подтверждено реальными файлами
----------------------------------
Форматы разобраны по данным, восстановленным с дистрибутивной флешки
прибора (эксперимент «Example woundhealing», 56 карт фазы, и выгрузка
базы «MCF-10A time-lapse»).

Карта фазы — двоичный файл, две версии:

    .fmx (2017)               .bin (2010)
    0  uint32 ширина          0  uint32 версия = 1
    4  uint32 высота          4  uint32 тип = 2
    8  float32 [ш*в] фаза     8  uint32 ширина
       1032 байта служебных  12  uint32 высота
                             16  float32 верхняя граница
                             20  float32 нижняя граница
                             24  float32 [ш*в] фаза
                                 1024 байта служебных

Значения фазы — в долях длины волны (то есть сдвиг, делённый на 2*pi).
Это те же единицы, в которых Hstudio считает Phase shift sum.

Чего в карте фазы НЕТ
--------------------
Размера пикселя, длины волны и показателей преломления. Проверено по
всем 56 файлам образца. Эти величины приходится задавать, и импортёр
помечает их как подставленные (см. holocyt/importers/provenance.py),
чтобы в протоколе они не выглядели измеренными.

Источник калибровки, если он есть
---------------------------------
Файл DBTransferInfo.xml в выгрузке базы содержит настоящий паспорт
съёмки: CameraPixelSize, Lens, LaserWaveLength, RefIndexMedium,
RefIndexObject. Если такой файл рядом есть, значения берутся из него и
помечаются как измеренные.

Чего импортёр НЕ делает
-----------------------
Не читает базу phidbdata.sdf (формат Microsoft SQL Server Compact 4.0,
без Windows и .NET недоступен) и не обращается к библиотекам прибора.
Для работы это и не требуется: карты фазы лежат отдельными файлами.
"""

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..calibration import Calibration, from_transfer_xml
from ..optics import OpticalConfig
from .provenance import Provenance

# Поддерживаемое расширение карты фазы. Формат .bin (версия 2010)
# намеренно НЕ поддержан: его раскладка в памяти не разобрана, и
# декодирование даёт искажённое изображение (анизотропия соседних
# разностей 2,15 против 1,00 у корректного кадра). Отдавать такие
# данные под видом измерений нельзя.
FMX_SUFFIXES = (".fmx",)
UNSUPPORTED_SUFFIXES = (".bin",)

# Порядок поиска источников. Калибровка есть только в первом.
SOURCE_ORDER = ("DBTransferInfo.xml", "imagedb.xml", "*.fmx")


class UnsupportedFormat(ValueError):
    """Формат распознан, но чтение не поддержано."""


@dataclass
class PhaseMatrix:
    """Карта фазы с указанием происхождения сопутствующих величин."""

    path: Path
    phase: np.ndarray            # доли длины волны
    width: int
    height: int
    version: str                 # "fmx-2017" или "bin-2010"
    provenance: Provenance = field(default_factory=Provenance)

    @property
    def shape(self):
        return self.phase.shape


def read_phase_matrix(path) -> PhaseMatrix:
    """Читает карту фазы. Версия формата определяется по заголовку."""
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) < 28:
        raise ValueError(f"файл слишком мал для карты фазы: {path}")

    a, b, c, d = struct.unpack("<IIII", raw[:16])
    if a == 1 and b == 2 and 0 < c <= 1 << 16 and 0 < d <= 1 << 16 \
            and len(raw) >= 24 + c * d * 4:
        raise UnsupportedFormat(
            f"{path.name}: формат карты фазы версии 2010 (.bin) не поддержан. "
            f"Его раскладка в памяти не разобрана, и чтение даёт искажённое "
            f"изображение. Используйте эксперименты в формате .fmx.")
    elif 0 < a <= 1 << 16 and 0 < b <= 1 << 16 and len(raw) >= 8 + a * b * 4:
        w, h, off, ver = a, b, 8, "fmx-2017"
    else:
        raise ValueError(
            f"не распознан формат карты фазы: {path.name}. "
            f"Первые 16 байт: {raw[:16].hex()}")

    phase = np.frombuffer(raw, dtype="<f4", count=w * h,
                          offset=off).reshape(h, w).astype(np.float64)

    prov = Provenance()
    prov.measured("width", w, f"{path.name}, заголовок")
    prov.measured("height", h, f"{path.name}, заголовок")
    prov.measured("phase_unit", "доли длины волны", f"{path.name}")
    prov.measured("format_version", ver, f"{path.name}, заголовок")
    return PhaseMatrix(path=path, phase=phase, width=w, height=h,
                       version=ver, provenance=prov)


def read_transfer_info(path):
    """Разбирает DBTransferInfo.xml — паспорт съёмки, если он есть."""
    path = Path(path)
    xml = path if path.is_file() else path / "DBTransferInfo.xml"
    if not xml.exists():
        return [], {}
    root = ET.parse(xml).getroot()
    frames, optics = [], {}
    for fr in root.findall("Frame"):
        holo = fr.find("Hologram")
        if holo is None:
            continue
        if not optics:
            def f(name):
                v = holo.get(name)
                return float(v) if v not in (None, "") else None
            cam, lens = f("CameraPixelSize"), f("Lens")
            wl = f("LaserWaveLength")
            optics = {
                "camera_pixel_um": cam, "lens": lens,
                "pixel_size_um": (cam / lens) if cam and lens else None,
                "wavelength_um": (wl / 1000.0) if wl else None,
                "n_medium": f("RefIndexMedium"), "n_cell": f("RefIndexObject"),
                "exposure_s": f("ExposureTime"), "gain": f("Gain"),
                "_source": str(xml),
            }
        pm = holo.find("./Reconstruct/PhaseMatrix")
        frames.append({
            "file": pm.get("ImageName") if pm is not None else None,
            "hologram": holo.get("ImageName"),
            "project": fr.get("Project"), "group": fr.get("Group"),
            "time": fr.get("CreateDateTime"),
            "description": fr.get("Description"),
        })
    return frames, optics


@dataclass
class HstudioExperiment:
    """Эксперимент Hstudio, приведённый к внутреннему виду ГОЛОЦИТа."""

    root: Path
    name: str
    phase_files: list
    provenance: Provenance
    calibration: Calibration = field(default_factory=Calibration)
    frames_meta: list = field(default_factory=list)
    database: Path = None
    layout: str = ""              # как распознан каталог
    sources_found: list = field(default_factory=list)

    @property
    def n_frames(self):
        return len(self.phase_files)

    @property
    def calibrated(self):
        return self.calibration.complete

    def optical_config(self) -> OpticalConfig:
        """Оптические параметры. Только при полной калибровке."""
        return self.calibration.to_optics()

    def frame_shape(self):
        """Размер кадра, прочитанный из первого файла."""
        pm = read_phase_matrix(self.phase_files[0])
        return pm.width, pm.height

    def warnings(self):
        out = list(self.provenance.warnings())
        if not self.calibrated:
            miss = ", ".join(self.calibration.missing)
            out.append(
                f"Калибровка не найдена — физические величины недоступны. "
                f"Отсутствует: {miss}. Нужен файл DBTransferInfo.xml из "
                f"выгрузки базы Hstudio либо ввод значений вручную.")
        return out


def detect(path):
    """Распознаёт каталог Hstudio. Возвращает имя раскладки или None."""
    path = Path(path)
    if not path.is_dir():
        return None
    if (path / "imagedb.xml").exists() and (path / "Storage").exists():
        return "experiment"       # каталог эксперимента Hstudio
    if (path / "DBTransferInfo.xml").exists():
        return "transfer"         # выгрузка базы для переноса
    # ВНИМАНИЕ: rglob возвращает генератор, и any(генератор) истинно всегда.
    # Здесь нужна именно проверка на наличие хотя бы одного файла.
    def _has(suffixes):
        return any(next(path.rglob(f"*{s}"), None) is not None for s in suffixes)

    if _has(FMX_SUFFIXES):
        return "loose"            # просто карты фазы россыпью
    if _has(UNSUPPORTED_SUFFIXES):
        return "unsupported"      # есть карты фазы, но неподдержанной версии
    return None


def _sorted_phase_files(files):
    def key(p):
        stem = "".join(ch for ch in p.stem if ch.isdigit())
        return (0, int(stem)) if stem else (1, p.stem)
    return sorted(files, key=key)


def load_experiment(path) -> HstudioExperiment:
    """Загружает эксперимент Hstudio и фиксирует происхождение величин."""
    path = Path(path)
    layout = detect(path)
    if layout == "unsupported":
        raise UnsupportedFormat(
            f"{path}: найдены карты фазы версии 2010 (.bin), которые "
            f"программа не читает. Поддерживается формат .fmx.")
    if layout is None:
        raise FileNotFoundError(
            f"{path} не похож на данные Hstudio: нет ни imagedb.xml, "
            f"ни DBTransferInfo.xml, ни файлов *.fmx / *.bin")

    prov = Provenance()
    name = path.name
    frames_meta, optics = [], {}

    if layout == "experiment":
        try:
            node = ET.parse(path / "imagedb.xml").getroot().find("ImageDatabase")
            if node is not None:
                name = node.get("Name") or name
                prov.measured("experiment_name", name, "imagedb.xml")
                if node.get("CreateTime"):
                    prov.measured("created", node.get("CreateTime"), "imagedb.xml")
                if node.get("GUID"):
                    prov.measured("database_guid", node.get("GUID"), "imagedb.xml")
        except ET.ParseError:
            pass
        files = _sorted_phase_files(
            [p for s in FMX_SUFFIXES
             for p in (path / "Storage" / "PhaseMatrixStorage").rglob(f"*{s}")])
    elif layout == "transfer":
        frames_meta, optics = read_transfer_info(path)
        if frames_meta:
            name = frames_meta[0].get("project") or name
            prov.measured("experiment_name", name, "DBTransferInfo.xml")
        files = _sorted_phase_files(
            [path / fr["file"] for fr in frames_meta
             if fr.get("file") and (path / fr["file"]).exists()
             and Path(fr["file"]).suffix.lower() in FMX_SUFFIXES])
    else:
        files = _sorted_phase_files(
            [p for s in FMX_SUFFIXES for p in path.rglob(f"*{s}")])

    if not files:
        n_bin = sum(1 for suf in UNSUPPORTED_SUFFIXES for _ in path.rglob(f"*{suf}"))
        if n_bin:
            raise UnsupportedFormat(
                f"В каталоге {path.name} найдено {n_bin} карт фазы версии 2010 "
                f"(.bin) и ни одной версии .fmx. Формат 2010 года не поддержан: "
                f"его раскладка в памяти не разобрана, и чтение даёт искажённое "
                f"изображение. Калибровка из DBTransferInfo.xml при этом читается "
                f"и может быть применена к другому эксперименту.")
        raise FileNotFoundError(
            f"В каталоге {path.name} не найдено ни одной карты фазы (*.fmx).")
    prov.measured("n_phase_files", len(files), str(path))

    # Калибровка. Единственный её источник в данных прибора —
    # DBTransferInfo.xml. Нет файла — нет калибровки, и точка.
    sources = []
    if (path / "DBTransferInfo.xml").exists():
        sources.append("DBTransferInfo.xml")
    if (path / "imagedb.xml").exists():
        sources.append("imagedb.xml")
    sources.append(f"{len(files)} файлов карт фазы")

    if optics and optics.get("_source"):
        cal = from_transfer_xml(optics, optics["_source"])
    else:
        cal = Calibration()

    db = path / "Database" / "phidbdata.sdf"
    if db.exists():
        prov.measured("database_file", str(db), "каталог Database")
        prov.assumed("database_readable", False,
                     note="формат Microsoft SQL Server Compact 4.0; "
                          "без Windows и .NET не читается, в анализе не используется")

    return HstudioExperiment(root=path, name=name, phase_files=files,
                             provenance=prov, calibration=cal,
                             frames_meta=frames_meta,
                             database=db if db.exists() else None,
                             layout=layout, sources_found=sources)


def write_manifest(experiment: HstudioExperiment, out_csv=None, group=None):
    """Составляет manifest.csv — общий формат входа ГОЛОЦИТа."""
    import csv
    out_csv = Path(out_csv) if out_csv else experiment.root / "manifest.csv"
    by_file = {}
    for fr in experiment.frames_meta:
        if fr.get("file"):
            by_file[Path(fr["file"]).name] = fr
    rows = []
    for i, p in enumerate(experiment.phase_files):
        meta = by_file.get(p.name, {})
        rows.append({
            "file": str(p.relative_to(experiment.root)),
            "group": group or meta.get("group") or experiment.name,
            "concentration": "", "replicate": 1, "field": i + 1,
            # Время ставим только если оно реально есть в данных прибора.
            "time_h": "", "capture_time": meta.get("time") or "",
        })
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    return out_csv, len(rows)
