from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .model import ChartTerminalLeg, Ils, Navaid, NavModel, ProcedureSegment, TerminalWaypoint, is_china_icao
from .pdf_charts import approach_procedure_name_candidates
from .profile import validate_fenix_profile
from .source import romanize_name


class ConversionBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class FenixTerminalLegProjection:
    """The source-backed subset of one Fenix TerminalLegs/Ex pair."""

    type_code: str
    transition: str
    track_code: str
    waypoint_id: int | None
    waypoint_latitude: float | None
    waypoint_longitude: float | None
    turn_direction: str | None
    course: float | None
    altitude: str | None
    waypoint_description: str
    speed_limit: float | None
    speed_limit_description: str | None
    center_id: int | None = None
    center_latitude: float | None = None
    center_longitude: float | None = None


@dataclass(frozen=True)
class FenixIlsProjection:
    frequency: int
    glide_slope_angle: float
    latitude: float
    longitude: float
    category: str
    ident: str
    localizer_course: float
    crossing_height: str
    elevation_feet: int


_FENIX_REFERENCE_ILS_CROSSING_HEIGHT_FEET = 50


# The 2608 finished dataset deliberately retains these source points despite
# collocated official identifiers.  Keep the behavior explicit and local to
# the compatibility adapter rather than silently relying on row order.
_REFERENCE2608_DESIGNATED_RETAIN = {"PAPA", "SADLI", "AGVUT", "OGIGI", "SULEM"}
_PROCEDURE_LABEL = re.compile(r"^(?P<base>[A-Z0-9]+)-(?P<suffix>\d{1,2}[A-Z]{1,2})$")
_IAP_KINDS = {"\u8fdb\u8fd1\u8fc7\u6e21", "\u8fdb\u8fd1", "\u590d\u98de"}


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


def fenix_procedure_type(label: str, procedure_kind: str) -> str:
    """Map observable database-heading direction to Fenix procedure type."""
    if procedure_kind == "\u79bb\u573a":
        return "2"
    if procedure_kind == "\u8fdb\u573a":
        return "1"
    if label.endswith("A"):
        return "1"
    if label.endswith("D"):
        return "2"
    raise ValueError(f"unsupported terminal procedure kind: {procedure_kind!r} for {label!r}")


def fenix_terminal_identity(segment: ProcedureSegment) -> tuple[str, str, str]:
    """Map a source procedure segment to its Fenix terminal business key.

    Database coding pages use a literal runway heading for an approach.  An
    explicit W/X/Y/Z suffix is retained as the Fenix procedure suffix.
    """
    if segment.kind in {"进近过渡", "进近", "复飞"}:
        return "3", segment.label, segment.runway
    return fenix_procedure_type(segment.label, segment.kind), fenix_procedure_name(segment.label), segment.runway


def _constraint_altitude(meters: float | None) -> str | None:
    if meters is None:
        return None
    return f"{round(meters * 3.28084 / 100) * 100:.0f}A"


def project_database_terminal_leg(
    leg: ChartTerminalLeg,
    procedure_type: str,
    transition: str,
    waypoint: tuple[int, float, float] | None = None,
    center: tuple[int, float, float] | None = None,
) -> FenixTerminalLegProjection:
    """Project a database-coding leg only when every required source value exists."""
    type_codes = {"1": "6", "2": "5", "3": "0"}
    if procedure_type not in type_codes:
        raise ValueError(f"unsupported Fenix procedure type: {procedure_type}")
    if leg.leg_type not in {"CA", "CF", "DF", "HF", "HM", "IF", "RF", "TF"}:
        raise ValueError(f"unsupported database leg type: {leg.leg_type}")
    if leg.fix_ident and waypoint is None:
        raise ValueError(f"missing resolved waypoint for {leg.fix_ident}")
    if not leg.fix_ident and waypoint is not None:
        raise ValueError(f"unexpected waypoint for {leg.leg_type}")
    if leg.leg_type == "RF" and center is None:
        raise ValueError("missing resolved RF center")
    if leg.leg_type != "RF" and center is not None:
        raise ValueError(f"unexpected center for {leg.leg_type}")
    waypoint_id, waypoint_latitude, waypoint_longitude = waypoint or (None, None, None)
    center_id, center_latitude, center_longitude = center or (None, None, None)
    return FenixTerminalLegProjection(
        type_codes[procedure_type], transition, leg.leg_type,
        waypoint_id, waypoint_latitude, waypoint_longitude,
        leg.turn_direction, leg.course_degrees, _constraint_altitude(leg.altitude_meters), "E",
        float(leg.speed_limit_knots) if leg.speed_limit_knots is not None else None,
        "B" if leg.speed_limit_knots is not None else None,
        center_id, center_latitude, center_longitude,
    )


