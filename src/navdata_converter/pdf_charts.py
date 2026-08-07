"""Evidence-preserving extraction of terminal-chart PDF text layers.

This module deliberately does not invent ARINC leg semantics from geometry.  It
returns observable labels and fix identifiers so the Fenix adapter can reject a
chart until an explicit mapping is implemented and tested.
"""

from __future__ import annotations

import hashlib
import json
import re
import csv
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pymupdf
from pypdf import PdfReader

from .model import ChartFixCoordinate, ChartRouteFix, ChartTerminalLeg, ProcedureChart, SourceRef


_EVIDENCE_CACHE_VERSION = 2


_PROCEDURE = re.compile(r"\b([A-Z0-9]{2,6}-\d{2}[AD])\b")
_RUNWAY = re.compile(r"\bRWY\s?(\d{2}[LRC]?)\b")
_SHARED_RUNWAYS = re.compile(r"\bRWY\s?\d{2}[LRC]?(?:\s*/\s*(?:RWY\s?)?\d{2}[LRC]?)+\b")
_APPROACH_VARIANT = re.compile(r"\b(?P<variant>[WXYZ])\s+RWY\s?\d{2}[LRC]?\b", re.IGNORECASE)
_RNP_AR_LONG_NAME_AIRPORTS = {"ZYTL"}
_WAYPOINT = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\b")
_IGNORED = {"CAAC", "ALL", "RIGHTS", "RESER", "MSA", "RNP", "ILS", "DME", "RWY", "ATC", "GP", "INOP", "N", "E", "S", "W"}
_ROUTE_ROLE = {"IAF", "IF", "FAF", "MAP", "MAPT", "MAHF"}
_CHART_COORDINATE = re.compile(
    r"\bN\s*(?P<lat_deg>\d{2})\s*(?:[°º]|D)?\s*(?P<lat_min>\d{2}(?:\.\d+)?)\s*(?:['′])?"
    r"\s*[,/ ]*E\s*(?P<lon_deg>\d{3})\s*(?:[°º]|D)?\s*(?P<lon_min>\d{2}(?:\.\d+)?)\s*(?:['′])?\b",
    re.IGNORECASE,
)
_DATABASE_PROCEDURE = re.compile(r"\bRWY\s?(?P<runway>\d{2}[LRC]?)\s*(?P<kind>\u79bb\u573a|\u8fdb\u573a|\u7b49\u5f85)?\s*[^\n]*?(?P<label>[A-Z0-9]{1,6}-\d{1,2}[A-Z]{1,2})(?:\b|\()")
_DATABASE_LEG = re.compile(r"^(?P<leg_type>CF|DF|TF|CA|IF|HM|RF|AF|FA|FC|FD|FM|HA|HF|PI|VI|VM)\b(?:\s+(?P<fix>[A-Z][A-Z0-9]{0,5}))?")
_DATABASE_SPEED = re.compile(r"^MAX(?P<speed>\d{2,3})$", re.IGNORECASE)
_COORDINATE_PAGE_IDENT = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
_DMS_COORDINATE = re.compile(
    r"N\s*(?P<lat_deg>\d{2})\D+?(?P<lat_min>\d{2})\D+?(?P<lat_sec>\d{2}(?:\.\d+)?)[\"']?\s*"
    r"E\s*(?P<lon_deg>\d{2,3})\D+?(?P<lon_min>\d{2})\D+?(?P<lon_sec>\d{2}(?:\.\d+)?)[\"']?",
    re.IGNORECASE,
)
_DM_COORDINATE = re.compile(
    r"N\s*(?P<lat_deg>\d{2})\D+?(?P<lat_min>\d{2}(?:\.\d+)?)[\"']\s*"
    r"E\s*(?P<lon_deg>\d{2,3})\D+?(?P<lon_min>\d{2}(?:\.\d+)?)[\"']",
    re.IGNORECASE,
)


