from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

from pypinyin import lazy_pinyin

from .model import Airport, AirwayLeg, NavModel, Navaid, RejectedProcedure, Runway, SourceRef, Waypoint, is_china_icao


def parse_dms(value: str) -> float:
    """Parse fixed-width NAIP DMS coordinates without guessing degree width."""
    raw = (value or "").strip().upper()
    if len(raw) < 5 or raw[0] not in "NSEW":
        raise ValueError(f"无效坐标: {value!r}")
    hemisphere, digits = raw[0], raw[1:]
    whole, dot, fraction = digits.partition(".")
    degree_digits = 2 if hemisphere in "NS" else 3
    if len(whole) < degree_digits + 4:
        raise ValueError(f"无效坐标: {value!r}")
    degrees = int(whole[:degree_digits])
    minutes = int(whole[degree_digits:degree_digits + 2])
    seconds = float(whole[degree_digits + 2:] + (dot + fraction if dot else ""))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"无效坐标: {value!r}")
    result = degrees + minutes / 60 + seconds / 3600
    return -result if hemisphere in "SW" else result


def _rows(path: Path):
    raw = path.read_bytes()
    # The main NAIP tables are commonly GBK, while per-airport Charts.csv is UTF-8.
    for encoding in ("utf-8-sig", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - both supported encodings failed
        raise UnicodeDecodeError("naip", raw, 0, len(raw), "不支持的 CSV 编码")
    yield from csv.DictReader(text.splitlines())


def _number(value: str, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except ValueError:
        return default


def _float(value: str, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except ValueError:
        return default


def _surface(value: str) -> str:
    normalized = (value or "").upper()
    if any(token in normalized for token in ("水泥", "沥青", "混凝土", "CON", "ASP")):
        return "ASP"
    if any(token in normalized for token in ("草", "土", "GRE", "GRASS")):
        return "GRE"
    if any(token in normalized for token in ("水", "WAT")):
        return "WAT"
    return "U"


def _feet(value: str) -> int:
    """NAIP vertical and runway dimensions are meters; Fenix stores feet."""
    return round(_float(value) * 3.28084)


def romanize_name(value: str) -> str:
    """Match Fenix's uppercase, separator-free Chinese place-name spelling."""
    return "".join(lazy_pinyin(value or "")).upper()


def load_naip(root: Path) -> NavModel:
    """Load only structured data; PDFs are inspected separately and never guessed."""
    root = root.resolve()
    model = NavModel(root=root)
    for row_number, row in enumerate(_rows(root / "AD_HP.csv"), start=2):
        icao = (row.get("CODE_ID") or "").strip().upper()
        if not is_china_icao(icao):
            continue
        key = row["AD_HP_ID"]
        model.airports[key] = Airport(key, icao, row.get("TXT_NAME") or icao,
            parse_dms(row.get("GEO_LAT_ACCURACY") or ""), parse_dms(row.get("GEO_LONG_ACCURACY") or ""),
            _feet(row.get("VAL_ELEV") or "0"), _feet(row.get("VAL_TRANSITION_ALT") or "0"),
            _number(row.get("VAL_TRANSITION_LEVEL") or "0"), SourceRef("AD_HP.csv", row_number))

    runway_airports: dict[str, str] = {}
    dimensions: dict[str, tuple[int, int, str]] = {}
    for row_number, row in enumerate(_rows(root / "RWY.csv"), start=2):
        if row.get("AD_HP_ID") in model.airports:
            runway_airports[row["RWY_ID"]] = row["AD_HP_ID"]
            dimensions[row["RWY_ID"]] = (_feet(row.get("VAL_LEN") or "0"), _feet(row.get("VAL_WID") or "0"), _surface(row.get("CODE_COMPOSITION") or ""))
    for row_number, row in enumerate(_rows(root / "RWY_DIRECTION.csv"), start=2):
        airport_key = runway_airports.get(row.get("RWY_ID") or "")
        if airport_key:
            length, width, surface = dimensions[row["RWY_ID"]]
            model.runways.append(Runway(row["RWY_DIRECTION_ID"], airport_key, row.get("TXT_DESIG") or "",
                _float(row.get("VAL_TRUE_BRG") or "0"), length, width, surface, _feet(row.get("VAL_ELEV") or "0"),
                SourceRef("RWY_DIRECTION.csv", row_number)))

    for filename, kind, divisor in (("VOR.csv", "VOR", 1), ("NDB.csv", "NDB", 1)):
        for row_number, row in enumerate(_rows(root / filename), start=2):
            try:
                model.navaids.append(Navaid(row["SIGNIFICANT_POINT_ID"], row.get("CODE_ID") or "", kind,
                    row.get("TXT_NAME") or "", parse_dms(row.get("GEO_LAT_ACCURACY") or ""),
                    parse_dms(row.get("GEO_LONG_ACCURACY") or ""), _float(row.get("VAL_FREQ") or "0") / divisor,
                    _float(row.get("VAL_MAG_VAR") or "0"), _number(row.get("VAL_ELEV") or "0"), SourceRef(filename, row_number)))
            except ValueError:
                continue
    for row_number, row in enumerate(_rows(root / "DESIGNATED_POINT.csv"), start=2):
        try:
            model.waypoints.append(Waypoint(row["SIGNIFICANT_POINT_ID"], row.get("CODE_ID") or "", row.get("TXT_NAME") or "",
                parse_dms(row.get("GEO_LAT_ACCURACY") or ""), parse_dms(row.get("GEO_LONG_ACCURACY") or ""), SourceRef("DESIGNATED_POINT.csv", row_number)))
        except ValueError:
            continue
    for row_number, row in enumerate(_rows(root / "RTE_SEG.csv"), start=2):
        model.airway_legs.append(AirwayLeg(row.get("TXT_DESIG") or "", _number(row.get("VAL_SORT") or "0"),
            row.get("CODE_POINT_START") or "", row.get("CODE_POINT_END") or "", SourceRef("RTE_SEG.csv", row_number)))
    _reject_unparsed_charts(model)
    return model


def _reject_unparsed_charts(model: NavModel) -> None:
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    for index in sorted(terminal.glob("*/Charts.csv")):
        airport = index.parent.name
        for row_number, row in enumerate(_rows(index), start=2):
            kind = row.get("ChartTypeEx_CH") or ""
            if "仪表" not in kind and "进近" not in kind:
                continue
            chart = row.get("ChartName") or f"第{row_number}行"
            model.rejected_procedures.append(RejectedProcedure(airport, chart, "终端 PDF 语义提取尚未完成", SourceRef(str(index.relative_to(model.root)), row_number)))
