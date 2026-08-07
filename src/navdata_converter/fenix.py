from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .model import NavModel, is_china_icao
from .profile import validate_fenix_profile


class ConversionBlocked(RuntimeError):
    pass


def _next_id(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COALESCE(MAX(ID), 0) + 1 FROM {table}").fetchone()[0])


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


def _delete_china(connection: sqlite3.Connection) -> None:
    airport_ids = [row[0] for row in connection.execute("SELECT ID FROM Airports WHERE substr(ICAO, 1, 2) IN ('ZB','ZG','ZH','ZJ','ZL','ZP','ZS','ZU','ZW','ZY')")]
    if not airport_ids:
        return
    placeholders = ",".join("?" for _ in airport_ids)
    terminal_ids = [row[0] for row in connection.execute(f"SELECT ID FROM Terminals WHERE AirportID IN ({placeholders})", airport_ids)]
    if terminal_ids:
        marks = ",".join("?" for _ in terminal_ids)
        leg_ids = [row[0] for row in connection.execute(f"SELECT ID FROM TerminalLegs WHERE TerminalID IN ({marks})", terminal_ids)]
        if leg_ids:
            connection.execute(f"DELETE FROM TerminalLegsEx WHERE ID IN ({','.join('?' for _ in leg_ids)})", leg_ids)
        connection.execute(f"DELETE FROM TerminalLegs WHERE TerminalID IN ({marks})", terminal_ids)
        connection.execute(f"DELETE FROM Terminals WHERE ID IN ({marks})", terminal_ids)
    connection.execute(f"DELETE FROM ILSes WHERE RunwayID IN (SELECT ID FROM Runways WHERE AirportID IN ({placeholders}))", airport_ids)
    connection.execute(f"DELETE FROM Runways WHERE AirportID IN ({placeholders})", airport_ids)
    connection.execute(f"DELETE FROM AirportLookup WHERE ID IN ({placeholders})", airport_ids)
    connection.execute(f"DELETE FROM Airports WHERE ID IN ({placeholders})", airport_ids)


def _insert_model(connection: sqlite3.Connection, model: NavModel) -> dict[str, int]:
    airport_ids: dict[str, int] = {}
    next_airport = _next_id(connection, "Airports")
    for airport in sorted(model.airports.values(), key=lambda item: item.icao):
        airport_id = next_airport
        next_airport += 1
        airport_ids[airport.key] = airport_id
        connection.execute("INSERT INTO Airports VALUES (?,?,?,?,?,?,?,?,?,?,?)", (airport_id, airport.name, airport.icao, None,
            airport.latitude, airport.longitude, airport.elevation_ft, airport.transition_altitude, airport.transition_level, 250, 10000))
        connection.execute("INSERT INTO AirportLookup VALUES (?,?)", (airport.icao, airport_id))
    next_runway = _next_id(connection, "Runways")
    runways = 0
    for runway in sorted(model.runways, key=lambda item: (model.airports[item.airport_key].icao, item.ident)):
        airport = model.airports[runway.airport_key]
        connection.execute("INSERT INTO Runways VALUES (?,?,?,?,?,?,?,?,?,?)", (next_runway, airport_ids[runway.airport_key], runway.ident,
            runway.true_heading, runway.length_ft, runway.width_ft, runway.surface, airport.latitude, airport.longitude, runway.elevation_ft))
        next_runway += 1
        runways += 1
    return {"airports": len(airport_ids), "runways": runways}


def convert(official_navdata: Path, model: NavModel, output: Path, reference: Path | None = None) -> dict[str, object]:
    profile = validate_fenix_profile(official_navdata / "nd.db3")
    if model.rejected_procedures:
        raise ConversionBlocked(f"发现 {len(model.rejected_procedures)} 个未可靠解析的程序图表，已拒绝生成候选")
    database = _copy_navdata(official_navdata, output)
    try:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            _delete_china(connection)
            counts = _insert_model(connection, model)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        report = {"status": "candidate", "test_build": True, "profile": profile["config"], "counts": counts,
                  "rejected_procedures": [], "reference": str(reference) if reference else None}
        (output / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def build_rejection_report(model: NavModel, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "blocked", "test_build": True, "rejected_procedures": [asdict(item) for item in model.rejected_procedures]}
    target = output / "conversion-report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
