"""Read-only diagnostics for records added to a local Fenix reference database."""

from __future__ import annotations

import sqlite3
import math
from pathlib import Path

from .model import NavModel
from .pdf_charts import approach_procedure_name_candidates


def _db(path: Path) -> Path:
    return path / "nd.db3" if path.is_dir() else path


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    }


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _id_delta(base: sqlite3.Connection, reference: sqlite3.Connection, table: str) -> dict[str, object]:
    columns = _columns(reference, table)
    if "ID" not in columns or columns != _columns(base, table):
        return {"id_diagnostic": False}
    id_index = columns.index("ID")
    quoted = ", ".join(f'"{column}"' for column in columns)
    base_rows = {row[id_index]: row for row in base.execute(f'SELECT {quoted} FROM "{table}"')}
    reference_rows = {row[id_index]: row for row in reference.execute(f'SELECT {quoted} FROM "{table}"')}
    added_ids = [row[0] for row in reference.execute(f'SELECT "ID" FROM "{table}" ORDER BY rowid') if row[0] not in base_rows]
    changed_ids = sorted(identifier for identifier in base_rows.keys() & reference_rows.keys() if base_rows[identifier] != reference_rows[identifier])
    return {
        "id_diagnostic": True,
        "base_max_id": max(base_rows, default=None),
        "added_rows": len(added_ids),
        "added_ids_in_physical_order": added_ids[:20],
        "added_ids_tail": added_ids[-20:],
        "physical_id_order_ascending": added_ids == sorted(added_ids),
        "changed_existing_rows": len(changed_ids),
        "changed_id_sample": changed_ids[:20],
    }


def inspect_reference_delta(official: Path, reference: Path) -> dict[str, object]:
    """Compare an official base with a local finished database without copying data."""
    official, reference = _db(official), _db(reference)
    with sqlite3.connect(f"file:{official}?mode=ro", uri=True) as base, sqlite3.connect(f"file:{reference}?mode=ro", uri=True) as finished:
        base_tables = _tables(base)
        reference_tables = _tables(finished)
        result: dict[str, dict[str, object]] = {}
        for table in sorted(base_tables | reference_tables):
            if table not in base_tables or table not in reference_tables:
                result[table] = {"present": [table in base_tables, table in reference_tables]}
                continue
            item: dict[str, object] = {
                "base_rows": base.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                "reference_rows": finished.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
            }
            item.update(_id_delta(base, finished, table))
            result[table] = item
    return {"tables": result}


def _distance_nm(latitude1: float, longitude1: float, latitude2: float, longitude2: float) -> float:
    latitude1, latitude2 = math.radians(latitude1), math.radians(latitude2)
    latitude_delta = latitude2 - latitude1
    longitude_delta = math.radians(longitude2 - longitude1)
    haversine = math.sin(latitude_delta / 2) ** 2 + math.cos(latitude1) * math.cos(latitude2) * math.sin(longitude_delta / 2) ** 2
    return 3_440.065 * 2 * math.asin(math.sqrt(haversine))


def _waypoints_by_ident(connection: sqlite3.Connection) -> dict[str, list[tuple[int, float, float]]]:
    result: dict[str, list[tuple[int, float, float]]] = {}
    for identifier, point_id, latitude, longitude in connection.execute("SELECT Ident, ID, Latitude, Longtitude FROM Waypoints"):
        result.setdefault(identifier, []).append((point_id, latitude, longitude))
    return result


def _grid_key(latitude: float, longitude: float) -> tuple[int, int]:
    # 0.05 degrees is wider than the matching tolerance, so examining the
    # neighbouring cells cannot omit a point within 0.02 NM.
    return round(latitude / 0.05), round(longitude / 0.05)


def _waypoint_grid(points: dict[str, list[tuple[int, float, float]]]) -> dict[tuple[int, int], list[tuple[int, str, float, float]]]:
    result: dict[tuple[int, int], list[tuple[int, str, float, float]]] = {}
    for identifier, entries in points.items():
        for point_id, latitude, longitude in entries:
            result.setdefault(_grid_key(latitude, longitude), []).append((point_id, identifier, latitude, longitude))
    return result


def _physical_hits(grid: dict[tuple[int, int], list[tuple[int, str, float, float]]], latitude: float, longitude: float, tolerance_nm: float) -> list[tuple[int, str, float, float]]:
    cell_latitude, cell_longitude = _grid_key(latitude, longitude)
    candidates = [
        point
        for latitude_offset in range(-1, 2)
        for longitude_offset in range(-1, 2)
        for point in grid.get((cell_latitude + latitude_offset, cell_longitude + longitude_offset), [])
    ]
    return [point for point in candidates if _distance_nm(latitude, longitude, point[2], point[3]) < tolerance_nm]


