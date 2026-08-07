from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


CN_PREFIXES = ("ZB", "ZG", "ZH", "ZJ", "ZL", "ZP", "ZS", "ZU", "ZW", "ZY")


def is_china_icao(icao: str) -> bool:
    return (icao or "").upper()[:2] in CN_PREFIXES


@dataclass(frozen=True)
class SourceRef:
    file: str
    row: int | None = None
    page: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class Airport:
    key: str
    icao: str
    name: str
    latitude: float
    longitude: float
    elevation_ft: int
    transition_altitude: int
    transition_level: int
    source: SourceRef


@dataclass(frozen=True)
class Runway:
    key: str
    airport_key: str
    ident: str
    true_heading: float
    length_ft: int
    width_ft: int
    surface: str
    elevation_ft: int
    source: SourceRef


@dataclass(frozen=True)
class Navaid:
    key: str
    ident: str
    kind: str
    name: str
    latitude: float
    longitude: float
    frequency: float
    magnetic_variation: float
    elevation_ft: int
    country: str
    source: SourceRef


@dataclass(frozen=True)
class Waypoint:
    key: str
    ident: str
    name: str
    latitude: float
    longitude: float
    source: SourceRef
    country: str = ""


@dataclass(frozen=True)
class TerminalWaypoint:
    """A terminal waypoint printed on an indexed coordinate-page PDF.

    This stays separate from structured designated points until the Fenix
    adapter has resolved physical identity and its deterministic ID phase.
    """

    key: str
    airport: str
    ident: str
    latitude: float
    longitude: float
    source: SourceRef
    country: str = ""


@dataclass(frozen=True)
class AirwayLeg:
    airway: str
    sequence: int
    start_ident: str
    end_ident: str
    source: SourceRef


@dataclass(frozen=True)
class RejectedProcedure:
    airport: str
    chart: str
    reason: str
    source: SourceRef


@dataclass(frozen=True)
class RejectedRecord:
    kind: str
    key: str
    reason: str
    source: SourceRef


@dataclass(frozen=True)
class ProcedureChart:
    airport: str
    filename: str
    page: int
    chart_type: str
    chart_name: str
    text_sha256: str
    procedure_labels: tuple[str, ...]
    runways: tuple[str, ...]
    waypoints: tuple[str, ...]
    terminal_legs: tuple["ChartTerminalLeg", ...]
    fix_coordinates: tuple["ChartFixCoordinate", ...]
    source: SourceRef
    route_fixes: tuple["ChartRouteFix", ...] = ()


@dataclass(frozen=True)
class ChartFixCoordinate:
    """A coordinate observed in a chart text layer, not an inferred procedure leg."""

    ident: str | None
    latitude: float
    longitude: float
    raw: str


@dataclass(frozen=True)
class ChartTerminalLeg:
    procedure_label: str
    runway: str
    leg_type: str
    fix_ident: str | None
    raw: str
    procedure_kind: str = ""
    course_degrees: float | None = None
    altitude_meters: float | None = None
    turn_direction: str | None = None
    speed_limit_knots: int | None = None
    transition: str = ""


@dataclass(frozen=True)
class ChartRouteFix:
    """A fix explicitly paired with a printed approach-route role."""

    ident: str
    role: str


@dataclass
class NavModel:
    root: Path
    airports: dict[str, Airport] = field(default_factory=dict)
    runways: list[Runway] = field(default_factory=list)
    navaids: list[Navaid] = field(default_factory=list)
    waypoints: list[Waypoint] = field(default_factory=list)
    terminal_waypoints: list[TerminalWaypoint] = field(default_factory=list)
    airway_legs: list[AirwayLeg] = field(default_factory=list)
    rejected_records: list[RejectedRecord] = field(default_factory=list)
    rejected_procedures: list[RejectedProcedure] = field(default_factory=list)
    procedure_charts: list[ProcedureChart] = field(default_factory=list)
