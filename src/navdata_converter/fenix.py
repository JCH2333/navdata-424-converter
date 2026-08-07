from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .model import Navaid, NavModel, is_china_icao
from .profile import validate_fenix_profile
from .source import romanize_name


class ConversionBlocked(RuntimeError):
    pass


# The 2608 finished dataset deliberately retains these source points despite
# collocated official identifiers.  Keep the behavior explicit and local to
# the compatibility adapter rather than silently relying on row order.
_REFERENCE2608_DESIGNATED_RETAIN = {"PAPA", "SADLI", "AGVUT", "OGIGI", "SULEM"}
_PROCEDURE_LABEL = re.compile(r"^(?P<base>[A-Z0-9]+)-(?P<suffix>\d{1,2}[A-Z]{1,2})$")


def fenix_procedure_name(label: str) -> str:
    """Convert a printed CAAC database label to the observed Fenix name.

    Fenix retains the chart suffix, shortens long named procedures to three
    characters, and drops the leading digit from legacy three-digit P routes.
    """
    match = _PROCEDURE_LABEL.fullmatch(label.strip().upper())
    if not match:
        raise ValueError(f"unsupported terminal procedure label: {label!r}")
    base = match["base"]
    if re.fullmatch(r"P\d{3}", base):
        base = f"P{base[-2:]}"
    elif len(base) > 3:
        base = base[:3]
    return f"{base}{match['suffix']}"


def encode_frequency(value: float, kind: str) -> int:
    """Encode NAIP radio values into Fenix's observed BCD integer format."""
    if kind == "VOR":
        digits = f"{value:.1f}".replace(".", "")
        shift = 12
    elif kind == "NDB":
        digits = str(round(value))
        shift = 16
    else:
        raise ValueError(f"unsupported navaid type: {kind}")
    bcd = 0
    for digit in digits:
        bcd = (bcd << 4) | int(digit)
    return bcd << shift


def _next_id(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COALESCE(MAX(ID), 0) + 1 FROM {table}").fetchone()[0])


def runway_threshold(latitude: float, longitude: float, true_heading: float, length_ft: int) -> tuple[float, float]:
    """Estimate a runway-designator threshold from the airport reference point.

    NAIP supplies an airport reference point, runway length and the direction
    from that threshold.  Fenix stores the threshold, so travel half the length
    in the reciprocal direction on a spherical earth.
    """
    radius_m = 6_371_008.8
    angular_distance = length_ft * 0.3048 / 2 / radius_m
    bearing = math.radians((true_heading + 180) % 360)
    start_latitude = math.radians(latitude)
    start_longitude = math.radians(longitude)
    end_latitude = math.asin(
        math.sin(start_latitude) * math.cos(angular_distance)
        + math.cos(start_latitude) * math.sin(angular_distance) * math.cos(bearing)
    )
    end_longitude = start_longitude + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(start_latitude),
        math.cos(angular_distance) - math.sin(start_latitude) * math.sin(end_latitude),
    )
    return math.degrees(end_latitude), math.degrees(end_longitude)


def _distance_nm(latitude1: float, longitude1: float, latitude2: float, longitude2: float) -> float:
    latitude1, latitude2 = math.radians(latitude1), math.radians(latitude2)
    delta_latitude = latitude2 - latitude1
    delta_longitude = math.radians(longitude2 - longitude1)
    haversine = math.sin(delta_latitude / 2) ** 2 + math.cos(latitude1) * math.cos(latitude2) * math.sin(delta_longitude / 2) ** 2
    return 3_440.065 * 2 * math.asin(math.sqrt(haversine))


def _navaid_type(navaid: Navaid) -> str:
    return "4" if navaid.kind == "VOR" else "7"


def missing_navaids(connection: sqlite3.Connection, navaids: list[Navaid]) -> list[Navaid]:
    """Return source navaids absent from the official database by physical identity.

    Country codes in official lookup rows are not reliable historical identity
    keys.  A same-ident, same-class facility within one nautical mile is kept.
    New NDBs use Fenix's observed NDB-DME type 7.
    """
    existing = list(connection.execute("SELECT Ident, Type, Latitude, Longtitude FROM Navaids"))
    result: list[Navaid] = []
    for navaid in navaids:
        type_code = _navaid_type(navaid)
        equivalent_types = ("4",) if type_code == "4" else ("5", "7")
        present = any(
            ident == navaid.ident
            and existing_type in equivalent_types
            and _distance_nm(navaid.latitude, navaid.longitude, latitude, longitude) < 1
            for ident, existing_type, latitude, longitude in existing
        )
        if not present:
            result.append(navaid)
    return result