def extract_fix_coordinates(text: str) -> tuple[ChartFixCoordinate, ...]:
    """Return only explicitly printed north/east chart coordinates.

    Terminal-chart reading order is not route order, so this function preserves
    nearby labels as evidence and deliberately makes no leg or procedure claim.
    """
    coordinates: list[ChartFixCoordinate] = []
    for match in _CHART_COORDINATE.finditer(text):
        labels = [token for token in _WAYPOINT.findall(text[max(0, match.start() - 48):match.start()]) if token not in _IGNORED]
        coordinates.append(ChartFixCoordinate(
            ident=labels[-1] if labels else None,
            latitude=int(match["lat_deg"]) + float(match["lat_min"]) / 60,
            longitude=int(match["lon_deg"]) + float(match["lon_min"]) / 60,
            raw=match.group(0),
        ))
    return tuple(coordinates)


def _extract_runways(text: str) -> tuple[str, ...]:
    """Read individual and slash-shared runway labels from chart text."""
    runways = set(_RUNWAY.findall(text))
    for match in _SHARED_RUNWAYS.finditer(text):
        runways.update(re.findall(r"\d{2}[LRC]?", match.group(0)))
    return tuple(sorted(runways))


def approach_procedure_name_candidates(chart_name: str, runways: tuple[str, ...], airport: str = "") -> tuple[str, ...]:
    """Derive only title-supported Fenix approach-name candidates.

    CAAC titles explicitly carry the ILS/RNP family and X/Y/Z variant for
    some charts.  Names without that variant are intentionally reduced to the
    observed generic runway form, while a combined RNP ILS title retains both
    possible families for read-only reference comparison.
    """
    title = chart_name.upper()
    title_runways = _extract_runways(title)
    variant_match = _APPROACH_VARIANT.search(title)
    variant = variant_match["variant"].upper() if variant_match else ""
    families = (
        ([] if "ILS" not in title else ["I"])
        + ([] if "RNP" not in title else ["R"])
        + ([] if "VOR/DME" not in title else ["D"])
        + (["Q"] if "NDB/DME" in title else ([] if "NDB" not in title else ["N"]))
    )
    candidates: list[str] = []
    for runway in title_runways or runways:
        if not variant:
            candidates.extend(f"{family}{runway}" for family in families or ["R"])
            continue
        # The finished 2608 library retains a base ILS/RNP procedure alongside
        # the explicitly lettered chart variants.  It is a title-supported
        # compatibility candidate, not a claim that both share leg geometry.
        candidates.extend(f"{family}{runway}" for family in families if family in {"I", "R"})
        for family in families:
            if family in {"D", "N", "Q"}:
                candidates.append(f"{family}{runway}")
                continue
            separator = "" if family == "I" and len(runway) > 2 else "-"
            candidates.append(f"{family}{runway}{separator}{variant}")
            if family == "R" and "(AR)" in title and airport.upper() in _RNP_AR_LONG_NAME_AIRPORTS:
                candidates.append(f"R{runway}-AR-{variant}")
    return tuple(dict.fromkeys(candidates))


def extract_coordinate_page_points(text: str) -> tuple[ChartFixCoordinate, ...]:
    """Pair a terminal coordinate-page's identifier and coordinate columns.

    The CAAC coordinate pages present two independent columns in extraction
    order: all identifiers followed by all coordinates.  Pairing is accepted
    only when their counts agree exactly.
    """
    identifiers: list[str] = []
    coordinates: list[ChartFixCoordinate] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _COORDINATE_PAGE_IDENT.fullmatch(line) and line not in _IGNORED:
            identifiers.append(line)
            continue
        match = _DMS_COORDINATE.search(line)
        if match:
            latitude = int(match["lat_deg"]) + int(match["lat_min"]) / 60 + float(match["lat_sec"]) / 3600
            longitude = int(match["lon_deg"]) + int(match["lon_min"]) / 60 + float(match["lon_sec"]) / 3600
            coordinates.append(ChartFixCoordinate(None, latitude, longitude, match.group(0)))
            continue
        match = _DM_COORDINATE.search(line)
        if match:
            latitude = int(match["lat_deg"]) + float(match["lat_min"]) / 60
            longitude = int(match["lon_deg"]) + float(match["lon_min"]) / 60
            coordinates.append(ChartFixCoordinate(None, latitude, longitude, match.group(0)))
    if not identifiers or len(identifiers) != len(coordinates):
        return ()
    return tuple(
        ChartFixCoordinate(identifier, coordinate.latitude, coordinate.longitude, coordinate.raw)
        for identifier, coordinate in zip(identifiers, coordinates, strict=True)
    )


