import sqlite3
from pathlib import Path

from navdata_converter.model import NavModel, SourceRef, TerminalWaypoint
from navdata_converter.reference_delta import inspect_reference_delta, inspect_terminal_waypoint_coverage


def _database(path, rows):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE Records (ID INTEGER, Value TEXT)")
        connection.executemany("INSERT INTO Records VALUES (?, ?)", rows)


def test_reports_added_ids_in_reference_physical_order(tmp_path):
    official = tmp_path / "official.db3"
    reference = tmp_path / "reference.db3"
    _database(official, [(1, "base"), (2, "same")])
    _database(reference, [(1, "base"), (2, "same"), (5, "first"), (3, "second")])

    report = inspect_reference_delta(official, reference)

    assert report["tables"]["Records"] == {
        "base_rows": 2,
        "reference_rows": 4,
        "id_diagnostic": True,
        "base_max_id": 2,
        "added_rows": 2,
        "added_ids_in_physical_order": [5, 3],
        "added_ids_tail": [5, 3],
        "physical_id_order_ascending": False,
        "changed_existing_rows": 0,
        "changed_id_sample": [],
    }


def test_terminal_coordinate_coverage_requires_matching_ident_and_location(tmp_path):
    official = tmp_path / "official.db3"
    reference = tmp_path / "reference.db3"
    _database(official, [])
    _database(reference, [])
    for database, rows in ((official, [(1, "BASE", 10.0, 20.0)]), (reference, [(1, "BASE", 10.0, 20.0), (2, "NEW", 30.0, 40.0)])):
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TABLE Records")
            connection.execute("CREATE TABLE Waypoints (ID INTEGER, Ident TEXT, Latitude REAL, Longtitude REAL)")
            connection.executemany("INSERT INTO Waypoints VALUES (?, ?, ?, ?)", rows)
    source = SourceRef("Terminal/ZBAD/ZBAD-4Y01.pdf", 1, 1, "hash")
    model = NavModel(Path("."), terminal_waypoints=[
        TerminalWaypoint("a", "ZBAD", "BASE", 10.0, 20.0, source),
        TerminalWaypoint("b", "ZBAD", "NEW", 30.0, 40.0, source),
        TerminalWaypoint("c", "ZBAD", "NEW", 31.0, 40.0, source),
    ])

    report = inspect_terminal_waypoint_coverage(model, official, reference)

    assert report["unique_physical_points"] == 3
    assert report["official_matches"] == 1
    assert report["reference_matches"] == 2
    assert report["reference_new_matches"] == 1
    assert report["reference_missing_sample"] == [{
        "airport": "ZBAD", "ident": "NEW", "latitude": 31.0, "longitude": 40.0, "source": "Terminal/ZBAD/ZBAD-4Y01.pdf",
    }]