def project_database_iap_leg(
    leg: ChartTerminalLeg,
    transition: str | None,
    waypoint_description: str,
    waypoint: tuple[int, float, float] | None = None,
    center: tuple[int, float, float] | None = None,
) -> FenixTerminalLegProjection:
    """Project one explicitly sectioned IAP leg with its Fenix description."""
    return replace(
        project_database_terminal_leg(leg, "3", transition or "", waypoint, center),
        waypoint_description=waypoint_description,
    )


def resolve_terminal_waypoint(
    connection: sqlite3.Connection,
    model: NavModel,
    airport: str,
    ident: str,
) -> tuple[int, float, float]:
    """Resolve one printed terminal fix to an exact target waypoint identity."""
    source_points = {
        (round(point.latitude, 9), round(point.longitude, 9))
        for point in model.terminal_waypoints
        if point.airport == airport and point.ident == ident
    }
    if len(source_points) != 1:
        raise ConversionBlocked(f"terminal fix {airport}/{ident} has {len(source_points)} source locations")
    latitude, longitude = next(iter(source_points))
    rows = _resolve_terminal_target_rows(
        latitude, longitude,
        list(connection.execute("SELECT ID, Latitude, Longtitude FROM Waypoints WHERE Ident=?", (ident,))),
    )
    if len(rows) != 1:
        raise ConversionBlocked(f"terminal fix {airport}/{ident} has {len(rows)} target waypoint matches")
    return int(rows[0][0]), float(rows[0][1]), float(rows[0][2])


def _resolve_terminal_target_rows(
    latitude: float,
    longitude: float,
    candidates: list[tuple[int, float, float]],
) -> list[tuple[int, float, float]]:
    """Prefer one exact terminal-coordinate-page position over nearby points."""
    exact = [
        row for row in candidates
        if math.isclose(latitude, row[1], abs_tol=1e-8)
        and math.isclose(longitude, row[2], abs_tol=1e-8)
    ]
    if len(exact) == 1:
        return exact
    return [
        row for row in candidates
        if _distance_nm(latitude, longitude, row[1], row[2]) < 0.02
    ]


def _terminal_waypoint_resolutions(connection: sqlite3.Connection, model: NavModel) -> tuple[dict[tuple[str, str], tuple[int, float, float]], dict[tuple[str, str], str]]:
    """Resolve all source terminal fixes once before projecting procedure legs."""
    source_points: dict[tuple[str, str], set[tuple[float, float]]] = {}
    for point in model.terminal_waypoints:
        source_points.setdefault((point.airport, point.ident), set()).add((round(point.latitude, 9), round(point.longitude, 9)))
    designated_points: dict[str, set[tuple[float, float]]] = {}
    for point in model.waypoints:
        designated_points.setdefault(point.ident, set()).add((round(point.latitude, 9), round(point.longitude, 9)))
    navaid_points: dict[str, set[tuple[float, float]]] = {}
    for navaid in model.navaids:
        navaid_points.setdefault(navaid.ident, set()).add((round(navaid.latitude, 9), round(navaid.longitude, 9)))
    required_keys = {
        (segment.airport, ident)
        for segment in model.procedure_segments
        for leg in segment.legs
        for ident in (leg.fix_ident, leg.center_ident)
        if ident
    }
    required_keys.update(source_points)
    targets: dict[str, list[tuple[int, float, float]]] = {}
    for point_id, ident, latitude, longitude in connection.execute("SELECT ID, Ident, Latitude, Longtitude FROM Waypoints"):
        targets.setdefault(str(ident), []).append((int(point_id), float(latitude), float(longitude)))
    source_terminal_ids = {
        (str(airport), str(ident), round(float(latitude), 9), round(float(longitude), 9)): int(waypoint_id)
        for airport, ident, latitude, longitude, waypoint_id in connection.execute(
            "SELECT Airport, Ident, Latitude, Longtitude, WaypointID "
            "FROM temp._fenix_source_terminal_waypoints"
        )
    } if connection.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='_fenix_source_terminal_waypoints'"
    ).fetchone() else {}
    source_designated_ids = {
        (str(ident), round(float(latitude), 9), round(float(longitude), 9)): int(waypoint_id)
        for ident, latitude, longitude, waypoint_id in connection.execute(
            "SELECT Ident, Latitude, Longtitude, WaypointID "
            "FROM temp._fenix_source_designated_waypoints"
        )
    } if connection.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='_fenix_source_designated_waypoints'"
    ).fetchone() else {}
    resolutions: dict[tuple[str, str], tuple[int, float, float]] = {}
    failures: dict[tuple[str, str], str] = {}
    for key in required_keys:
        airport, ident = key
        locations = source_points.get(key)
        if locations is None:
            locations = designated_points.get(ident)
        if locations is None:
            locations = navaid_points.get(ident)
        if locations is None:
            failures[key] = f"terminal fix {airport}/{ident} has no source coordinate evidence"
            continue
        if len(locations) != 1:
            count = len(locations)
            failures[key] = f"terminal fix {airport}/{ident} has {count} source locations"
            continue
        latitude, longitude = next(iter(locations))
        source_id = source_terminal_ids.get((airport, ident, latitude, longitude))
        if source_id is None and key not in source_points:
            source_id = source_designated_ids.get((ident, latitude, longitude))
        if source_id is not None:
            preferred = [row for row in targets.get(ident, []) if row[0] == source_id]
            if len(preferred) == 1:
                resolutions[key] = preferred[0]
                continue
        matches = _resolve_terminal_target_rows(latitude, longitude, targets.get(ident, []))
        if len(matches) != 1:
            failures[key] = f"terminal fix {airport}/{ident} has {len(matches)} target waypoint matches"
            continue
        resolutions[key] = matches[0]
    return resolutions, failures