def extract_positioned_coordinate_page_points(words: list[tuple[float, float, float, float, str, int, int, int]]) -> tuple[ChartFixCoordinate, ...]:
    """Read identifier/coordinate pairs from their rendered PDF positions.

    Some CAAC PDFs store individual coordinate text objects out of stream order.
    Their visual rows remain reliable, so pair a coordinate with the nearest
    identifier to its left on the same rendered line instead of trusting text
    extraction order.
    """
    identifiers = [
        (x0, y0, text)
        for x0, y0, _, _, text, *_ in words
        if _COORDINATE_PAGE_IDENT.fullmatch(text) and text not in _IGNORED
    ]
    result: list[tuple[float, float, ChartFixCoordinate]] = []
    for coordinate_x, coordinate_y, _, _, token, *_ in words:
        match = _DMS_COORDINATE.search(token) or _DM_COORDINATE.search(token)
        if not match:
            continue
        candidates = [
            (identifier_x, identifier_y, identifier)
            for identifier_x, identifier_y, identifier in identifiers
            if identifier_x < coordinate_x and abs(identifier_y - coordinate_y) <= 3
        ]
        if not candidates:
            continue
        _, _, identifier = max(candidates, key=lambda candidate: (candidate[0], -abs(candidate[1] - coordinate_y)))
        latitude = int(match["lat_deg"]) + float(match["lat_min"]) / 60
        longitude = int(match["lon_deg"]) + float(match["lon_min"]) / 60
        if "lat_sec" in match.groupdict() and match["lat_sec"] is not None:
            latitude += float(match["lat_sec"]) / 3600
            longitude += float(match["lon_sec"]) / 3600
        result.append((coordinate_y, coordinate_x, ChartFixCoordinate(identifier, latitude, longitude, match.group(0))))
    return tuple(point for _, _, point in sorted(result))


def extract_positioned_route_fixes(words: list[tuple[float, float, float, float, str, int, int, int]]) -> tuple[ChartRouteFix, ...]:
    """Read route fixes only where the PDF explicitly labels their procedure role.

    CAAC plates put labels such as ``IAF`` and ``YK603`` in separate text
    objects but the same PDF text block.  Requiring that block plus overlapping
    horizontal positions avoids promoting arbitrary map labels or chart notes
    into route evidence.  This is source evidence, not an inferred leg order.
    """
    result: list[ChartRouteFix] = []
    for role_x0, role_y0, role_x1, role_y1, raw_role, block, *_ in words:
        role = raw_role.upper()
        if role not in _ROUTE_ROLE:
            continue
        candidates = []
        for fix_x0, fix_y0, fix_x1, fix_y1, raw_fix, fix_block, *_ in words:
            fix = raw_fix.upper()
            if fix_block != block or not _COORDINATE_PAGE_IDENT.fullmatch(fix) or fix in _IGNORED or fix in _ROUTE_ROLE:
                continue
            vertical_gap = min(abs(fix_y0 - role_y1), abs(role_y0 - fix_y1))
            horizontal_overlap = min(role_x1, fix_x1) - max(role_x0, fix_x0)
            if vertical_gap <= 12 and horizontal_overlap >= -1:
                candidates.append((vertical_gap, -horizontal_overlap, fix))
        if candidates:
            result.append(ChartRouteFix(min(candidates)[2], role))
    return tuple(dict.fromkeys(result))


