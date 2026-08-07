from __future__ import annotations

import sqlite3
from pathlib import Path


REQUIRED_TABLES = {
    "config", "Airports", "AirportLookup", "Runways", "Waypoints", "WaypointLookup",
    "Navaids", "NavaidLookup", "Airways", "AirwayLegs", "ILSes", "Holdings",
    "AirportCommunication", "GridMora", "Terminals", "TerminalLegs", "TerminalLegsEx",
}


class ProfileError(RuntimeError):
    pass


def validate_fenix_profile(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ProfileError("Fenix 模板缺少表: " + ", ".join(sorted(missing)))
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        config = dict(connection.execute("SELECT key, val FROM config"))
        columns = {name: [row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')] for name in REQUIRED_TABLES}
    required = {
        "Airports": ["ID", "ICAO", "Latitude", "Longtitude"],
        "Terminals": ["ID", "AirportID", "Proc", "ICAO"],
        "TerminalLegs": ["ID", "TerminalID", "WptID"],
        "TerminalLegsEx": ["ID", "IsFlyOver"],
    }
    for table, expected in required.items():
        if not all(column in columns[table] for column in expected):
            raise ProfileError(f"Fenix 模板 {table} 列不兼容")
    return {"journal_mode": journal_mode, "config": config, "columns": columns}