def encode_frequency(value: float, kind: str) -> int:
    """Encode NAIP radio values into Fenix's observed BCD integer format."""
    if kind == "VOR":
        # Fenix stores the printed VHF digits as left-aligned BCD.  Most
        # channels have one decimal place, but AD 2.19 also publishes 25 kHz
        # and 5 kHz values such as 111.55 and 108.950.
        digits = f"{value:.3f}".rstrip("0").replace(".", "")
        shift = 4 * (7 - len(digits))
        if shift < 0:
            raise ValueError(f"invalid VHF frequency: {value!r}")
    elif kind == "NDB":
        digits = str(round(value))
        shift = 16
    else:
        raise ValueError(f"unsupported navaid type: {kind}")
    bcd = 0
    for digit in digits:
        bcd = (bcd << 4) | int(digit)
    return bcd << shift


def project_ad219_ils(ils: Ils) -> FenixIlsProjection:
    """Project an AD 2.19 ILS only when every Fenix field is source-backed."""
    categories = {"I": "1", "II": "2", "III": "3"}
    if ils.category not in categories:
        raise ConversionBlocked(f"ILS {ils.airport}/{ils.runway}/{ils.ident} has no supported CAT category")
    missing = [
        name for name, value in (
            ("LOC course", ils.localizer_course_magnetic),
            ("GP angle", ils.glide_slope_degrees),
            ("RDH", ils.crossing_height_meters),
            ("DME elevation", ils.dme_elevation_meters),
        ) if value is None
    ]
    if missing:
        raise ConversionBlocked(f"ILS {ils.airport}/{ils.runway}/{ils.ident} missing {', '.join(missing)}")
    return FenixIlsProjection(
        frequency=encode_frequency(ils.frequency_mhz, "VOR"),
        glide_slope_angle=float(ils.glide_slope_degrees),
        latitude=round(ils.localizer_latitude, 6),
        longitude=round(ils.localizer_longitude, 6),
        category=categories[ils.category],
        ident=ils.ident,
        localizer_course=float(ils.localizer_course_magnetic),
        crossing_height=str(_FENIX_REFERENCE_ILS_CROSSING_HEIGHT_FEET),
        elevation_feet=math.ceil(float(ils.dme_elevation_meters) * 3.28084),
    )


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
    terminal_identities: dict[str, _WaypointLocations] = {}
    for ident, latitude, longitude in connection.execute("SELECT Ident, Latitude, Longtitude FROM Waypoints"):
        terminal_identities.setdefault(str(ident), _WaypointLocations([])).add(float(latitude), float(longitude))
    designated_identities: dict[str, list[tuple[float, float]]] = {}
    for ident, latitude, longitude in connection.execute("SELECT Ident, Latitude, Longtitude FROM Waypoints"):
        designated_identities.setdefault(ident, []).append((latitude, longitude))
    next_waypoint_id = _next_id(connection, "Waypoints")
    connection.execute("DROP TABLE IF EXISTS temp._fenix_source_terminal_waypoints")
    connection.execute("DROP TABLE IF EXISTS temp._fenix_source_designated_waypoints")
    connection.execute(
        "CREATE TEMP TABLE _fenix_source_terminal_waypoints "
        "(Airport TEXT NOT NULL, Ident TEXT NOT NULL, Latitude REAL NOT NULL, Longtitude REAL NOT NULL, WaypointID INTEGER NOT NULL)"
    )
    connection.execute(
        "CREATE TEMP TABLE _fenix_source_designated_waypoints "
        "(Ident TEXT NOT NULL, Latitude REAL NOT NULL, Longtitude REAL NOT NULL, WaypointID INTEGER NOT NULL)"
    )
    terminal_point_ids: dict[tuple[str, float, float], int] = {}
    terminal_count = 0
    for point in model.terminal_waypoints:
        locations = terminal_identities.setdefault(point.ident, _WaypointLocations([]))
        point_key = (point.ident, round(point.latitude, 9), round(point.longitude, 9))
        if locations.contains(point.latitude, point.longitude):
            waypoint_id = terminal_point_ids.get(point_key)
            if waypoint_id is not None:
                connection.execute(
                    "INSERT INTO temp._fenix_source_terminal_waypoints VALUES (?,?,?,?,?)",
                    (point.airport, point.ident, point.latitude, point.longitude, waypoint_id),
                )
            continue
        _insert_waypoint(connection, next_waypoint_id, point.ident, point.ident, point.latitude, point.longitude, point.country)
        connection.execute(
            "INSERT INTO temp._fenix_source_terminal_waypoints VALUES (?,?,?,?,?)",
            (point.airport, point.ident, point.latitude, point.longitude, next_waypoint_id),
        )
        terminal_point_ids[point_key] = next_waypoint_id
        locations.add(point.latitude, point.longitude)
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
        connection.execute(
            "INSERT INTO temp._fenix_source_designated_waypoints VALUES (?,?,?,?)",
            (point.ident, point.latitude, point.longitude, next_waypoint_id),
        )
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


