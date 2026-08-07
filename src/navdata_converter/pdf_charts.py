"""Evidence-preserving extraction of terminal-chart PDF text layers.

This module deliberately does not invent ARINC leg semantics from geometry.  It
returns observable labels and fix identifiers so the Fenix adapter can reject a
chart until an explicit mapping is implemented and tested.
"""

from __future__ import annotations

import hashlib
import re
import csv
from dataclasses import replace
from pathlib import Path

import pymupdf
from pypdf import PdfReader

from .model import ChartFixCoordinate, ChartTerminalLeg, ProcedureChart, SourceRef


_PROCEDURE = re.compile(r"\b([A-Z0-9]{2,6}-\d{2}[AD])\b")
_RUNWAY = re.compile(r"\bRWY\s?(\d{2}[LRC]?)\b")
_WAYPOINT = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\b")
_IGNORED = {"CAAC", "ALL", "RIGHTS", "RESER", "MSA", "RNP", "ILS", "DME", "RWY", "ATC", "N", "E", "S", "W"}
_CHART_COORDINATE = re.compile(
    r"\bN\s*(?P<lat_deg>\d{2})\s*(?:[°º]|D)?\s*(?P<lat_min>\d{2}(?:\.\d+)?)\s*(?:['′])?"
    r"\s*[,/ ]*E\s*(?P<lon_deg>\d{3})\s*(?:[°º]|D)?\s*(?P<lon_min>\d{2}(?:\.\d+)?)\s*(?:['′])?\b",
    re.IGNORECASE,
)
_DATABASE_PROCEDURE = re.compile(r"\bRWY\s?(?P<runway>\d{2}[LRC]?)\s*[^\n]*?(?P<label>[A-Z0-9]{1,6}-\d{1,2}[A-Z]{1,2})(?:\b|\()")
_DATABASE_LEG = re.compile(r"^(?P<leg_type>CF|DF|TF|CA|IF|HM|RF|AF|FA|FC|FD|FM|HA|HF|PI|VI|VM)\b(?:\s+(?P<fix>[A-Z][A-Z0-9]{0,5}))?")
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


def extract_terminal_leg_evidence(text: str) -> tuple[ChartTerminalLeg, ...]:
    """Extract ordered database-chart rows without inferring ARINC semantics.

    PDF table reading order places a leading CF/CA row immediately before its
    procedure heading.  It is attached only when the next observable heading
    confirms that association; all remaining rows retain their literal text.
    """
    result: list[ChartTerminalLeg] = []
    active_label = ""
    active_runway = ""
    active_rows: list[tuple[str, str | None, str]] = []
    pending_rows: list[tuple[str, str | None, str]] = []

    def flush() -> None:
        nonlocal active_rows
        if not active_label:
            return
        result.extend(
            ChartTerminalLeg(active_label, active_runway, leg_type, fix_ident, raw)
            for leg_type, fix_ident, raw in active_rows
        )
        active_rows = []

    lines = [raw_line.strip() for raw_line in text.splitlines()]
    for line_number, line in enumerate(lines):
        heading = _DATABASE_PROCEDURE.search(line)
        if heading:
            flush()
            active_label = heading["label"]
            active_runway = heading["runway"]
            active_rows = pending_rows
            pending_rows = []
            continue
        leg = _DATABASE_LEG.match(line)
        if not leg:
            continue
        next_line = lines[line_number + 1] if line_number + 1 < len(lines) else ""
        fix_ident = leg["fix"] or (next_line if _COORDINATE_PAGE_IDENT.fullmatch(next_line) and next_line not in _IGNORED else None)
        row = (leg["leg_type"], fix_ident, line if leg["fix"] else f"{line} {next_line}".rstrip())
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


def _chart_from_text(pdf: Path, airport: str, chart_type: str, chart_name: str, page_number: int, text: str, file_hash: str, coordinate_text: str | None = None) -> ProcedureChart:
    labels = tuple(sorted(set(_PROCEDURE.findall(text))))
    runways = tuple(sorted(set(_RUNWAY.findall(f"{chart_name}\n{text}"))))
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


def extract_airport_database_charts(airport_directory: Path) -> list[ProcedureChart]:
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
            charts.extend(extract_database_chart(pdf, airport, "terminal-database-coding", chart_name))
    return charts


def _chart_rows(index: Path) -> list[dict[str, str]]:
    raw = index.read_bytes()
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return list(csv.DictReader(raw.decode(encoding).splitlines()))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"unsupported chart-index encoding: {index}")  # pragma: no cover


def extract_airport_coordinate_pages(airport_directory: Path) -> list[ProcedureChart]:
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
            charts.extend(extract_coordinate_chart(pdf, airport, "terminal-coordinate-page", chart_name))
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