def _database_leg_attributes(lines: list[str], start: int, leg_type: str, fix_ident: str | None) -> tuple[float | None, float | None, str | None, int | None]:
    """Read observable numeric fields from one database-coding table row."""
    values: list[str] = []
    for line in lines[start + 1:]:
        if _DATABASE_LEG.match(line) or _DATABASE_PROCEDURE.search(line):
            break
        if line:
            values.append(line)
    if fix_ident and values[:1] == [fix_ident]:
        values.pop(0)
    turn_direction = next((value for value in values if value in {"L", "R"}), None)
    speed = next((int(match["speed"]) for value in values if (match := _DATABASE_SPEED.fullmatch(value))), None)
    numeric = [float(value) for value in values if value.isdecimal()]
    course = None
    altitude = None
    if leg_type == "CA" and numeric:
        course = numeric[0]
        altitude = numeric[1] if len(numeric) > 1 else None
    elif leg_type == "CF" and numeric:
        course = numeric[0]
    elif leg_type == "DF" and numeric:
        altitude = numeric[0]
    return course, altitude, turn_direction, speed


def extract_terminal_leg_evidence(text: str) -> tuple[ChartTerminalLeg, ...]:
    """Extract ordered database-chart rows without inferring ARINC semantics.

    PDF table reading order places a leading CF/CA row immediately before its
    procedure heading.  It is attached only when the next observable heading
    confirms that association; all remaining rows retain their literal text.
    """
    result: list[ChartTerminalLeg] = []
    active_label = ""
    active_runway = ""
    active_kind = ""
    active_rows: list[tuple[str, str | None, str, float | None, float | None, str | None, int | None]] = []
    pending_rows: list[tuple[str, str | None, str, float | None, float | None, str | None, int | None]] = []

    def flush() -> None:
        nonlocal active_rows
        if not active_label:
            return
        result.extend(
            ChartTerminalLeg(active_label, active_runway, leg_type, fix_ident, raw, active_kind, course, altitude, turn, speed)
            for leg_type, fix_ident, raw, course, altitude, turn, speed in active_rows
        )
        active_rows = []

    lines = [raw_line.strip() for raw_line in text.splitlines()]
    for line_number, line in enumerate(lines):
        heading = _DATABASE_PROCEDURE.search(line)
        if heading:
            flush()
            active_label = heading["label"]
            active_runway = heading["runway"]
            active_kind = heading["kind"] or ""
            active_rows = pending_rows
            pending_rows = []
            continue
        leg = _DATABASE_LEG.match(line)
        if not leg:
            continue
        next_line = lines[line_number + 1] if line_number + 1 < len(lines) else ""
        fix_ident = leg["fix"] or (next_line if _COORDINATE_PAGE_IDENT.fullmatch(next_line) and next_line not in _IGNORED else None)
        row = (leg["leg_type"], fix_ident, line if leg["fix"] else f"{line} {next_line}".rstrip())
        course, altitude, turn, speed = _database_leg_attributes(lines, line_number, leg["leg_type"], fix_ident)
        row = (*row, course, altitude, turn, speed)
        if leg["leg_type"] in {"CF", "CA"} and active_rows and active_rows[-1][0] != "CA":
            pending_rows.append(row)
        elif active_label:
            active_rows.append(row)
        else:
            pending_rows.append(row)
    flush()
    return tuple(result)


def extract_chart(pdf: Path, airport: str, chart_type: str = "", chart_name: str = "") -> list[ProcedureChart]:
    """Extract text from every page and retain labels with reproducible hashes."""
    reader = PdfReader(pdf)
    result: list[ProcedureChart] = []
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        coordinate_text = page.extract_text() or ""
        result.append(_chart_from_text(pdf, airport, chart_type, chart_name, page_number, text, file_hash, coordinate_text))
    return result