def _insert_terminal_procedures(connection: sqlite3.Connection, model: NavModel) -> dict[str, object]:
    """Insert only fully evidenced SID/STAR plans and their paired extension rows.

    IAP rows need additional Fenix-only MAP and waypoint-description semantics.
    They remain out of this source-backed path until those semantics have a
    deterministic rule.  SID/STAR rows can be projected directly from the
    database coding table when all referenced terminal points resolve uniquely.
    """
    next_terminal_id = _next_id(connection, "Terminals")
    next_leg_id = _next_id(connection, "TerminalLegs")
    airport_ids = dict(connection.execute("SELECT ICAO, ID FROM Airports"))
    runway_ids = {
        (airport_id, ident): runway_id
        for runway_id, airport_id, ident in connection.execute("SELECT ID, AirportID, Ident FROM Runways")
    }
    existing = {
        (str(icao), str(proc), str(name), str(runway or ""))
        for icao, proc, name, runway in connection.execute("SELECT ICAO, Proc, Name, Rwy FROM Terminals")
    }
    inserted_terminals = 0
    inserted_legs = 0
    rejected: list[dict[str, object]] = []
    deferred_holdings: list[dict[str, object]] = []
    waypoint_resolutions, waypoint_failures = _terminal_waypoint_resolutions(connection, model)
    for segment in model.procedure_segments:
        try:
            procedure_type, name, runway = fenix_terminal_identity(segment)
        except ValueError as error:
            rejected.append({"airport": segment.airport, "label": segment.label, "reason": str(error), "source": asdict(segment.source)})
            continue
        if procedure_type == "3":
            continue
        identity = (segment.airport, procedure_type, name, runway)
        if identity in existing:
            continue
        airport_id = airport_ids.get(segment.airport)
        runway_id = runway_ids.get((airport_id, runway)) if airport_id is not None else None
        if airport_id is None or runway_id is None:
            rejected.append({"airport": segment.airport, "label": segment.label, "reason": "missing target airport or runway", "source": asdict(segment.source)})
            continue
        transition = f"RW{runway}"
        legs = []
        for leg in segment.legs:
            if leg.leg_type == "HM":
                deferred_holdings.append({
                    "airport": segment.airport, "label": segment.label, "runway": runway,
                    "fix_ident": leg.fix_ident, "raw": leg.raw, "source": asdict(segment.source),
                })
            else:
                legs.append(leg)
        if not legs:
            rejected.append({"airport": segment.airport, "label": segment.label, "reason": "only unprojectable holding legs", "source": asdict(segment.source)})
            continue
        try:
            projections = []
            for leg in legs:
                key = (segment.airport, leg.fix_ident) if leg.fix_ident else None
                center_key = (segment.airport, leg.center_ident) if leg.center_ident else None
                if key and key in waypoint_failures:
                    raise ConversionBlocked(waypoint_failures[key])
                if key and key not in waypoint_resolutions:
                    raise ConversionBlocked(f"terminal fix {segment.airport}/{leg.fix_ident} has no source coordinate evidence")
                if center_key and center_key in waypoint_failures:
                    raise ConversionBlocked(waypoint_failures[center_key])
                if center_key and center_key not in waypoint_resolutions:
                    raise ConversionBlocked(f"terminal RF center {segment.airport}/{leg.center_ident} has no source coordinate evidence")
                projections.append(project_database_terminal_leg(
                    leg, procedure_type, transition, waypoint_resolutions[key] if key else None,
                    waypoint_resolutions[center_key] if center_key else None,
                ))
        except (ConversionBlocked, ValueError) as error:
            rejected.append({"airport": segment.airport, "label": segment.label, "reason": str(error), "source": asdict(segment.source)})
            continue
        connection.execute(
            "INSERT INTO Terminals VALUES (?,?,?,?,?,?,?,?,?)",
            (next_terminal_id, airport_id, procedure_type, segment.airport, name, name, runway, runway_id, 0),
        )
        for projection in projections:
            connection.execute(
                "INSERT INTO TerminalLegsEx VALUES (?,?,?,?)",
                (next_leg_id, 0, projection.speed_limit, projection.speed_limit_description),
            )
            connection.execute(
                "INSERT INTO TerminalLegs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    next_leg_id, next_terminal_id, projection.type_code, projection.transition, projection.track_code,
                    projection.waypoint_id, projection.waypoint_latitude, projection.waypoint_longitude,
                    projection.turn_direction, None, None, None, None, None, projection.course, None,
                    projection.altitude, None, projection.center_id, projection.center_latitude, projection.center_longitude, projection.waypoint_description,
                ),
            )
            next_leg_id += 1
            inserted_legs += 1
        existing.add(identity)
        next_terminal_id += 1
        inserted_terminals += 1
    return {
        "terminal_procedures_inserted": inserted_terminals,
        "terminal_legs_inserted": inserted_legs,
        "terminal_procedure_rejections": rejected,
        "terminal_holding_rejections": deferred_holdings,
    }