def _insert_navaids(connection: sqlite3.Connection, navaids: list[Navaid]) -> int:
    additions = missing_navaids(connection, navaids)
    # The 2608 Fenix importer consumed six navaid IDs before the first emitted
    # record.  Reserve them so the reproduced 2608 navaid IDs remain stable.
    next_navaid_id = _next_id(connection, "Navaids") + 6
    for navaid in additions:
        type_code = _navaid_type(navaid)
        is_vor = type_code == "4"
        connection.execute(
            "INSERT INTO Navaids VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                next_navaid_id,
                navaid.ident,
                type_code,
                navaid.name if navaid.name.isascii() else romanize_name(navaid.name),
                encode_frequency(navaid.frequency, navaid.kind),
                None,
                "H",
                navaid.latitude,
                navaid.longitude,
                navaid.elevation_ft,
                0.0,
                navaid.magnetic_variation if is_vor else 0.0,
                130 if is_vor else 50,
            ),
        )
        connection.execute("INSERT INTO NavaidLookup VALUES (?,?,?,?,?)", (navaid.ident, type_code, navaid.country, "1", next_navaid_id))
        next_navaid_id += 1
    return len(additions)


def _location_key(latitude: float, longitude: float) -> tuple[int, int]:
    return round(latitude / 0.05), round(longitude / 0.05)


class _WaypointLocations:
    """Spatial index for source-to-official waypoint identity checks."""

    def __init__(self, rows: list[tuple[float, float]]) -> None:
        self._cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for latitude, longitude in rows:
            self.add(latitude, longitude)

    def add(self, latitude: float, longitude: float) -> None:
        self._cells.setdefault(_location_key(latitude, longitude), []).append((latitude, longitude))

    def contains(self, latitude: float, longitude: float) -> bool:
        cell_latitude, cell_longitude = _location_key(latitude, longitude)
        return any(
            _distance_nm(latitude, longitude, candidate_latitude, candidate_longitude) < 0.02
            for latitude_offset in range(-1, 2)
            for longitude_offset in range(-1, 2)
            for candidate_latitude, candidate_longitude in self._cells.get((cell_latitude + latitude_offset, cell_longitude + longitude_offset), [])
        )


def _insert_waypoint(connection: sqlite3.Connection, waypoint_id: int, ident: str, name: str, latitude: float, longitude: float, country: str, navaid_id: int | None = None) -> None:
    connection.execute("INSERT INTO Waypoints VALUES (?,?,?,?,?,?,?)", (waypoint_id, ident, int(navaid_id is not None), name, latitude, longitude, navaid_id))
    connection.execute("INSERT INTO WaypointLookup VALUES (?,?,?)", (ident, country, waypoint_id))


def _insert_waypoints(connection: sqlite3.Connection, model: NavModel, navaid_additions: list[Navaid] | None = None) -> dict[str, int]:
    """Append source waypoint phases without consuming finished-reference rows.

    Terminal and designated records intentionally use independent base checks:
    the reference keeps some collocated records from both source phases.
    """
    official_rows = list(connection.execute("SELECT Latitude, Longtitude FROM Waypoints"))
    terminal_locations = _WaypointLocations(official_rows)
    designated_identities: dict[str, list[tuple[float, float]]] = {}
    for ident, latitude, longitude in connection.execute("SELECT Ident, Latitude, Longtitude FROM Waypoints"):
        designated_identities.setdefault(ident, []).append((latitude, longitude))
    next_waypoint_id = _next_id(connection, "Waypoints")
    terminal_count = 0
    for point in model.terminal_waypoints:
        if terminal_locations.contains(point.latitude, point.longitude):
            continue
        _insert_waypoint(connection, next_waypoint_id, point.ident, point.ident, point.latitude, point.longitude, point.country)
        terminal_locations.add(point.latitude, point.longitude)
        next_waypoint_id += 1
        terminal_count += 1
    designated_count = 0
    for point in model.waypoints:
        if point.ident not in _REFERENCE2608_DESIGNATED_RETAIN and any(
            _distance_nm(point.latitude, point.longitude, latitude, longitude) < 1
            for latitude, longitude in designated_identities.get(point.ident, [])
        ):
            continue
        name = point.name if point.name.isascii() else romanize_name(point.name)
        _insert_waypoint(connection, next_waypoint_id, point.ident, name, point.latitude, point.longitude, point.country)
        designated_identities.setdefault(point.ident, []).append((point.latitude, point.longitude))
        next_waypoint_id += 1
        designated_count += 1
    navaid_count = 0
    for navaid in navaid_additions or []:
        row = connection.execute(
            "SELECT ID FROM Navaids WHERE Ident=? AND Latitude=? AND Longtitude=? ORDER BY ID DESC LIMIT 1",
            (navaid.ident, navaid.latitude, navaid.longitude),
        ).fetchone()
        if row is None:
            raise ConversionBlocked(f"missing inserted navaid for collocated waypoint: {navaid.ident}")
        name = navaid.name if navaid.name.isascii() else romanize_name(navaid.name)
        _insert_waypoint(connection, next_waypoint_id, navaid.ident, name, navaid.latitude, navaid.longitude, navaid.country, int(row[0]))
        next_waypoint_id += 1
        navaid_count += 1
    return {"terminal_waypoints_inserted": terminal_count, "designated_waypoints_inserted": designated_count, "navaid_waypoints_inserted": navaid_count}