def _chart_to_payload(chart: ProcedureChart) -> dict[str, object]:
    return {
        "airport": chart.airport,
        "filename": chart.filename,
        "page": chart.page,
        "chart_type": chart.chart_type,
        "chart_name": chart.chart_name,
        "text_sha256": chart.text_sha256,
        "procedure_labels": list(chart.procedure_labels),
        "runways": list(chart.runways),
        "waypoints": list(chart.waypoints),
        "terminal_legs": [leg.__dict__ for leg in chart.terminal_legs],
        "fix_coordinates": [point.__dict__ for point in chart.fix_coordinates],
        "source": chart.source.__dict__,
        "route_fixes": [fix.__dict__ for fix in chart.route_fixes],
    }


def _chart_from_payload(payload: dict[str, object]) -> ProcedureChart:
    return ProcedureChart(
        airport=str(payload["airport"]), filename=str(payload["filename"]), page=int(payload["page"]),
        chart_type=str(payload["chart_type"]), chart_name=str(payload["chart_name"]),
        text_sha256=str(payload["text_sha256"]), procedure_labels=tuple(payload["procedure_labels"]),
        runways=tuple(payload["runways"]), waypoints=tuple(payload["waypoints"]),
        terminal_legs=tuple(ChartTerminalLeg(**item) for item in payload["terminal_legs"]),
        fix_coordinates=tuple(ChartFixCoordinate(**item) for item in payload["fix_coordinates"]),
        source=SourceRef(**payload["source"]),
        route_fixes=tuple(ChartRouteFix(**item) for item in payload.get("route_fixes", [])),
    )