def _iap_chart_roles(model: NavModel, segment: ProcedureSegment) -> dict[str, set[str]]:
    """Return explicit IF/FAF/MAPT labels for one uniquely named approach chart."""
    charts = [
        chart for chart in model.procedure_charts
        if chart.airport == segment.airport
        and chart.chart_type == "instrument-approach-index"
        and segment.runway in chart.runways
        and segment.label in approach_procedure_name_candidates(chart.chart_name, chart.runways, segment.airport)
    ]
    if len(charts) != 1:
        raise ConversionBlocked(f"IAP {segment.airport}/{segment.label} has {len(charts)} matching approach charts")
    roles: dict[str, set[str]] = {}
    for route_fix in charts[0].route_fixes:
        roles.setdefault(route_fix.ident, set()).add(route_fix.role)
    return roles


def _iap_sections(
    groups: dict[tuple[str, str, str], list[ProcedureSegment]],
    airport: str,
    label: str,
    runway: str,
    segments: list[ProcedureSegment],
) -> tuple[list[ProcedureSegment], list[ProcedureSegment], list[ProcedureSegment]]:
    """Return IAP sections, including same-page unlabelled shared sections.

    CAAC coding tables may print variant main approaches as ``R01-Y`` and
    ``R01-Z`` while their shared transition and missed sections remain under
    the literal ``R01`` heading.  The association is allowed only on the same
    source page, never by airport-wide name matching.
    """
    primary = [segment for segment in segments if segment.kind == "\u8fdb\u8fd1"]
    transitions = [segment for segment in segments if segment.kind == "\u8fdb\u8fd1\u8fc7\u6e21"]
    missed = [segment for segment in segments if segment.kind == "\u590d\u98de"]
    if "-" not in label or len(primary) != 1:
        return transitions, primary, missed
    base_label = label.split("-", 1)[0]
    source = primary[0].source
    shared = groups.get((airport, base_label, runway), [])
    transitions.extend(
        segment for segment in shared
        if segment.kind == "\u8fdb\u8fd1\u8fc7\u6e21" and segment.source.file == source.file and segment.source.page == source.page
    )
    missed.extend(
        segment for segment in shared
        if segment.kind == "\u590d\u98de" and segment.source.file == source.file and segment.source.page == source.page
    )
    return transitions, primary, missed


