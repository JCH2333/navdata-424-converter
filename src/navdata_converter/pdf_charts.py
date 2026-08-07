"""Evidence-preserving extraction of terminal-chart PDF text layers.

This module deliberately does not invent ARINC leg semantics from geometry.  It
returns observable labels and fix identifiers so the Fenix adapter can reject a
chart until an explicit mapping is implemented and tested.
"""

from __future__ import annotations

import hashlib
import re
import csv
from pathlib import Path

from pypdf import PdfReader

from .model import ProcedureChart, SourceRef


_PROCEDURE = re.compile(r"\b([A-Z0-9]{2,6}-\d{2}[AD])\b")
_WAYPOINT = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\b")
_IGNORED = {"CAAC", "ALL", "RIGHTS", "RESER", "MSA", "RNP", "ILS", "DME", "RWY", "ATC", "N", "E", "S", "W"}


def extract_chart(pdf: Path, airport: str, chart_type: str = "") -> list[ProcedureChart]:
    """Extract text from every page and retain labels with reproducible hashes."""
    reader = PdfReader(pdf)
    result: list[ProcedureChart] = []
    file_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        labels = tuple(sorted(set(_PROCEDURE.findall(text))))
        waypoints = tuple(sorted({token for token in _WAYPOINT.findall(text) if token not in _IGNORED and not token.isdigit()}))
        result.append(ProcedureChart(
            airport=airport,
            filename=pdf.name,
            page=page_number,
            chart_type=chart_type,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            procedure_labels=labels,
            waypoints=waypoints,
            source=SourceRef(str(pdf), page_number, page_number, file_hash),
        ))
    return result


def extract_airport_charts(airport_directory: Path) -> list[ProcedureChart]:
    """Resolve PDF names from the per-airport chart index and extract procedures."""
    index = airport_directory / "Charts.csv"
    if not index.is_file():
        raise FileNotFoundError(f"missing chart index: {index}")
    raw = index.read_bytes()
    for encoding in ("utf-8-sig", "gbk"):
        try:
            rows = list(csv.DictReader(raw.decode(encoding).splitlines()))
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        raise ValueError(f"unsupported chart-index encoding: {index}")
    charts: list[ProcedureChart] = []
    airport = airport_directory.resolve().name.upper()
    for row in rows:
        page = (row.get("PAGE_NUMBER") or "").strip()
        chart_type = (row.get("ChartTypeEx_CH") or "").strip()
        # Page numbers are the stable cross-encoding contract.  Classifying the
        # chart happens from extracted labels rather than locale-dependent text.
        if not page:
            continue
        pdf = airport_directory / f"{airport}-{page}.pdf"
        if pdf.is_file():
            charts.extend(extract_chart(pdf, airport, chart_type))
    return charts