def _cached_extract(
    pdf: Path, airport: str, chart_type: str, chart_name: str, cache_dir: Path | None,
    extractor: Callable[[Path, str, str, str], list[ProcedureChart]],
) -> list[ProcedureChart]:
    """Cache exact chart evidence outside the immutable NAIP source tree."""
    if cache_dir is None:
        return extractor(pdf, airport, chart_type, chart_name)
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    key_material = json.dumps({
        "version": _EVIDENCE_CACHE_VERSION, "pdf_sha256": file_hash, "airport": airport,
        "chart_type": chart_type, "chart_name": chart_name, "extractor": extractor.__name__,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    cache_file = cache_dir / f"{hashlib.sha256(key_material.encode('utf-8')).hexdigest()}.json"
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        if payload["key"] == key_material:
            return [_chart_from_payload(item) for item in payload["charts"]]
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        pass
    charts = extractor(pdf, airport, chart_type, chart_name)
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_suffix(".tmp")
    temporary.write_text(json.dumps({"key": key_material, "charts": [_chart_to_payload(chart) for chart in charts]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temporary.replace(cache_file)
    return charts


def _chart_from_text(pdf: Path, airport: str, chart_type: str, chart_name: str, page_number: int, text: str, file_hash: str, coordinate_text: str | None = None) -> ProcedureChart:
    labels = tuple(sorted(set(_PROCEDURE.findall(text))))
    runways = _extract_runways(f"{chart_name}\n{text}")
    waypoints = tuple(sorted({token for token in _WAYPOINT.findall(text) if token not in _IGNORED and not token.isdigit()}))
    coordinates = extract_coordinate_page_points(text) or extract_coordinate_page_points(coordinate_text or "")
    return ProcedureChart(
        airport=airport,
        filename=pdf.name,
        page=page_number,
        chart_type=chart_type,
        chart_name=chart_name,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        procedure_labels=labels,
        runways=runways,
        waypoints=waypoints,
        terminal_legs=extract_terminal_leg_evidence(text),
        fix_coordinates=extract_fix_coordinates(text) + coordinates,
        source=SourceRef(str(pdf), page_number, page_number, file_hash),
    )


def extract_airport_charts(airport_directory: Path) -> list[ProcedureChart]:
    """Resolve PDF names from the per-airport chart index and extract procedures."""
    index = airport_directory / "Charts.csv"
    if not index.is_file():
        raise FileNotFoundError(f"missing chart index: {index}")
    rows = _chart_rows(index)
    charts: list[ProcedureChart] = []
    airport = airport_directory.resolve().name.upper()
    for row in rows:
        page = (row.get("PAGE_NUMBER") or "").strip()
        chart_type = (row.get("ChartTypeEx_CH") or "").strip()
        chart_name = (row.get("ChartName") or "").strip()
        # Page numbers are the stable cross-encoding contract.  Classifying the
        # chart happens from extracted labels rather than locale-dependent text.
        if not page:
            continue
        pdf = airport_directory / f"{airport}-{page}.pdf"
        if pdf.is_file():
            charts.extend(extract_chart(pdf, airport, chart_type, chart_name))
    return charts


def extract_airport_database_charts(airport_directory: Path, cache_dir: Path | None = None) -> list[ProcedureChart]:
    """Extract only index-declared database-coding pages with PyMuPDF.

    These pages carry printed procedure leg tables.  They are intentionally
    separated from coordinate pages so later waypoint selection can be based
    on observable procedure use rather than every point printed on a chart.
    """
    index = airport_directory / "Charts.csv"
    if not index.is_file():
        raise FileNotFoundError(f"missing chart index: {index}")
    airport = airport_directory.resolve().name.upper()
    charts: list[ProcedureChart] = []
    for row in _chart_rows(index):
        page = (row.get("PAGE_NUMBER") or "").strip()
        chart_name = (row.get("ChartName") or "").strip()
        if not page or "数据库编码" not in chart_name:
            continue
        pdf = airport_directory / f"{airport}-{page}.pdf"
        if pdf.is_file():
            charts.extend(_cached_extract(pdf, airport, "terminal-database-coding", chart_name, cache_dir, extract_database_chart))
    return charts


def _is_instrument_approach_index_row(row: dict[str, str]) -> bool:
    """Return whether a chart-index row is an instrument-approach chart.

    This classification deliberately relies on the publisher's chart index,
    not on text guessed from a rendered procedure plate.  Some 2608 indexes
    use an underscored chart-name category instead of the normal type label.
    """
    chart_type = (row.get("ChartTypeEx_CH") or "").strip()
    chart_name = (row.get("ChartName") or "").strip()
    return "\u4eea\u8868\u8fdb\u8fd1\u56fe" in chart_type or "\u8fdb\u8fd1\u56fe_" in chart_type or "\u8fdb\u8fd1\u56fe_" in chart_name


def extract_airport_approach_charts(airport_directory: Path, cache_dir: Path | None = None) -> list[ProcedureChart]:
    """Extract index-declared instrument approach pages as source evidence.

    These charts are intentionally not interpreted as Fenix terminal legs.
    They establish only that a source page is associated with an airport and
    printed runway, allowing the reference-comparison command to measure the
    currently unimplemented approach-procedure surface.
    """
    index = airport_directory / "Charts.csv"
    if not index.is_file():
        raise FileNotFoundError(f"missing chart index: {index}")
    airport = airport_directory.resolve().name.upper()
    charts: list[ProcedureChart] = []
    for row in _chart_rows(index):
        page = (row.get("PAGE_NUMBER") or "").strip()
        chart_name = (row.get("ChartName") or "").strip()
        if not page or not _is_instrument_approach_index_row(row):
            continue
        pdf = airport_directory / f"{airport}-{page}.pdf"
        if pdf.is_file():
            charts.extend(_cached_extract(pdf, airport, "instrument-approach-index", chart_name, cache_dir, extract_approach_chart))
    return charts


def _is_standard_procedure_index_row(row: dict[str, str]) -> bool:
    chart_type = (row.get("ChartTypeEx_CH") or "").strip()
    chart_name = (row.get("ChartName") or "").strip()
    if "\u6570\u636e\u5e93\u7f16\u7801" in chart_name or "\u822a\u8def\u70b9\u5750\u6807" in chart_name:
        return False
    return "\u6807\u51c6\u4eea\u8868\u79bb\u573a\u56fe" in chart_type or "\u6807\u51c6\u4eea\u8868\u8fdb\u573a\u56fe" in chart_type


def extract_airport_standard_procedure_charts(airport_directory: Path, cache_dir: Path | None = None) -> list[ProcedureChart]:
    """Extract index-declared SID/STAR pages as waypoint-label evidence."""
    index = airport_directory / "Charts.csv"
    if not index.is_file():
        raise FileNotFoundError(f"missing chart index: {index}")
    airport = airport_directory.resolve().name.upper()
    charts: list[ProcedureChart] = []
    for row in _chart_rows(index):
        page = (row.get("PAGE_NUMBER") or "").strip()
        chart_name = (row.get("ChartName") or "").strip()
        if not page or not _is_standard_procedure_index_row(row):
            continue
        pdf = airport_directory / f"{airport}-{page}.pdf"
        if pdf.is_file():
            charts.extend(_cached_extract(pdf, airport, "standard-terminal-procedure", chart_name, cache_dir, extract_approach_chart))
    return charts


def _chart_rows(index: Path) -> list[dict[str, str]]:
    raw = index.read_bytes()
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return list(csv.DictReader(raw.decode(encoding).splitlines()))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"unsupported chart-index encoding: {index}")  # pragma: no cover


def extract_airport_coordinate_pages(airport_directory: Path, cache_dir: Path | None = None) -> list[ProcedureChart]:
    """Extract only index-declared terminal waypoint coordinate pages."""
    index = airport_directory / "Charts.csv"
    if not index.is_file():
        raise FileNotFoundError(f"missing chart index: {index}")
    airport = airport_directory.resolve().name.upper()
    charts: list[ProcedureChart] = []
    for row in _chart_rows(index):
        page = (row.get("PAGE_NUMBER") or "").strip()
        chart_name = (row.get("ChartName") or "").strip()
        if not page or "航路点坐标" not in chart_name:
            continue
        pdf = airport_directory / f"{airport}-{page}.pdf"
        if pdf.is_file():
            charts.extend(_cached_extract(pdf, airport, "terminal-coordinate-page", chart_name, cache_dir, extract_coordinate_chart))
    return charts


def extract_coordinate_chart(pdf: Path, airport: str, chart_type: str, chart_name: str) -> list[ProcedureChart]:
    """Use PyMuPDF's fast plain-text order for terminal coordinate pages."""
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    result: list[ProcedureChart] = []
    with pymupdf.open(pdf) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text()
            chart = _chart_from_text(pdf, airport, chart_type, chart_name, page_number, text, file_hash)
            positioned = extract_positioned_coordinate_page_points(page.get_text("words"))
            result.append(replace(chart, fix_coordinates=positioned or chart.fix_coordinates))
    return result


def extract_database_chart(pdf: Path, airport: str, chart_type: str, chart_name: str) -> list[ProcedureChart]:
    """Use fast text extraction for database-coding procedure tables."""
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    result: list[ProcedureChart] = []
    with pymupdf.open(pdf) as document:
        for page_number, page in enumerate(document, start=1):
            result.append(_chart_from_text(pdf, airport, chart_type, chart_name, page_number, page.get_text(), file_hash))
    return result


def extract_approach_chart(pdf: Path, airport: str, chart_type: str, chart_name: str) -> list[ProcedureChart]:
    """Extract text-layer and role-labelled fix evidence from a procedure plate."""
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    result: list[ProcedureChart] = []
    with pymupdf.open(pdf) as document:
        for page_number, page in enumerate(document, start=1):
            chart = _chart_from_text(pdf, airport, chart_type, chart_name, page_number, page.get_text(), file_hash)
            result.append(replace(chart, route_fixes=extract_positioned_route_fixes(page.get_text("words"))))
    return result