def _insert_iap_procedures(connection: sqlite3.Connection, model: NavModel) -> dict[str, object]:
    """Insert source-complete IAP plans assembled from their printed sections.

    A Fenix IAP requires a MAP row in addition to the printed procedure legs.
    It is emitted only when the selected approach chart explicitly marks the
    final main-approach fix as MAPT, so its position remains source-backed.
    """
    groups: dict[tuple[str, str, str], list[ProcedureSegment]] = {}
    for segment in model.procedure_segments:
        if segment.kind in _IAP_KINDS:
            groups.setdefault((segment.airport, segment.label, segment.runway), []).append(segment)
    next_terminal_id = _next_id(connection, "Terminals")
    next_leg_id = _next_id(connection, "TerminalLegs")
    airport_ids = dict(connection.execute("SELECT ICAO, ID FROM Airports"))
    runway_ids = {(airport_id, ident): runway_id for runway_id, airport_id, ident in connection.execute("SELECT ID, AirportID, Ident FROM Runways")}
    existing = {(str(icao), str(proc), str(name), str(runway or "")) for icao, proc, name, runway in connection.execute("SELECT ICAO, Proc, Name, Rwy FROM Terminals")}
    waypoint_resolutions, waypoint_failures = _terminal_waypoint_resolutions(connection, model)
    inserted_terminals = 0
    inserted_legs = 0
    rejected: list[dict[str, object]] = []

    for (airport, label, runway), segments in groups.items():
        identity = (airport, "3", label, runway)
        if identity in existing:
            continue
        transitions, primary, missed = _iap_sections(groups, airport, label, runway, segments)
        source = primary[0].source if primary else segments[0].source
        try:
            if len(primary) != 1 or not primary[0].legs:
                raise ConversionBlocked("IAP requires exactly one non-empty main-approach section")
            roles = _iap_chart_roles(model, primary[0])
            map_leg = primary[0].legs[-1]
            if map_leg.fix_ident is None or "MAPT" not in roles.get(map_leg.fix_ident, set()):
                raise ConversionBlocked("IAP main approach does not end at an explicit MAPT fix")
            airport_id = airport_ids.get(airport)
            runway_id = runway_ids.get((airport_id, runway)) if airport_id is not None else None
            if airport_id is None or runway_id is None:
                raise ConversionBlocked("missing target airport or runway")
            projected: list[tuple[FenixTerminalLegProjection, float | None]] = []

            def append_leg(leg: ChartTerminalLeg, transition: str | None, description: str, vnav: float | None = None) -> None:
                key = (airport, leg.fix_ident) if leg.fix_ident else None
                center_key = (airport, leg.center_ident) if leg.center_ident else None
                if key and key in waypoint_failures:
                    raise ConversionBlocked(waypoint_failures[key])
                if center_key and center_key in waypoint_failures:
                    raise ConversionBlocked(waypoint_failures[center_key])
                if key and key not in waypoint_resolutions:
                    raise ConversionBlocked(f"terminal fix {airport}/{leg.fix_ident} has no source coordinate evidence")
                if center_key and center_key not in waypoint_resolutions:
                    raise ConversionBlocked(f"terminal RF center {airport}/{leg.center_ident} has no source coordinate evidence")
                projected.append((project_database_iap_leg(
                    leg, transition, description,
                    waypoint_resolutions[key] if key else None,
                    waypoint_resolutions[center_key] if center_key else None,
                ), vnav))

            for transition in transitions:
                for index, leg in enumerate(transition.legs):
                    append_leg(leg, transition.transition, "E A" if index == 0 else "EE B")
            for index, leg in enumerate(primary[0].legs):
                if index == 0:
                    append_leg(leg, None, "EI")
                else:
                    role = roles.get(leg.fix_ident or "", set())
                    append_leg(leg, None, "EF" if "FAF" in role else "E", 3.0 if role & {"FAF", "MAPT"} else None)
            map_waypoint = waypoint_resolutions[(airport, map_leg.fix_ident)]
            projected.append((FenixTerminalLegProjection(
                "0", "", map_leg.leg_type, None, map_waypoint[1], map_waypoint[2], None,
                None, "MAP", "GY M", None, None,
            ), 3.0))
            for section in missed:
                for index, leg in enumerate(section.legs):
                    append_leg(leg, None, "E M" if index == 0 else "EE")
        except (ConversionBlocked, ValueError) as error:
            rejected.append({"airport": airport, "label": label, "reason": str(error), "source": asdict(source)})
            continue

        connection.execute("INSERT INTO Terminals VALUES (?,?,?,?,?,?,?,?,?)", (next_terminal_id, airport_id, "3", airport, label, label, runway, runway_id, 0))
        for projection, vnav in projected:
            connection.execute("INSERT INTO TerminalLegsEx VALUES (?,?,?,?)", (next_leg_id, 0, projection.speed_limit, projection.speed_limit_description))
            connection.execute(
                "INSERT INTO TerminalLegs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (next_leg_id, next_terminal_id, projection.type_code, projection.transition or None, projection.track_code,
                 projection.waypoint_id, projection.waypoint_latitude, projection.waypoint_longitude,
                 projection.turn_direction, None, None, None, None, None, projection.course, None,
                 projection.altitude, vnav, projection.center_id, projection.center_latitude, projection.center_longitude, projection.waypoint_description),
            )
            next_leg_id += 1
            inserted_legs += 1
        existing.add(identity)
        next_terminal_id += 1
        inserted_terminals += 1
    return {"terminal_procedures_inserted": inserted_terminals, "terminal_legs_inserted": inserted_legs, "terminal_procedure_rejections": rejected}


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