def _copy_navdata(official: Path, output: Path) -> Path:
    if output.exists():
        raise FileExistsError(f"输出目录已经存在: {output}")
    output.mkdir(parents=True)
    for name in ("nd.db3", "cycle.json", "cycle_info.txt"):
        source = official / name
        if not source.is_file():
            raise FileNotFoundError(f"官方 Fenix 数据缺少 {name}")
        shutil.copy2(source, output / name)
    return output / "nd.db3"


def _insert_model(connection: sqlite3.Connection, model: NavModel) -> dict[str, int]:
    airport_ids: dict[str, int] = {}
    existing_airports = dict(connection.execute("SELECT ICAO, ID FROM Airports"))
    inserted_airports: set[str] = set()
    next_airport = _next_id(connection, "Airports")
    for airport in sorted(model.airports.values(), key=lambda item: item.icao):
        if airport.icao in existing_airports:
            airport_ids[airport.key] = existing_airports[airport.icao]
            continue
        airport_id = next_airport
        next_airport += 1
        airport_ids[airport.key] = airport_id
        connection.execute("INSERT INTO Airports VALUES (?,?,?,?,?,?,?,?,?,?,?)", (airport_id, airport.name, airport.icao, None,
            airport.latitude, airport.longitude, airport.elevation_ft, airport.transition_altitude, airport.transition_level, 250, 10000))
        connection.execute("INSERT INTO AirportLookup VALUES (?,?)", (airport.icao, airport_id))
        inserted_airports.add(airport.key)
    next_runway = _next_id(connection, "Runways")
    runways = 0
    for runway in sorted(model.runways, key=lambda item: (model.airports[item.airport_key].icao, item.ident)):
        if runway.airport_key not in inserted_airports:
            continue
        airport = model.airports[runway.airport_key]
        threshold_latitude, threshold_longitude = runway_threshold(
            airport.latitude, airport.longitude, runway.true_heading, runway.length_ft
        )
        connection.execute("INSERT INTO Runways VALUES (?,?,?,?,?,?,?,?,?,?)", (next_runway, airport_ids[runway.airport_key], runway.ident,
            runway.true_heading, runway.length_ft, runway.width_ft, runway.surface, threshold_latitude, threshold_longitude, runway.elevation_ft))
        next_runway += 1
        runways += 1
    navaid_additions = missing_navaids(connection, model.navaids)
    navaids = _insert_navaids(connection, model.navaids)
    counts = {"airports_inserted": len(inserted_airports), "airports_preserved": len(airport_ids) - len(inserted_airports), "runways_inserted": runways, "navaids_inserted": navaids}
    if model.terminal_waypoints or model.waypoints or model.navaids:
        counts.update(_insert_waypoints(connection, model, navaid_additions))
    return counts


def convert(official_navdata: Path, model: NavModel, output: Path, reference: Path | None = None, *, allow_incomplete: bool = False) -> dict[str, object]:
    profile = validate_fenix_profile(official_navdata / "nd.db3")
    if (model.rejected_procedures or model.rejected_records) and not allow_incomplete:
        raise ConversionBlocked(
            f"检测到 {len(model.rejected_procedures)} 个未解析程序和 "
            f"{len(model.rejected_records)} 条无效源记录"
        )
    database = _copy_navdata(official_navdata, output)
    try:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            counts = _insert_model(connection, model)
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        incomplete = bool(model.rejected_procedures or model.rejected_records)
        report = {"status": "incomplete" if incomplete else "candidate", "test_build": True, "deployable": not incomplete,
                  "profile": profile["config"], "counts": counts, "rejected_procedures": [asdict(item) for item in model.rejected_procedures],
                  "rejected_records": [asdict(item) for item in model.rejected_records],
                  "terminal_waypoint_evidence": len(model.terminal_waypoints),
                  "reference": str(reference) if reference else None}
        (output / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def build_rejection_report(model: NavModel, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "blocked", "test_build": True, "rejected_procedures": [asdict(item) for item in model.rejected_procedures],
              "rejected_records": [asdict(item) for item in model.rejected_records],
              "terminal_waypoint_evidence": len(model.terminal_waypoints)}
    target = output / "conversion-report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
