"""Read-only diagnostics for records added to a local Fenix reference database."""

from __future__ import annotations

import sqlite3
import math
from pathlib import Path

from .model import NavModel


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
            samples: list[dict[str, object]] = result["reference_missing_sample"]  # type: ignore[assignment]
            if len(samples) < 20:
                source = sources[0]
                samples.append({"airport": source.airport, "ident": identifier, "latitude": latitude, "longitude": longitude, "source": source.source.file})
    return result