def _clear_china_airport_domain(connection: sqlite3.Connection) -> dict[str, int]:
    """Remove airport-owned Chinese records without touching global entities.

    This is deliberately kept separate from projection.  A complete regional
    replacement must repopulate ILSes, markers, terminals and their legs from
    source-backed data before it can call this transaction on a candidate.
    """
    prefixes = ("ZB", "ZG", "ZH", "ZJ", "ZL", "ZP", "ZS", "ZU", "ZW", "ZY")
    connection.execute("DROP TABLE IF EXISTS temp._fenix_china_airports")
    connection.execute("DROP TABLE IF EXISTS temp._fenix_china_terminal_legs")
    connection.execute("CREATE TEMP TABLE _fenix_china_airports (ID INTEGER PRIMARY KEY)")
    connection.executemany(
        "INSERT INTO _fenix_china_airports SELECT ID FROM Airports WHERE substr(ICAO, 1, 2)=?",
        ((prefix,) for prefix in prefixes),
    )
    connection.execute(
        "CREATE TEMP TABLE _fenix_china_terminal_legs (ID INTEGER PRIMARY KEY)"
    )
    connection.execute(
        "INSERT INTO _fenix_china_terminal_legs "
        "SELECT legs.ID FROM TerminalLegs AS legs "
        "JOIN Terminals AS terminals ON terminals.ID=legs.TerminalID "
        "WHERE terminals.AirportID IN (SELECT ID FROM _fenix_china_airports)"
    )
    counts = {
        "airports_replaced": int(connection.execute("SELECT count(*) FROM _fenix_china_airports").fetchone()[0]),
        "airport_lookups_removed": 0,
        "runways_removed": 0,
        "terminals_removed": 0,
        "terminal_legs_removed": 0,
        "terminal_leg_extensions_removed": 0,
    }
    # TerminalLegs references both the terminal and its extension row, so the
    # extension rows must be removed only after the primary leg rows.
    cursor = connection.execute("DELETE FROM TerminalLegs WHERE ID IN (SELECT ID FROM _fenix_china_terminal_legs)")
    counts["terminal_legs_removed"] = cursor.rowcount
    cursor = connection.execute("DELETE FROM TerminalLegsEx WHERE ID IN (SELECT ID FROM _fenix_china_terminal_legs)")
    counts["terminal_leg_extensions_removed"] = cursor.rowcount
    cursor = connection.execute("DELETE FROM Terminals WHERE AirportID IN (SELECT ID FROM _fenix_china_airports)")
    counts["terminals_removed"] = cursor.rowcount
    cursor = connection.execute("DELETE FROM Runways WHERE AirportID IN (SELECT ID FROM _fenix_china_airports)")
    counts["runways_removed"] = cursor.rowcount
    cursor = connection.execute("DELETE FROM AirportLookup WHERE ID IN (SELECT ID FROM _fenix_china_airports)")
    counts["airport_lookups_removed"] = cursor.rowcount
    connection.execute("DELETE FROM Airports WHERE ID IN (SELECT ID FROM _fenix_china_airports)")
    connection.execute("DROP TABLE temp._fenix_china_terminal_legs")
    connection.execute("DROP TABLE temp._fenix_china_airports")
    return counts