def inspect_terminal_waypoint_coverage(model: NavModel, official: Path, reference: Path, tolerance_nm: float = 0.02) -> dict[str, object]:
    """Measure indexed terminal coordinate evidence against local Fenix databases.

    Matches require both an identical identifier and physical proximity.  The
    function is deliberately read-only and reports unmatched samples for later
    source-priority and ID-phase investigation.
    """
    official, reference = _db(official), _db(reference)
    points: dict[tuple[str, float, float], list[object]] = {}
    for point in model.terminal_waypoints:
        points.setdefault((point.ident, round(point.latitude, 9), round(point.longitude, 9)), []).append(point)
    with sqlite3.connect(f"file:{official}?mode=ro", uri=True) as base, sqlite3.connect(f"file:{reference}?mode=ro", uri=True) as finished:
        base_points = _waypoints_by_ident(base)
        reference_points = _waypoints_by_ident(finished)
        reference_grid = _waypoint_grid(reference_points)
        base_max_id = int(base.execute("SELECT COALESCE(MAX(ID), 0) FROM Waypoints").fetchone()[0])
    result = {
        "evidence_rows": len(model.terminal_waypoints),
        "unique_physical_points": len(points),
        "official_matches": 0,
        "official_missing": 0,
        "reference_matches": 0,
        "reference_missing": 0,
        "reference_new_matches": 0,
        "reference_existing_matches": 0,
        "reference_renamed_or_collocated": 0,
        "reference_unrepresented": 0,
        "reference_missing_sample": [],
    }
    for (identifier, latitude, longitude), sources in points.items():
        official_hits = [row for row in base_points.get(identifier, []) if _distance_nm(latitude, longitude, row[1], row[2]) < tolerance_nm]
        reference_hits = [row for row in reference_points.get(identifier, []) if _distance_nm(latitude, longitude, row[1], row[2]) < tolerance_nm]
        result["official_matches" if official_hits else "official_missing"] += 1
        if reference_hits:
            result["reference_matches"] += 1
            result["reference_new_matches" if any(row[0] > base_max_id for row in reference_hits) else "reference_existing_matches"] += 1
        else:
            result["reference_missing"] += 1
            physical_hits = _physical_hits(reference_grid, latitude, longitude, tolerance_nm)
            result["reference_renamed_or_collocated" if physical_hits else "reference_unrepresented"] += 1
            samples: list[dict[str, object]] = result["reference_missing_sample"]  # type: ignore[assignment]
            if len(samples) < 20:
                source = sources[0]
                samples.append({"airport": source.airport, "ident": identifier, "latitude": latitude, "longitude": longitude, "source": source.source.file})
    return result


def inspect_database_fix_coverage(model: NavModel, official: Path, reference: Path, tolerance_nm: float = 0.02) -> dict[str, int]:
    """Measure coordinate-page points that database-coded procedures actually use."""
    fix_keys = {
        (chart.airport, leg.fix_ident)
        for chart in model.procedure_charts
        for leg in chart.terminal_legs
        if leg.fix_ident
    }
    points = {
        (point.ident, round(point.latitude, 9), round(point.longitude, 9))
        for point in model.terminal_waypoints
        if (point.airport, point.ident) in fix_keys
    }
    official, reference = _db(official), _db(reference)
    with sqlite3.connect(f"file:{official}?mode=ro", uri=True) as base, sqlite3.connect(f"file:{reference}?mode=ro", uri=True) as finished:
        base_ids = {row[0] for row in base.execute("SELECT ID FROM Waypoints")}
        added_by_ident: dict[str, list[tuple[float, float]]] = {}
        for identifier, point_id, latitude, longitude in finished.execute("SELECT Ident, ID, Latitude, Longtitude FROM Waypoints"):
            if point_id not in base_ids:
                added_by_ident.setdefault(identifier, []).append((latitude, longitude))
    matches = sum(
        any(_distance_nm(latitude, longitude, candidate_latitude, candidate_longitude) < tolerance_nm for candidate_latitude, candidate_longitude in added_by_ident.get(identifier, []))
        for identifier, latitude, longitude in points
    )
    return {"database_fix_keys": len(fix_keys), "coordinate_points": len(points), "reference_added_matches": matches}


def inspect_role_fix_coverage(model: NavModel, official: Path, reference: Path, tolerance_nm: float = 0.02) -> dict[str, int]:
    """Measure coordinate-page points supported by explicit plate route roles."""
    fix_keys = {
        (chart.airport, fix.ident)
        for chart in model.procedure_charts
        for fix in chart.route_fixes
    }
    points = {
        (point.ident, round(point.latitude, 9), round(point.longitude, 9))
        for point in model.terminal_waypoints
        if (point.airport, point.ident) in fix_keys
    }
    official, reference = _db(official), _db(reference)
    with sqlite3.connect(f"file:{official}?mode=ro", uri=True) as base, sqlite3.connect(f"file:{reference}?mode=ro", uri=True) as finished:
        base_ids = {row[0] for row in base.execute("SELECT ID FROM Waypoints")}
        added_by_ident: dict[str, list[tuple[float, float]]] = {}
        for identifier, point_id, latitude, longitude in finished.execute("SELECT Ident, ID, Latitude, Longtitude FROM Waypoints"):
            if point_id not in base_ids:
                added_by_ident.setdefault(identifier, []).append((latitude, longitude))
    matches = sum(
        any(_distance_nm(latitude, longitude, candidate_latitude, candidate_longitude) < tolerance_nm for candidate_latitude, candidate_longitude in added_by_ident.get(identifier, []))
        for identifier, latitude, longitude in points
    )
    return {"role_fix_keys": len(fix_keys), "coordinate_points": len(points), "reference_added_matches": matches}


