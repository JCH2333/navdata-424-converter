"""Evidence-preserving extraction of terminal-chart PDF text layers.

This module deliberately does not invent ARINC leg semantics from geometry.  It
returns observable labels and fix identifiers so the Fenix adapter can reject a
chart until an explicit mapping is implemented and tested.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import csv
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pymupdf
from pypdf import PdfReader

from .model import ChartFixCoordinate, ChartRouteFix, ChartStandardProcedureRoute, ChartTerminalLeg, Ils, ProcedureChart, SourceRef


_EVIDENCE_CACHE_VERSION = 25


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
_DATABASE_PROCEDURE = re.compile(
    r"\bRWY\s?(?P<runway>\d{2}[LRC]?)(?:\s*/\s*(?:RWY\s?)?\d{2}[LRC]?)*\s*"
    r"(?:(?P<kind>\u79bb\u573a|\u8fdb\u573a|\u7b49\u5f85)\s*|)[^\n]*?"
    r"(?P<label_base>[A-Z0-9]{1,6}?)-?(?P<label_suffix>\d{1,2}[A-Z]{1,2})(?:\b|\()"
)
_DATABASE_COMPOUND_PROCEDURE = re.compile(
    r"\bRWY\s?(?P<runway>\d{2}[LRC]?)\s*(?P<kind>\u79bb\u573a|\u8fdb\u573a)\s*"
    r"(?P<stem>[A-Z][A-Z0-9]{2,5})-(?:[A-Z]{0,2})(?P<serial>\d{3})(?:\b|\()"
)
_DATABASE_NUMERIC_PROCEDURE = re.compile(
    r"\bRWY\s?(?P<runway>\d{2}[LRC]?)(?:\s*/\s*(?:RWY\s?)?\d{2}[LRC]?)*\s*"
    r"(?:(?P<kind>\u79bb\u573a|\u8fdb\u573a|\u7b49\u5f85)\s*|)[^\n]*?"
    r"(?P<label_base>[A-Z][A-Z0-9]{0,5}?)(?P<label_suffix>\d{2})(?:\b|\()"
)
_DATABASE_APPROACH_PROCEDURE = re.compile(
    r"\bRWY\s?(?P<runway>\d{2}[LRC]?)\s*(?P<kind>\u8fdb\u8fd1\u8fc7\u6e21|\u8fdb\u8fd1\u53ca\u590d\u98de|\u8fdb\u8fd1|\u590d\u98de)"
    r"(?:\s*-?\s*(?P<variant>[WXYZ]))?"
    r"(?:\s+(?P<transition>[A-Z][A-Z0-9]{0,5})|\s*VIA\s*(?P<via_transition>[A-Z][A-Z0-9]{0,5}))?\b", re.IGNORECASE
)
_DATABASE_LEG = re.compile(r"\b(?P<leg_type>CF|DF|TF|CA|IF|HM|RF|AF|FA|FC|FD|FM|HA|HF|PI|VI|VM)\b(?:\s+(?P<fix>[A-Z][A-Z0-9]{0,5}))?")
_DATABASE_RF_LEG = re.compile(r"\bRF\s*\[\s*(?P<center>[A-Z][A-Z0-9]{0,5})\s*,\s*\d+(?:\.\d+)?\s*\]\s*(?P<fix>[A-Z][A-Z0-9]{0,5})?")
_DATABASE_SPEED = re.compile(r"^MAX(?P<speed>\d{2,3})$", re.IGNORECASE)
_STANDARD_ROUTE = re.compile(
    r"\b(?P<label>[A-Z][A-Z0-9]{1,5}-(?:\d{1,2}[A-Z]{1,2}|[A-Z]{1,2}\d{1,2}))\s+"
    r"(?P<code>[A-Z][A-Z0-9]{2,5})\s+"
    r"(?P<route>[A-Z][A-Z0-9]{1,5}(?:-[A-Z][A-Z0-9]{1,5})+)\b"
)
_COORDINATE_PAGE_IDENT = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")
_DMS_COORDINATE = re.compile(
    r"N\s*(?P<lat_deg>\d{2})\D+?(?P<lat_min>\d{2})\D+?(?P<lat_sec>\d{2}(?:\.\d+)?)[\"']?\s*"
    r"E\s*(?P<lon_deg>\d{2,3})\D+?(?P<lon_min>\d{2})\D+?(?P<lon_sec>\d{2}(?:\.\d+)?)[\"']?",
    re.IGNORECASE,
)
_DM_COORDINATE = re.compile(
    r"N\s*(?P<lat_deg>\d{2})\D+?(?P<lat_min>\d{2}(?:\.\d+)?)[\"']\s*"
    r"E\s*(?P<lon_deg>\d{2,3})\D+?(?P<lon_min>\d{2}(?:\.\d+)?)[\"']?\b",
    re.IGNORECASE,
)
_AIP_DMS_COORDINATE = re.compile(
    r"N\s*(?P<lat>\d{6}(?:\.\d+)?)\s*E\s*(?P<lon>\d{7}(?:\.\d+)?)",
    re.IGNORECASE,
)
_AIP_LOC = re.compile(
    r"\bLOC\s*(?P<runway>\d{2}[LRC]?)\s+(?:ILS\s*)?(?:CAT\s*(?P<category>I{1,3})\s+)?"
    r"(?P<ident>[A-Z0-9]{2,5})\s+(?P<frequency>\d{3}\.\d{1,3})\s*MHz\s*"
    r"(?P<coordinate>N\s*\d{6}(?:\.\d+)?\s*E\s*\d{7}(?:\.\d+)?)",
    re.IGNORECASE | re.DOTALL,
)
_AIP_SPLIT_LOC = re.compile(
    r"\bLOC\s*(?P<runway>\d{2}[LRC]?)\s+(?P<ident>[A-Z0-9]{2,5})\s+"
    r"(?P<frequency>\d{3}\.\d{1,3})\s*MHz\s*(?P<latitude>N\s*\d{6}(?:\.\d+)?)"
    r".{0,960}?ILS\s*CAT\s*(?P<category>I{1,3})\s*(?P<longitude>E\s*\d{7}(?:\.\d+)?)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_aip_dms_coordinate(value: str) -> tuple[float, float]:
    match = _AIP_DMS_COORDINATE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"invalid AD 2.19 coordinate: {value!r}")

    def convert(digits: str, degree_digits: int) -> float:
        degrees = int(digits[:degree_digits])
        minutes = int(digits[degree_digits:degree_digits + 2])
        seconds = float(digits[degree_digits + 2:])
        if minutes >= 60 or seconds >= 60:
            raise ValueError(f"invalid AD 2.19 coordinate: {value!r}")
        return degrees + minutes / 60 + seconds / 3600

    return convert(match["lat"], 2), convert(match["lon"], 3)


def extract_ad219_ils(text: str, airport: str, source: SourceRef) -> tuple[Ils, ...]:
    """Extract only explicitly printed AD 2.19 LOC/GP/DME facts."""
    result: list[Ils] = []
    matches = sorted(
        (*_AIP_LOC.finditer(text), *_AIP_SPLIT_LOC.finditer(text)),
        key=lambda item: (item.start(), item.end()),
    )
    seen: set[tuple[str, str, str, float, float]] = set()
    for localizer in matches:
        coordinate = localizer.groupdict().get("coordinate") or f"{localizer['latitude']} {localizer['longitude']}"
        localizer_latitude, localizer_longitude = _parse_aip_dms_coordinate(coordinate)
        tail = text[localizer.end():localizer.end() + 220]
        course_match = re.search(r"(?P<course>\d{3})\s*[°º]\s*MAG", tail, re.IGNORECASE)
        runway = localizer["runway"].upper()
        ident = localizer["ident"].upper()
        identity = (runway, ident, localizer["frequency"], localizer_latitude, localizer_longitude)
        if identity in seen:
            continue
        seen.add(identity)
        # Start GP/DME matching immediately after the localizer.  The LOC
        # pattern itself intentionally consumes no look-ahead text, so a
        # densely printed first ILS cannot hide the following localizer.
        remainder = text[localizer.end():]
        dme = re.search(
            rf"\bDME\s*{re.escape(runway)}\s+{re.escape(ident)}\b.{{0,180}}?"
            r"(?P<coordinate>N\s*\d{6}(?:\.\d+)?\s*E\s*\d{7}(?:\.\d+)?)(?P<tail>.{0,120})",
            remainder, re.IGNORECASE | re.DOTALL,
        )
        glide_path = re.search(
            rf"\bGP\s*{re.escape(runway)}\b.{{0,180}}?"
            r"(?P<coordinate>N\s*\d{6}(?:\.\d+)?\s*E\s*\d{7}(?:\.\d+)?)(?P<tail>.{0,180})",
            remainder, re.IGNORECASE | re.DOTALL,
        )
        dme_latitude = dme_longitude = dme_elevation = None
        if dme is not None:
            dme_latitude, dme_longitude = _parse_aip_dms_coordinate(dme["coordinate"])
            elevation_match = re.search(
                r"(?P<elevation>\d+(?:\.\d+)?)\s*m\s*(?:与|同).{0,16}(?:GP|下滑)",
                dme["tail"], re.IGNORECASE,
            )
            if elevation_match is None:
                elevations = list(re.finditer(r"(?P<elevation>\d+(?:\.\d+)?)\s*m\b", dme["tail"], re.IGNORECASE))
                elevation_match = elevations[-1] if elevations else None
            dme_elevation = float(elevation_match["elevation"]) if elevation_match else None
        glide_latitude = glide_longitude = glide_angle = crossing_height = None
        if glide_path is not None:
            glide_latitude, glide_longitude = _parse_aip_dms_coordinate(glide_path["coordinate"])
            angle_match = re.search(r"(?P<angle>\d(?:\.\d+)?)\s*[°º]\s*(?:下滑角|GP)", glide_path["tail"], re.IGNORECASE)
            glide_angle = float(angle_match["angle"]) if angle_match else None
            height_match = re.search(r"RDH\s*(?P<height>\d+(?:\.\d+)?)\s*m?\b", glide_path["tail"], re.IGNORECASE)
            crossing_height = float(height_match["height"]) if height_match else None
        result.append(Ils(
            airport=airport.upper(), runway=runway, ident=ident, frequency_mhz=float(localizer["frequency"]),
            category=localizer["category"], localizer_latitude=localizer_latitude,
            localizer_longitude=localizer_longitude,
            localizer_course_magnetic=float(course_match["course"]) if course_match else None,
            glide_slope_degrees=glide_angle, crossing_height_meters=crossing_height,
            glide_slope_latitude=glide_latitude,
            glide_slope_longitude=glide_longitude, dme_latitude=dme_latitude,
            dme_longitude=dme_longitude, dme_elevation_meters=dme_elevation, source=source,
        ))
    return tuple(result)


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


def _database_heading_runways(heading: str) -> tuple[str, ...]:
    """Keep every runway explicitly printed in one database-table heading."""
    return tuple(dict.fromkeys(re.findall(r"(?:\bRWY\s*|/)\s*(\d{2}[LRC]?)", heading)))


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


def _positioned_database_text(words: list[tuple[float, float, float, float, str, int, int, int]]) -> str:
    """Rebuild database-table rows from rendered text-object positions.

    Some plates contain several procedure tables and rotated copyright text.
    Their PDF object order can interleave adjacent table rows, even when each
    cell's rendered baseline is intact. Group only objects on the same
    baseline, then order them left-to-right.
    """
    rows: list[list[tuple[float, float, str]]] = []
    for x0, y0, _, _, raw_text, *_ in sorted(words, key=lambda word: (word[1], word[0])):
        text = raw_text.strip()
        if not text:
            continue
        if rows and abs(rows[-1][0][1] - y0) <= 2.5:
            rows[-1].append((x0, y0, text))
        else:
            rows.append([(x0, y0, text)])
    return "\n".join(" ".join(text for _, _, text in sorted(row)) for row in rows)


def _standard_procedure_routes(text: str) -> tuple[ChartStandardProcedureRoute, ...]:
    """Read only fully printed route-table entries from a standard SID/STAR plate."""
    routes = []
    for match in _STANDARD_ROUTE.finditer(text.upper()):
        fixes = tuple(match["route"].split("-"))
        version = match["label"].rsplit("-", 1)[1]
        # The navigation-data code retains the printed version suffix.  Without
        # it, adjacent performance-table text can mimic the three columns.
        if len(fixes) >= 2 and fixes[0] == match["label"].split("-", 1)[0] and match["code"].endswith(version):
            routes.append(ChartStandardProcedureRoute(match["label"], match["code"], fixes))
    return tuple(dict.fromkeys(routes))


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


def _point_xy(point: object) -> tuple[float, float]:
    return float(getattr(point, "x", point[0])), float(getattr(point, "y", point[1]))  # type: ignore[index]


def _segment_distance(x: float, y: float, start: object, end: object) -> float:
    x1, y1 = _point_xy(start)
    x2, y2 = _point_xy(end)
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    fraction = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_squared))
    return ((x - (x1 + fraction * dx)) ** 2 + (y - (y1 + fraction * dy)) ** 2) ** 0.5


def extract_vector_route_fixes(words: list[tuple[float, float, float, float, str, int, int, int]], drawings: list[dict[str, object]]) -> tuple[ChartRouteFix, ...]:
    """Retain identifiers printed next to a black vector procedure path.

    The test is deliberately geometric: a candidate must be close to an actual
    stroke segment, not merely inside a drawing's bounding rectangle. It is
    evidence for later plan decoding and never establishes leg order by itself.
    """
    cell_size = 24.0
    cells: dict[tuple[int, int], list[tuple[object, object]]] = {}

    def index_segment(start: object, end: object) -> None:
        x1, y1 = _point_xy(start)
        x2, y2 = _point_xy(end)
        # Long strokes are chart borders, map outlines or tables. Procedure
        # paths are emitted as short vector pieces around their labelled fixes.
        if max(abs(x2 - x1), abs(y2 - y1)) > 96:
            return
        for cell_x in range(int(min(x1, x2) // cell_size), int(max(x1, x2) // cell_size) + 1):
            for cell_y in range(int(min(y1, y2) // cell_size), int(max(y1, y2) // cell_size) + 1):
                cells.setdefault((cell_x, cell_y), []).append((start, end))

    for drawing in drawings:
        drawing_type = drawing.get("type")
        # Standard procedure plates encode their route strokes as either a
        # conventional black stroke or a black filled path.  The latter keeps
        # the same line items in PyMuPDF, while its colour lives in ``fill``.
        # Do not accept other filled artwork: it has no route meaning.
        is_black_stroke = drawing_type == "s" and drawing.get("color") == (0.0, 0.0, 0.0)
        is_black_fill = drawing_type == "f" and drawing.get("fill") == (0.0, 0.0, 0.0)
        if not (is_black_stroke or is_black_fill):
            continue
        if is_black_stroke and not 0.2 <= float(drawing.get("width") or 0.0) <= 1.0:
            continue
        items = drawing.get("items", [])
        if len(items) > 96:
            continue
        for item in items:
            if item[0] == "l":
                index_segment(item[1], item[2])
            elif item[0] == "c":
                for start, end in zip(item[1:], item[2:]):
                    index_segment(start, end)
    result = []
    for x0, y0, x1, y1, raw_identifier, *_ in words:
        identifier = raw_identifier.upper()
        if (
            not _COORDINATE_PAGE_IDENT.fullmatch(identifier)
            or not any(character.isdigit() for character in identifier)
            or identifier.startswith(("RWY", "VAR"))
            or identifier in _IGNORED
            or identifier in _ROUTE_ROLE
        ):
            continue
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        cell_x, cell_y = int(center_x // cell_size), int(center_y // cell_size)
        nearby_segments = [
            segment
            for x_offset in (-1, 0, 1)
            for y_offset in (-1, 0, 1)
            for segment in cells.get((cell_x + x_offset, cell_y + y_offset), [])
        ]
        if any(_segment_distance(center_x, center_y, start, end) <= 8 for start, end in nearby_segments):
            result.append(ChartRouteFix(identifier, "VECTOR"))
    return tuple(dict.fromkeys(result))


def _database_leg_attributes(lines: list[str], start: int, leg_type: str, fix_ident: str | None) -> tuple[float | None, float | None, str | None, int | None]:
    """Read observable numeric fields from one database-coding table row."""
    values: list[str] = []
    for line in lines[start + 1:]:
        if _DATABASE_LEG.search(line) or _DATABASE_PROCEDURE.search(line):
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
    elif leg_type in {"HF", "HM"}:
        inline_values = lines[start].replace(",", " ").split()
        inline_turn = next((value for value in inline_values if value in {"L", "R"}), None)
        inline_speed_match = re.search(r"\bMAX(\d{2,3})\b", lines[start], re.IGNORECASE)
        inline_numeric = [float(value) for value in inline_values if value.isdecimal()]
        course = inline_numeric[0] if inline_numeric else None
        altitude = inline_numeric[1] if len(inline_numeric) > 1 else (numeric[0] if numeric else None)
        # Some holding-table altitude cells have a baseline a few points above
        # their leg cell, so position sorting emits the value just before HF/HM.
        if altitude is None and start and lines[start - 1].isdecimal():
            altitude = float(lines[start - 1])
        turn_direction = turn_direction or inline_turn
        speed = speed or (int(inline_speed_match.group(1)) if inline_speed_match else None)
    return course, altitude, turn_direction, speed


def extract_terminal_leg_evidence(text: str) -> tuple[ChartTerminalLeg, ...]:
    """Extract ordered database-chart rows without inferring ARINC semantics.

    PDF table reading order places a leading CF/CA row immediately before its
    procedure heading.  It is attached only when the next observable heading
    confirms that association; all remaining rows retain their literal text.
    """
    result: list[ChartTerminalLeg] = []
    active_label = ""
    active_runways: tuple[str, ...] = ()
    active_kind = ""
    active_transition = ""
    split_combined_approach_missed = False
    active_rows: list[tuple[str, str | None, str, float | None, float | None, str | None, int | None, str | None]] = []
    pending_rows: list[tuple[str, str | None, str, float | None, float | None, str | None, int | None, str | None]] = []

    def flush() -> None:
        nonlocal active_rows
        if not active_label:
            return
        result.extend(
            ChartTerminalLeg(active_label, runway, leg_type, fix_ident, raw, active_kind, course, altitude, turn, speed, active_transition, center_ident)
            for runway in active_runways
            for leg_type, fix_ident, raw, course, altitude, turn, speed, center_ident in active_rows
        )
        active_rows = []

    lines = [raw_line.strip() for raw_line in text.splitlines()]
    for line_number, line in enumerate(lines):
        compound_heading = _DATABASE_COMPOUND_PROCEDURE.search(line)
        heading = compound_heading or _DATABASE_PROCEDURE.search(line) or _DATABASE_NUMERIC_PROCEDURE.search(line)
        approach_heading = _DATABASE_APPROACH_PROCEDURE.search(line)
        if heading or approach_heading:
            flush()
            if approach_heading:
                variant = (approach_heading["variant"] or "").upper()
                active_label = f"R{approach_heading['runway']}{f'-{variant}' if variant else ''}"
                active_runways = (approach_heading["runway"],)
                split_combined_approach_missed = approach_heading["kind"] == "\u8fdb\u8fd1\u53ca\u590d\u98de"
                active_kind = "\u8fdb\u8fd1" if split_combined_approach_missed else approach_heading["kind"]
                active_transition = approach_heading["transition"] or approach_heading["via_transition"] or ""
                # Approach pages can begin with a hold continuation, which is
                # not attributable to the next approach transition.
                active_rows = []
            else:
                # Some CAAC database pages print procedure names as IDKE5Y
                # while others use IDKE-5Y.  Both expose the same base and
                # suffix columns, so normalize the observable typography here.
                if compound_heading:
                    stem = compound_heading["stem"]
                    base = f"R{stem[-2:]}" if re.fullmatch(r"RNV\d{2}", stem) else stem[:3]
                    active_label = f"{base}-{compound_heading['serial']}"
                else:
                    active_label = f"{heading['label_base']}-{heading['label_suffix']}"
                active_runways = _database_heading_runways(heading.group(0))
                active_kind = heading["kind"] or ""
                active_transition = ""
                active_rows = pending_rows
                split_combined_approach_missed = False
            pending_rows = []
            continue
        rf_legs = list(_DATABASE_RF_LEG.finditer(line))
        if len(rf_legs) > 1:
            for index, rf_leg in enumerate(rf_legs):
                end = rf_legs[index + 1].start() if index + 1 < len(rf_legs) else len(line)
                fragment = line[rf_leg.start():end]
                tokens = fragment.replace(",", " ").split()
                turn = next((token for token in tokens if token in {"L", "R"}), None)
                speed_match = re.search(r"\bMAX(\d{2,3})\b", fragment, re.IGNORECASE)
                row = ("RF", rf_leg["fix"], fragment, None, None, turn,
                       int(speed_match.group(1)) if speed_match else None, rf_leg["center"])
                if active_label:
                    active_rows.append(row)
                else:
                    pending_rows.append(row)
            continue
        rf_leg = _DATABASE_RF_LEG.search(line)
        leg = rf_leg or _DATABASE_LEG.search(line)
        if not leg:
            continue
        next_line = lines[line_number + 1] if line_number + 1 < len(lines) else ""
        leg_type = "RF" if rf_leg else leg["leg_type"]
        fix_ident = leg["fix"] or (next_line if _COORDINATE_PAGE_IDENT.fullmatch(next_line) and next_line not in _IGNORED else None)
        if split_combined_approach_missed and active_rows and leg_type in {"CA", "CF", "DF"}:
            # CAAC combines these two labelled phases under one title.  The
            # first course/direct leg after the printed approach rows starts
            # the following explicitly named missed-approach portion.
            flush()
            active_kind = "\u590d\u98de"
            active_transition = ""
            split_combined_approach_missed = False
        row = (leg_type, fix_ident, line if leg["fix"] else f"{line} {next_line}".rstrip())
        course, altitude, turn, speed = _database_leg_attributes(lines, line_number, leg_type, fix_ident)
        if rf_leg:
            tokens = line.replace(",", " ").split()
            turn = turn or next((token for token in tokens if token in {"L", "R"}), None)
            speed_match = re.search(r"\bMAX(\d{2,3})\b", line, re.IGNORECASE)
            speed = speed or (int(speed_match.group(1)) if speed_match else None)
        row = (*row, course, altitude, turn, speed, rf_leg["center"] if rf_leg else None)
        if (leg_type in {"CF", "CA"} and active_rows and active_rows[-1][0] != "CA"
                and not active_label.startswith("R")):
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
        "standard_routes": [route.__dict__ for route in chart.standard_routes],
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
        standard_routes=tuple(
            ChartStandardProcedureRoute(str(item["procedure_label"]), str(item["navigation_code"]), tuple(item["fixes"]))
            for item in payload.get("standard_routes", [])
        ),
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
    # Multiple diagnostics may warm the same local cache concurrently.  A
    # process-specific temporary file keeps one writer from deleting another
    # writer's pending payload before its atomic replacement.
    temporary = cache_file.with_suffix(f".{os.getpid()}.tmp")
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


def extract_airport_ad219_ils(airport_directory: Path) -> list[Ils]:
    """Read unindexed airport AD 2.19 landing-aid pages from PDF text layers."""
    airport = airport_directory.resolve().name.upper()
    index = airport_directory / "Charts.csv"
    indexed = {
        f"{airport}-{(row.get('PAGE_NUMBER') or '').strip()}.pdf".lower()
        for row in _chart_rows(index)
        if (row.get("PAGE_NUMBER") or "").strip()
    } if index.is_file() else set()
    result: list[Ils] = []
    for pdf in sorted(airport_directory.glob("*.pdf")):
        if pdf.name.lower() in indexed:
            continue
        file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
        with pymupdf.open(pdf) as document:
            in_ad219 = False
            start_page: int | None = None
            active_text: list[str] = []
            for page_number, page in enumerate(document, start=1):
                text = page.get_text()
                if "AD 2.19" in text or "无线电导航和着陆设施" in text:
                    if not in_ad219:
                        start_page = page_number
                        active_text.clear()
                    in_ad219 = True
                if not in_ad219:
                    continue
                terminators = [position for marker in ("AD 2.20", "本场规定") if (position := text.find(marker)) >= 0]
                ad219_text = text[:min(terminators)] if terminators else text
                active_text.append(ad219_text)
                if terminators:
                    result.extend(extract_ad219_ils(
                        "\n".join(active_text), airport,
                        SourceRef(str(pdf), start_page, start_page, file_hash),
                    ))
                    in_ad219 = False
                    start_page = None
                    active_text.clear()
            if in_ad219 and active_text:
                result.extend(extract_ad219_ils(
                    "\n".join(active_text), airport,
                    SourceRef(str(pdf), start_page, start_page, file_hash),
                ))
    return result


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


def extract_airport_standard_procedure_charts(
    airport_directory: Path,
    cache_dir: Path | None = None,
    *,
    include_vector_evidence: bool = False,
) -> list[ProcedureChart]:
    """Extract index-declared SID/STAR pages as route-label evidence.

    Vector drawings are deliberately opt-in.  A full NAIP run contains many
    thousands of standard plates, and decoding every page's drawing stream is
    a targeted diagnostic rather than a prerequisite for CSV/PDF conversion.
    """
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
            if include_vector_evidence:
                charts.extend(_cached_extract(
                    pdf, airport, "standard-terminal-procedure", chart_name, cache_dir,
                    lambda path, code, kind, name: extract_approach_chart(
                        path, code, kind, name, include_vector_evidence=True,
                    ),
                ))
            else:
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
    """Use rendered text positions for database-coding procedure tables.

    CAAC PDFs often store table cells by draw order, which can detach a leg
    from its procedure heading.  Sorting the native text objects by position
    restores the printed row order without interpreting chart geometry.
    """
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    result: list[ProcedureChart] = []
    with pymupdf.open(pdf) as document:
        for page_number, page in enumerate(document, start=1):
            text = _positioned_database_text(page.get_text("words"))
            result.append(_chart_from_text(pdf, airport, chart_type, chart_name, page_number, text, file_hash))
    return result


def extract_approach_chart(pdf: Path, airport: str, chart_type: str, chart_name: str, *, include_vector_evidence: bool = False) -> list[ProcedureChart]:
    """Extract text-layer procedure evidence, with optional vector-path analysis."""
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    result: list[ProcedureChart] = []
    with pymupdf.open(pdf) as document:
        for page_number, page in enumerate(document, start=1):
            chart = _chart_from_text(pdf, airport, chart_type, chart_name, page_number, page.get_text(), file_hash)
            words = page.get_text("words")
            route_fixes = extract_positioned_route_fixes(words)
            if include_vector_evidence and chart_type == "instrument-approach-index":
                route_fixes += extract_vector_route_fixes(words, page.get_drawings())
            standard_routes = _standard_procedure_routes(_positioned_database_text(words)) if chart_type == "standard-terminal-procedure" else ()
            result.append(replace(chart, route_fixes=tuple(dict.fromkeys(route_fixes)), standard_routes=standard_routes))
    return result