def _insert_ilses(connection: sqlite3.Connection, model: NavModel, permitted_airports: set[str] | None = None) -> dict[str, object]:
    """Append only complete, source-backed ILS rows in deterministic order."""
    airport_ids = dict(connection.execute("SELECT ICAO, ID FROM Airports"))
    runway_ids = {
        (airport_id, ident): runway_id
        for runway_id, airport_id, ident in connection.execute("SELECT ID, AirportID, Ident FROM Runways")
    }
    existing = {
        (int(runway_id), str(ident), int(frequency))
        for runway_id, ident, frequency in connection.execute("SELECT RunwayID, Ident, Freq FROM ILSes")
    }
    next_ils_id = _next_id(connection, "ILSes")
    inserted = 0
    rejected: list[dict[str, object]] = []
    for ils in sorted(model.ilses, key=lambda item: (item.airport, item.runway, item.ident, item.frequency_mhz)):
        if permitted_airports is not None and ils.airport not in permitted_airports:
            continue
        airport_id = airport_ids.get(ils.airport)
        runway_id = runway_ids.get((airport_id, ils.runway)) if airport_id is not None else None
        if runway_id is None:
            rejected.append({"airport": ils.airport, "runway": ils.runway, "ident": ils.ident, "reason": "missing target runway", "source": asdict(ils.source)})
            continue
        try:
            projection = project_ad219_ils(ils)
        except ConversionBlocked as error:
            rejected.append({"airport": ils.airport, "runway": ils.runway, "ident": ils.ident, "reason": str(error), "source": asdict(ils.source)})
            continue
        identity = (runway_id, projection.ident, projection.frequency)
        if identity in existing:
            continue
        connection.execute(
            "INSERT INTO ILSes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                next_ils_id, runway_id, projection.frequency, projection.glide_slope_angle,
                projection.latitude, projection.longitude, projection.category, projection.ident,
                projection.localizer_course, projection.crossing_height, 1, projection.elevation_feet,
            ),
        )
        existing.add(identity)
        next_ils_id += 1
        inserted += 1
    return {"ilses_inserted": inserted, "ils_rejections": rejected}


def _insert_model(connection: sqlite3.Connection, model: NavModel) -> dict[str, object]:
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
        name = airport.name if airport.name.isascii() else romanize_name(airport.name.replace("/", " "))
        connection.execute("INSERT INTO Airports VALUES (?,?,?,?,?,?,?,?,?,?,?)", (airport_id, name, airport.icao, None,
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
    if model.ilses:
        counts.update(_insert_ilses(
            connection, model,
            {model.airports[key].icao for key in inserted_airports},
        ))
    if model.terminal_waypoints or model.waypoints or model.navaids:
        counts.update(_insert_waypoints(connection, model, navaid_additions))
    if model.procedure_segments:
        terminal_counts = _insert_terminal_procedures(connection, model)
        iap_counts = _insert_iap_procedures(connection, model)
        terminal_counts["terminal_procedures_inserted"] += iap_counts["terminal_procedures_inserted"]
        terminal_counts["terminal_legs_inserted"] += iap_counts["terminal_legs_inserted"]
        terminal_counts["terminal_procedure_rejections"].extend(iap_counts["terminal_procedure_rejections"])
        counts.update(terminal_counts)
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
        terminal_rejections = counts.pop("terminal_procedure_rejections", [])
        holding_rejections = counts.pop("terminal_holding_rejections", [])
        ils_rejections = counts.pop("ils_rejections", [])
        incomplete = bool(model.rejected_procedures or model.rejected_records or terminal_rejections or holding_rejections or ils_rejections)
        if (terminal_rejections or holding_rejections or ils_rejections) and not allow_incomplete:
            raise ConversionBlocked(
                f"terminal projection rejected {len(terminal_rejections)} procedures, "
                f"{len(holding_rejections)} holding legs and {len(ils_rejections)} ILS rows"
            )
        report = {"status": "incomplete" if incomplete else "candidate", "test_build": True, "deployable": not incomplete,
                  "profile": profile["config"], "counts": counts, "rejected_procedures": [asdict(item) for item in model.rejected_procedures],
                  "rejected_records": [asdict(item) for item in model.rejected_records],
                  "terminal_procedure_rejections": terminal_rejections,
                  "terminal_holding_rejections": holding_rejections,
                  "ils_rejections": ils_rejections,
                  "terminal_waypoint_evidence": len(model.terminal_waypoints),
                  "terminal_database_chart_evidence": len(model.procedure_charts),
                  "terminal_database_leg_evidence": sum(len(chart.terminal_legs) for chart in model.procedure_charts),
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
              "terminal_waypoint_evidence": len(model.terminal_waypoints),
              "terminal_database_chart_evidence": len(model.procedure_charts),
              "terminal_database_leg_evidence": sum(len(chart.terminal_legs) for chart in model.procedure_charts)}
    target = output / "conversion-report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