def _runway_key(value: object) -> str:
    """Normalize printed Fenix and chart runway tokens for a read-only join."""
    runway = str(value or "").upper().strip().replace(" ", "")
    if runway.startswith("RWY"):
        runway = runway[3:]
    if runway.startswith("R") and len(runway) > 1 and runway[1:3].isdigit():
        runway = runway[1:]
    return runway


def inspect_approach_chart_coverage(model: NavModel, official: Path, reference: Path) -> dict[str, object]:
    """Compare indexed NAIP approach-chart runways to Fenix Proc=3 rows.

    It is a source-evidence diagnostic only: an index page identifies a runway
    surface but does not yet establish a procedure name, transition, or leg
    sequence.  Consequently callers must not use this result for conversion.
    """
    charts = [chart for chart in model.procedure_charts if chart.chart_type == "instrument-approach-index"]
    evidence = {
        (chart.airport.upper(), _runway_key(runway))
        for chart in charts
        for runway in chart.runways
        if _runway_key(runway)
    }
    official_database, database = _db(official), _db(reference)
    with sqlite3.connect(f"file:{official_database}?mode=ro", uri=True) as base, sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        columns = _columns(connection, "Terminals")
        quoted = ", ".join(f'"{column}"' for column in columns)
        id_index = columns.index("ID")
        proc_index = columns.index("Proc")
        base_rows = {row[id_index]: row for row in base.execute(f"SELECT {quoted} FROM Terminals")}
        raw_rows = list(connection.execute(f"SELECT {quoted} FROM Terminals"))
        delta_ids = {
            row[id_index]
            for row in raw_rows
            if row[id_index] not in base_rows or row != base_rows[row[id_index]]
        }
        rows = [
            (row[columns.index("ICAO")], row[columns.index("Rwy")], row[columns.index("Name")], row[id_index])
            for row in raw_rows
            if str(row[proc_index]) == "3"
        ]
    reference_pairs = {
        (str(icao).upper(), _runway_key(runway))
        for icao, runway, _, _ in rows
        if str(icao).upper() in {airport for airport, _ in evidence} and _runway_key(runway)
    }
    name_candidates = {
        (chart.airport.upper(), _runway_key(runway), name)
        for chart in charts
        for runway in chart.runways
        for name in approach_procedure_name_candidates(chart.chart_name, (_runway_key(runway),), chart.airport)
    }
    reference_names = {
        (str(icao).upper(), _runway_key(runway), str(name or "").upper())
        for icao, runway, name, _ in rows
        if str(icao).upper() in {airport for airport, _ in evidence} and _runway_key(runway)
    }
    non_runway_names = [
        {"airport": str(icao).upper(), "runway": _runway_key(runway), "name": str(name or "")}
        for icao, runway, name, _ in rows
        if str(icao).upper() in {airport for airport, _ in evidence}
        and _runway_key(runway)
        and str(name or "").upper() != f"R{_runway_key(runway)}"
    ]
    def payload(pair: tuple[str, str]) -> dict[str, str]:
        return {"airport": pair[0], "runway": pair[1]}
    def name_payload(item: tuple[str, str, str]) -> dict[str, str]:
        return {"airport": item[0], "runway": item[1], "name": item[2]}
    delta_names = {
        (str(icao).upper(), _runway_key(runway), str(name or "").upper())
        for icao, runway, name, identifier in rows
        if identifier in delta_ids and str(icao).upper() in {airport for airport, _ in evidence} and _runway_key(runway)
    }
    return {
        "evidence_pages": len(charts),
        "evidence_pairs": len(evidence),
        "reference_pairs": len(reference_pairs),
        "matched_pairs": len(evidence & reference_pairs),
        "evidence_without_reference": [payload(pair) for pair in sorted(evidence - reference_pairs)[:20]],
        "reference_without_evidence": [payload(pair) for pair in sorted(reference_pairs - evidence)[:20]],
        "reference_non_runway_name_count": len(non_runway_names),
        "reference_non_runway_name_sample": non_runway_names[:20],
        "name_candidates": len(name_candidates),
        "reference_names": len(reference_names),
        "matched_names": len(name_candidates & reference_names),
        "candidate_names_without_reference": [name_payload(item) for item in sorted(name_candidates - reference_names)[:20]],
        "reference_names_without_candidate": [name_payload(item) for item in sorted(reference_names - name_candidates)[:20]],
        "delta_names": len(delta_names),
        "matched_delta_names": len(name_candidates & delta_names),
        "delta_names_without_candidate": [name_payload(item) for item in sorted(delta_names - name_candidates)[:20]],
    }
