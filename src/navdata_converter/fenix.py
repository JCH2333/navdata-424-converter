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
        connection.execute("INSERT INTO Runways VALUES (?,?,?,?,?,?,?,?,?,?)", (next_runway, airport_ids[runway.airport_key], runway.ident,
            runway.true_heading, runway.length_ft, runway.width_ft, runway.surface, airport.latitude, airport.longitude, runway.elevation_ft))
        next_runway += 1
        runways += 1
    return {"airports_inserted": len(inserted_airports), "airports_preserved": len(airport_ids) - len(inserted_airports), "runways_inserted": runways}


def convert(official_navdata: Path, model: NavModel, output: Path, reference: Path | None = None, *, allow_incomplete: bool = False) -> dict[str, object]:
    profile = validate_fenix_profile(official_navdata / "nd.db3")
    if model.rejected_procedures and not allow_incomplete:
        raise ConversionBlocked(f"发现 {len(model.rejected_procedures)} 个未可靠解析的程序图表，已拒绝生成候选")
    database = _copy_navdata(official_navdata, output)
    try:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            counts = _insert_model(connection, model)
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        report = {"status": "incomplete" if model.rejected_procedures else "candidate", "test_build": True, "deployable": not model.rejected_procedures,
                  "profile": profile["config"], "counts": counts, "rejected_procedures": [asdict(item) for item in model.rejected_procedures],
                  "reference": str(reference) if reference else None}
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
