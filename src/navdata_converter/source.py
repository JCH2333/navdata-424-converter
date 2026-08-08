from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import replace
from pathlib import Path

from pypinyin import lazy_pinyin
import pymupdf

from .model import CN_PREFIXES, Airport, AirwayLeg, NavModel, Navaid, ProcedureSegment, RejectedProcedure, RejectedRecord, Runway, SourceRef, TerminalWaypoint, Waypoint, is_china_icao
from .pdf_charts import extract_airport_ad219_ils, extract_airport_approach_charts, extract_airport_coordinate_pages, extract_airport_database_charts, extract_airport_standard_procedure_charts


_FIR_COUNTRIES = {
    "\u4e09\u4e9a\u60c5\u62a5\u533a": "ZJ",
    "\u4e0a\u6d77\u60c5\u62a5\u533a": "ZS",
    "\u4e4c\u9c81\u6728\u9f50\u60c5\u62a5\u533a": "ZW",
    "\u5170\u5dde\u60c5\u62a5\u533a": "ZL",
    "\u5317\u4eac\u60c5\u62a5\u533a": "ZB",
    "\u5e7f\u5dde\u60c5\u62a5\u533a": "ZG",
    "\u6606\u660e\u60c5\u62a5\u533a": "ZP",
    "\u6b66\u6c49\u60c5\u62a5\u533a": "ZH",
    "\u6c88\u9633\u60c5\u62a5\u533a": "ZY",
}

# These border fixes have no FIR in the 2608 source table.  Their published
# locations identify the adjacent Fenix country key deterministically.
_EMPTY_FIR_COUNTRY_OVERRIDES = {"SARUL": "ZB", "MAGOG": "VH", "SULEM": "RC", "SADLI": "RK"}
_AIRPORT_PDF_NAME = re.compile(r"\b(?P<icao>Z[A-Z]{3})/[A-Z0-9]{3}\s*[-–]\s*(?P<name>.*)")


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


def _airport_altitude_feet(value: str) -> int:
    """Project airport transition heights to Fenix's 100-foot resolution."""
    return int(round(_float(value) * 3.28084, -2))


def romanize_name(value: str) -> str:
    """Match Fenix's uppercase, separator-free Chinese place-name spelling."""
    return "".join(lazy_pinyin(value or "")).upper()


