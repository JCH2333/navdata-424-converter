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
    frequency: int
    magnetic_variation: float
    elevation_ft: int
    source: SourceRef


@dataclass(frozen=True)
class Waypoint:
    key: str
    ident: str
    name: str
    latitude: float
    longitude: float
    source: SourceRef


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


@dataclass
class NavModel:
    root: Path
    airports: dict[str, Airport] = field(default_factory=dict)
    runways: list[Runway] = field(default_factory=list)
    navaids: list[Navaid] = field(default_factory=list)
    waypoints: list[Waypoint] = field(default_factory=list)
    airway_legs: list[AirwayLeg] = field(default_factory=list)
    rejected_procedures: list[RejectedProcedure] = field(default_factory=list)
