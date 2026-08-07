import sqlite3
from pathlib import Path

from navdata_converter.model import ChartTerminalLeg, NavModel, ProcedureChart, SourceRef, TerminalWaypoint
from navdata_converter.reference_delta import inspect_approach_chart_coverage, inspect_database_fix_coverage, inspect_reference_delta, inspect_terminal_waypoint_coverage


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
    assert report["reference_renamed_or_collocated"] == 0
    assert report["reference_unrepresented"] == 1
    assert report["reference_missing_sample"] == [{
        "airport": "ZBAD", "ident": "NEW", "latitude": 31.0, "longitude": 40.0, "source": "Terminal/ZBAD/ZBAD-4Y01.pdf",
    }]


def test_approach_chart_coverage_compares_indexed_runways_to_fenix_proc_three(tmp_path):
    official = tmp_path / "official.db3"
    reference = tmp_path / "reference.db3"
    for database, rows in ((official, [(2, 3, "ZYYK", "22", "R22")]), (reference, [(1, 3, "ZYYK", "04", "R04"), (2, 3, "ZYYK", "22", "R22")])):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE Terminals (ID INTEGER, Proc INTEGER, ICAO TEXT, Rwy TEXT, Name TEXT)")
            connection.executemany("INSERT INTO Terminals VALUES (?, ?, ?, ?, ?)", rows)
    source = SourceRef("Terminal/ZYYK/ZYYK-5A.pdf", 1, 1, "hash")
    model = NavModel(Path("."), procedure_charts=[
        ProcedureChart("ZYYK", "ZYYK-5A.pdf", 1, "instrument-approach-index", "ILS Z RWY04", "text", (), ("04",), (), (), (), source),
    ])

    report = inspect_approach_chart_coverage(model, official, reference)

    assert report == {
        "evidence_pages": 1,
        "evidence_pairs": 1,
        "reference_pairs": 2,
        "matched_pairs": 1,
        "evidence_without_reference": [],
        "reference_without_evidence": [{"airport": "ZYYK", "runway": "22"}],
        "reference_non_runway_name_count": 0,
        "reference_non_runway_name_sample": [],
        "name_candidates": 2,
        "reference_names": 2,
        "matched_names": 0,
        "candidate_names_without_reference": [
            {"airport": "ZYYK", "runway": "04", "name": "I04"},
            {"airport": "ZYYK", "runway": "04", "name": "I04-Z"},
        ],
        "reference_names_without_candidate": [
            {"airport": "ZYYK", "runway": "04", "name": "R04"},
            {"airport": "ZYYK", "runway": "22", "name": "R22"},
        ],
        "delta_names": 1,
        "matched_delta_names": 0,
        "delta_names_without_candidate": [{"airport": "ZYYK", "runway": "04", "name": "R04"}],
    }


def test_database_fix_coverage_requires_database_leg_and_coordinate_page_identity(tmp_path):
    official = tmp_path / "official.db3"
    reference = tmp_path / "reference.db3"
    for database, rows in ((official, [(1, "BASE", 1.0, 1.0)]), (reference, [(1, "BASE", 1.0, 1.0), (2, "FIX", 40.624444, 122.418333)])):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE Waypoints (ID INTEGER, Ident TEXT, Latitude REAL, Longtitude REAL)")
            connection.executemany("INSERT INTO Waypoints VALUES (?, ?, ?, ?)", rows)
    source = SourceRef("Terminal/ZYYK/ZYYK-4Y01.pdf", page=1, sha256="hash")
    chart = ProcedureChart("ZYYK", "ZYYK-4Z01.pdf", 1, "terminal-database-coding", "database", "text", (), (), (), (ChartTerminalLeg("P389-09D", "04", "CF", "FIX", "CF FIX"),), (), source)
    model = NavModel(Path("."), terminal_waypoints=[TerminalWaypoint("source", "ZYYK", "FIX", 40.624444, 122.418333, source)], procedure_charts=[chart])

    assert inspect_database_fix_coverage(model, official, reference) == {"database_fix_keys": 1, "coordinate_points": 1, "reference_added_matches": 1}