def _airport_pdf_english_name(text: str, icao: str) -> str | None:
    """Return an AD 2.1 English airport name printed after its Chinese name."""
    values: set[str] = set()
    for line in text.splitlines():
        match = _AIRPORT_PDF_NAME.search(line.upper())
        if match is None or match["icao"] != icao:
            continue
        original = line[match.start("name"):]
        tail = re.search(r"(?P<english>[A-Za-z][A-Za-z0-9 /'\-]*)\s*$", original)
        if tail is None:
            continue
        normalized = " ".join(re.findall(r"[A-Za-z0-9]+", tail["english"])).upper()
        words = normalized.split()
        # AD 2.1 headings can print the same bilingual airport name twice,
        # once in all caps and once in title case (for example ANQING/Anqing).
        # Collapse only an exact adjacent repetition; distinct slash-separated
        # place names such as ALXA LEFT BANNER/Bayanhot remain intact.
        if len(words) % 2 == 0 and words[:len(words) // 2] == words[len(words) // 2:]:
            normalized = " ".join(words[:len(words) // 2])
        if normalized:
            values.add(normalized)
    return next(iter(values)) if len(values) == 1 else None


def _load_airport_pdf_names(model: NavModel) -> None:
    """Use only uniquely printed AD 2.1 English airport names as name evidence."""
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    by_icao = {airport.icao: key for key, airport in model.airports.items()}
    for icao, key in by_icao.items():
        airport_directory = terminal / icao
        if not airport_directory.is_dir():
            continue
        evidence: list[tuple[str, Path, int]] = []
        for pdf in sorted(airport_directory.glob("*.pdf")):
            if pdf.name.upper().startswith(f"{icao}-"):
                continue
            with pymupdf.open(pdf) as document:
                for page_number in range(1, min(document.page_count, 2) + 1):
                    name = _airport_pdf_english_name(document[page_number - 1].get_text("text"), icao)
                    if name:
                        evidence.append((name, pdf, page_number))
        names = {name for name, _, _ in evidence}
        if len(names) != 1:
            continue
        name, pdf, page_number = evidence[0]
        source = SourceRef(
            str(pdf.relative_to(model.root).as_posix()), page_number, page_number,
            hashlib.sha256(pdf.read_bytes()).hexdigest(),
        )
        model.airports[key] = replace(model.airports[key], name=name, name_source=source)


def navaid_country(serviced_airport: str, fir: str) -> str:
    airport_prefix = (serviced_airport or "").strip().upper()[:2]
    if airport_prefix in CN_PREFIXES:
        return airport_prefix
    fir_name = (fir or "").split("\uff0c", maxsplit=1)[0].strip()
    try:
        return _FIR_COUNTRIES[fir_name]
    except KeyError as error:
        raise ValueError(f"unmapped navaid FIR: {fir!r}") from error


def waypoint_country(fir: str, latitude: float | None = None, longitude: float | None = None, ident: str = "") -> str:
    """Map the structured designated-point FIR code to a Fenix country key."""
    if "\u9999\u6e2f" in (fir or ""):
        return "VH"
    if fir:
        return navaid_country("", fir)
    if ident in _EMPTY_FIR_COUNTRY_OVERRIDES:
        return _EMPTY_FIR_COUNTRY_OVERRIDES[ident]
    if latitude is None or longitude is None:
        raise ValueError("empty waypoint FIR without coordinates")
    if 25 <= latitude <= 30 and 120 <= longitude <= 124:
        return "RC"
    if 30 <= latitude <= 40 and 124 <= longitude <= 132:
        return "RK"
    if 15 <= latitude <= 55 and 70 <= longitude <= 135:
        return "CN"
    raise ValueError(f"unmapped empty waypoint FIR at {latitude}, {longitude}")


def _validate_pdf_cache(root: Path, pdf_cache: Path | None) -> Path | None:
    if pdf_cache is None:
        return None
    resolved_cache = pdf_cache.resolve()
    if resolved_cache.is_relative_to(root):
        raise ValueError("PDF 证据缓存不得写入 NAIP 原始数据目录")
    return resolved_cache


def load_naip(root: Path, pdf_cache: Path | None = None) -> NavModel:
    """Load only structured data; PDFs are inspected separately and never guessed."""
    root = root.resolve()
    pdf_cache = _validate_pdf_cache(root, pdf_cache)
    model = NavModel(root=root)
    for row_number, row in enumerate(_rows(root / "AD_HP.csv"), start=2):
        icao = (row.get("CODE_ID") or "").strip().upper()
        if not is_china_icao(icao):
            continue
        key = row["AD_HP_ID"]
        model.airports[key] = Airport(key, icao, row.get("TXT_NAME") or icao,
            round(parse_dms(row.get("GEO_LAT_ACCURACY") or ""), 6), round(parse_dms(row.get("GEO_LONG_ACCURACY") or ""), 6),
            _feet(row.get("VAL_ELEV") or "0"), _airport_altitude_feet(row.get("VAL_TRANSITION_ALT") or "0"),
            _airport_altitude_feet(row.get("VAL_TRANSITION_LEVEL") or "0"), SourceRef("AD_HP.csv", row_number))

    _load_airport_pdf_names(model)

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
                    _float(row.get("VAL_MAG_VAR") or "0"), _number(row.get("VAL_ELEV") or "0"),
                    navaid_country(row.get("SERVICED_AIRPORT") or "", row.get("CODE_FIR") or ""), SourceRef(filename, row_number)))
            except ValueError:
                model.rejected_records.append(RejectedRecord(
                    kind=kind,
                    key=row.get("CODE_ID") or row.get("SIGNIFICANT_POINT_ID") or "",
                    reason="invalid coordinate or unmapped country",
                    source=SourceRef(filename, row_number),
                ))
    for row_number, row in enumerate(_rows(root / "DESIGNATED_POINT.csv"), start=2):
        try:
            latitude = parse_dms(row.get("GEO_LAT_ACCURACY") or "")
            longitude = parse_dms(row.get("GEO_LONG_ACCURACY") or "")
            model.waypoints.append(Waypoint(row["SIGNIFICANT_POINT_ID"], row.get("CODE_ID") or "", row.get("TXT_NAME") or "",
                latitude, longitude, SourceRef("DESIGNATED_POINT.csv", row_number), waypoint_country(row.get("CODE_FIR") or "", latitude, longitude, row.get("CODE_ID") or "")))
        except ValueError:
            model.rejected_records.append(RejectedRecord(
                kind="designated-point", key=row.get("CODE_ID") or row.get("SIGNIFICANT_POINT_ID") or "",
                reason="invalid coordinate or unmapped country", source=SourceRef("DESIGNATED_POINT.csv", row_number),
            ))
    for row_number, row in enumerate(_rows(root / "RTE_SEG.csv"), start=2):
        model.airway_legs.append(AirwayLeg(row.get("TXT_DESIG") or "", _number(row.get("VAL_SORT") or "0"),
            row.get("CODE_POINT_START") or "", row.get("CODE_POINT_END") or "", SourceRef("RTE_SEG.csv", row_number)))
    _load_terminal_coordinate_pages(model, pdf_cache)
    _load_terminal_landing_aids(model)
    _load_terminal_database_charts(model, pdf_cache)
    _build_database_procedure_segments(model)
    _retain_database_referenced_terminal_waypoints(model)
    _load_terminal_approach_charts(model, pdf_cache)
    _load_terminal_standard_procedure_charts(model, pdf_cache)
    _trim_p_route_segments(model)
    _reject_unparsed_charts(model)
    return model


def _load_terminal_landing_aids(model: NavModel) -> None:
    """Retain AD 2.19 landing-aid evidence before any Fenix field projection."""
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    for airport_directory in sorted(path for path in terminal.iterdir() if path.is_dir()):
        for ils in extract_airport_ad219_ils(airport_directory):
            source_path = Path(ils.source.file)
            model.ilses.append(replace(
                ils,
                source=SourceRef(
                    source_path.relative_to(model.root).as_posix(), ils.source.row,
                    ils.source.page, ils.source.sha256,
                ),
            ))


def _load_terminal_coordinate_pages(model: NavModel, pdf_cache: Path | None = None) -> None:
    """Load coordinate-page evidence without treating it as structured NAIP data.

    Coordinate pages are indexed in each airport's Charts.csv.  A page is
    rejected explicitly when its printed identifier and coordinate columns
    cannot be paired one-for-one; an empty result is never silently skipped.
    """
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    for airport_directory in sorted(path for path in terminal.iterdir() if path.is_dir()):
        charts = extract_airport_coordinate_pages(airport_directory) if pdf_cache is None else extract_airport_coordinate_pages(airport_directory, pdf_cache)
        if not charts:
            continue
        points = [point for chart in charts for point in chart.fix_coordinates if point.ident]
        if not points:
            model.rejected_records.append(RejectedRecord(
                "terminal-coordinate-page", airport_directory.name.upper(),
                "coordinate-page identifier and coordinate columns could not be paired",
                SourceRef(str(airport_directory.relative_to(model.root))),
            ))
            continue
        for chart in charts:
            for sequence, point in enumerate(chart.fix_coordinates, start=1):
                if not point.ident:
                    continue
                key = f"{chart.airport}:{chart.filename}:{chart.page}:{sequence}:{point.ident}"
                model.terminal_waypoints.append(TerminalWaypoint(
                    key, chart.airport, point.ident, point.latitude, point.longitude,
                    SourceRef((airport_directory / chart.filename).relative_to(model.root).as_posix(), chart.page, chart.page, chart.source.sha256), chart.airport[:2],
                ))


def _load_terminal_database_charts(model: NavModel, pdf_cache: Path | None = None) -> None:
    """Retain database-coding leg evidence for later Fenix procedure mapping."""
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    for airport_directory in sorted(path for path in terminal.iterdir() if path.is_dir()):
        extractor = extract_airport_database_charts
        model.procedure_charts.extend(extractor(airport_directory) if pdf_cache is None else extractor(airport_directory, pdf_cache))


def _retain_database_referenced_terminal_waypoints(model: NavModel) -> None:
    """Keep coordinate-page points only when a database-coded segment uses them.

    A coordinate page is an airport-wide catalogue, not a procedure sequence.
    Restricting it to explicitly printed legs prevents decorative, runway and
    unused catalogue labels from consuming Fenix waypoint IDs.
    """
    used = {
        (chart.airport, identifier)
        for chart in model.procedure_charts
        for leg in chart.terminal_legs
        for identifier in (leg.fix_ident, leg.center_ident)
        if identifier
    }
    model.terminal_waypoints[:] = [
        point for point in model.terminal_waypoints
        if (point.airport, point.ident) in used
    ]


def _build_database_procedure_segments(model: NavModel) -> None:
    """Group consecutive database-coded rows without inventing route geometry."""
    model.procedure_segments.clear()
    for chart in model.procedure_charts:
        if chart.chart_type != "terminal-database-coding":
            continue
        active_key: tuple[str, str, str, str] | None = None
        active_legs = []

        def flush() -> None:
            if active_key is None or not active_legs:
                return
            label, kind, runway, transition = active_key
            model.procedure_segments.append(ProcedureSegment(
                chart.airport, label, kind, runway, transition, tuple(active_legs), chart.source,
            ))

        for leg in chart.terminal_legs:
            key = (leg.procedure_label, leg.procedure_kind, leg.runway, leg.transition)
            if active_key is not None and key != active_key:
                flush()
                active_legs.clear()
            active_key = key
            active_legs.append(leg)
        flush()


def _load_terminal_approach_charts(model: NavModel, pdf_cache: Path | None = None) -> None:
    """Retain instrument-approach index pages before leg decoding exists."""
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    for airport_directory in sorted(path for path in terminal.iterdir() if path.is_dir()):
        extractor = extract_airport_approach_charts
        model.procedure_charts.extend(extractor(airport_directory) if pdf_cache is None else extractor(airport_directory, pdf_cache))


def _load_terminal_standard_procedure_charts(model: NavModel, pdf_cache: Path | None = None) -> None:
    """Retain SID/STAR chart text as source waypoint-label evidence."""
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    for airport_directory in sorted(path for path in terminal.iterdir() if path.is_dir()):
        extractor = extract_airport_standard_procedure_charts
        model.procedure_charts.extend(
            extractor(airport_directory, include_p_route_vector_evidence=True)
            if pdf_cache is None else extractor(airport_directory, pdf_cache, include_p_route_vector_evidence=True)
        )


def _trim_p_route_segments(model: NavModel) -> None:
    """Trim an uncharted P-route tail only after two consecutive plate edges."""
    result: list[ProcedureSegment] = []
    for segment in model.procedure_segments:
        match = re.fullmatch(r"(P\d{3})-[A-Z]?\d+[A-Z]?", segment.label)
        if match is None:
            result.append(segment)
            continue
        candidates = [
            chart for chart in model.procedure_charts
            if chart.chart_type == "standard-terminal-procedure"
            and chart.airport == segment.airport
            and match[1] in chart.chart_name.upper()
            and segment.runway in chart.runways
            and chart.route_edges
        ]
        if len(candidates) != 1:
            result.append(segment)
            continue
        edges = {frozenset((edge.first, edge.second)) for edge in candidates[0].route_edges}
        retained = list(segment.legs[:1])
        for previous, current in zip(segment.legs, segment.legs[1:]):
            if not previous.fix_ident or not current.fix_ident or frozenset((previous.fix_ident, current.fix_ident)) not in edges:
                break
            retained.append(current)
        result.append(replace(segment, legs=tuple(retained)) if len(retained) >= 3 and len(retained) < len(segment.legs) else segment)
    model.procedure_segments[:] = result


def _reject_unparsed_charts(model: NavModel) -> None:
    terminal = model.root / "Terminal"
    if not terminal.is_dir():
        return
    for index in sorted(terminal.glob("*/Charts.csv")):
        airport = index.parent.name
        for row_number, row in enumerate(_rows(index), start=2):
            kind = row.get("ChartTypeEx_CH") or ""
            chart = row.get("ChartName") or f"第{row_number}行"
            # Database-coding pages are handled by _load_terminal_database_charts.
            # Their publisher type is also an instrument chart, so excluding
            # them here prevents a successfully parsed source page from being
            # reported as an unparsed procedure.
            if "数据库编码" in chart:
                continue
            if "仪表" not in kind and "进近" not in kind:
                continue
            model.rejected_procedures.append(RejectedProcedure(airport, chart, "终端 PDF 语义提取尚未完成", SourceRef(str(index.relative_to(model.root)), row_number)))
