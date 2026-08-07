import json
import sqlite3
from pathlib import Path

from navdata_converter.fenix import _insert_model, _insert_waypoints, build_rejection_report, encode_frequency, fenix_procedure_name, fenix_procedure_type, missing_navaids, project_database_terminal_leg, runway_threshold
from navdata_converter.model import Airport, ChartTerminalLeg, Navaid, NavModel, RejectedRecord, Runway, SourceRef, TerminalWaypoint, Waypoint


def test_merge_preserves_existing_airport_and_appends_only_missing_rows(tmp_path):
    db = sqlite3.connect(tmp_path / "test.db3")
    db.executescript("""
        CREATE TABLE Airports (ID INTEGER, Name TEXT, ICAO TEXT, PrimaryID INTEGER, Latitude REAL, Longtitude REAL, Elevation INTEGER, TransitionAltitude INTEGER, TransitionLevel INTEGER, SpeedLimit INTEGER, SpeedLimitAltitude INTEGER);
        CREATE TABLE AirportLookup (extID TEXT, ID INTEGER);
        CREATE TABLE Runways (ID INTEGER, AirportID INTEGER, Ident TEXT, TrueHeading REAL, Length INTEGER, Width INTEGER, Surface TEXT, Latitude REAL, Longtitude REAL, Elevation INTEGER);
        CREATE TABLE Navaids (ID INTEGER, Ident TEXT, Type TEXT, Name TEXT, Freq INTEGER, Channel TEXT, Usage TEXT, Latitude REAL, Longtitude REAL, Elevation INTEGER, SlavedVar REAL, MagneticVariation REAL, Range INTEGER);
        CREATE TABLE NavaidLookup (Ident TEXT, Type TEXT, Country TEXT, NavKeyCode TEXT, ID INTEGER);
        INSERT INTO Airports VALUES (10, 'BASE', 'ZBAA', NULL, 0, 0, 0, 0, 0, 250, 10000);
    """)
    source = SourceRef("fixture.csv", 1)
    model = NavModel(Path("."), airports={
        "old": Airport("old", "ZBAA", "changed", 1, 2, 3, 4, 5, source),
        "new": Airport("new", "ZBCF", "new", 1, 2, 3, 4, 5, source),
    }, runways=[Runway("new-rwy", "new", "03", 30, 1000, 30, "ASP", 3, source)])
    counts = _insert_model(db, model)
    assert counts == {"airports_inserted": 1, "airports_preserved": 1, "runways_inserted": 1, "navaids_inserted": 0}
    assert db.execute("SELECT ID, Name FROM Airports WHERE ICAO='ZBAA'").fetchone() == (10, "BASE")
    assert db.execute("SELECT ID FROM Airports WHERE ICAO='ZBCF'").fetchone() == (11,)
    assert db.execute("SELECT AirportID FROM Runways").fetchone() == (11,)
    db.commit()


def test_fenix_navaid_frequency_uses_observed_bcd_contract():
    assert encode_frequency(112.4, "VOR") == 0x01124000
    assert encode_frequency(495, "NDB") == 0x04950000


def test_fenix_procedure_name_matches_observed_database_labels():
    assert fenix_procedure_name("P389-09D") == "P8909D"
    assert fenix_procedure_name("P528-9ZD") == "P289ZD"
    assert fenix_procedure_name("KAKAT-9ZA") == "KAK9ZA"
    assert fenix_procedure_name("BM-09D") == "BM09D"
    assert fenix_procedure_type("TGO-9ZD", "离场") == "2"
    assert fenix_procedure_type("TGO-9ZA", "进场") == "1"


def test_projects_database_leg_constraints_into_fenix_leg_and_extension_fields():
    cf = ChartTerminalLeg("P389-09D", "04", "CF", "YK551", "CF YK551", course_degrees=37.0, speed_limit_knots=220)
    df = ChartTerminalLeg("P389-09D", "04", "DF", "YK404", "DF YK404", altitude_meters=900.0, turn_direction="L")
    ca = ChartTerminalLeg("P387-09D", "04", "CA", None, "CA", course_degrees=37.0, altitude_meters=300.0, speed_limit_knots=220)

    assert project_database_terminal_leg(cf, "2", "RW04", (327066, 40.624444, 122.418333)).__dict__ == {
        "type_code": "5", "transition": "RW04", "track_code": "CF", "waypoint_id": 327066,
        "waypoint_latitude": 40.624444, "waypoint_longitude": 122.418333, "turn_direction": None,
        "course": 37.0, "altitude": None, "waypoint_description": "E", "speed_limit": 220.0,
        "speed_limit_description": "B",
    }
    assert project_database_terminal_leg(df, "2", "RW04", (327054, 40.522222, 122.343889)).altitude == "3000A"
    assert project_database_terminal_leg(ca, "2", "RW04").altitude == "1000A"


def test_runway_threshold_uses_reciprocal_heading_from_airport_reference_point():
    latitude, longitude = runway_threshold(40.5425, 122.3586111111111, 29, 8202)

    assert round(latitude, 4) == 40.5327
    assert round(longitude, 4) == 122.3514


def test_missing_navaids_matches_existing_facilities_by_location_not_lookup_country(tmp_path):
    connection = sqlite3.connect(tmp_path / "navaids.db3")
    connection.execute("CREATE TABLE Navaids (ID INTEGER, Ident TEXT, Type TEXT, Latitude REAL, Longtitude REAL)")
    connection.execute("INSERT INTO Navaids VALUES (1, 'CHF', '4', 42.19, 118.8117)")
    source = SourceRef("VOR.csv", 2)
    existing = Navaid("old", "CHF", "VOR", "", 42.1901, 118.8118, 113.5, 0, 0, "ZB", source)
    foreign_collision = Navaid("new", "GAZ", "VOR", "", 38.8172, 100.6331, 113.6, 0, 0, "ZL", source)

    assert missing_navaids(connection, [existing, foreign_collision]) == [foreign_collision]


def test_rejection_report_preserves_unmapped_source_record(tmp_path):
    model = NavModel(tmp_path, rejected_records=[RejectedRecord("VOR", "TD", "unmapped country", SourceRef("VOR.csv", 13))])

    report = json.loads(build_rejection_report(model, tmp_path / "report").read_text(encoding="utf-8"))

    assert report["rejected_records"] == [{"kind": "VOR", "key": "TD", "reason": "unmapped country", "source": {"file": "VOR.csv", "row": 13, "page": None, "sha256": None}}]


def test_waypoint_phases_keep_designated_collocation_observable(tmp_path):
    connection = sqlite3.connect(tmp_path / "waypoints.db3")
    connection.executescript("""
        CREATE TABLE Waypoints (ID INTEGER, Ident TEXT, Collocated INTEGER, Name TEXT, Latitude REAL, Longtitude REAL, NavaidID INTEGER);
        CREATE TABLE WaypointLookup (Ident TEXT, Country TEXT, ID INTEGER);
        CREATE TABLE Navaids (ID INTEGER, Ident TEXT, Type TEXT, Latitude REAL, Longtitude REAL);
    """)
    connection.execute("INSERT INTO Waypoints VALUES (1, 'OLD', 0, 'OLD', 1, 1, NULL)")
    source = SourceRef("fixture", 1)
    model = NavModel(Path("."), terminal_waypoints=[
        TerminalWaypoint("terminal", "ZBAD", "TERM", 2, 2, source, "ZB"),
        TerminalWaypoint("same-location", "ZBAD", "SKIP", 1, 1, source, "ZB"),
    ], waypoints=[Waypoint("designated", "DES", "DES", 2, 2, source, "ZB")])

    counts = _insert_waypoints(connection, model)

    assert counts == {"terminal_waypoints_inserted": 1, "designated_waypoints_inserted": 1, "navaid_waypoints_inserted": 0}
    assert connection.execute("SELECT ID, Ident, Collocated FROM Waypoints ORDER BY ID").fetchall() == [(1, "OLD", 0), (2, "TERM", 0), (3, "DES", 0)]


def test_designated_waypoint_prefers_nearby_official_record_with_same_ident(tmp_path):
    connection = sqlite3.connect(tmp_path / "designated.db3")
    connection.executescript("""
        CREATE TABLE Waypoints (ID INTEGER, Ident TEXT, Collocated INTEGER, Name TEXT, Latitude REAL, Longtitude REAL, NavaidID INTEGER);
        CREATE TABLE WaypointLookup (Ident TEXT, Country TEXT, ID INTEGER);
        CREATE TABLE Navaids (ID INTEGER, Ident TEXT, Type TEXT, Latitude REAL, Longtitude REAL);
        INSERT INTO Waypoints VALUES (1, 'P290', 0, 'P290', 40.06166667, 119.02833333, NULL);
        INSERT INTO WaypointLookup VALUES ('P290', 'ZB', 1);
    """)
    source = SourceRef("fixture", 1)
    model = NavModel(Path("."), waypoints=[Waypoint("new", "P290", "P290", 40.06222222, 119.02805556, source, "ZB")])

    assert _insert_waypoints(connection, model)["designated_waypoints_inserted"] == 0


def test_designated_reference_compatibility_retains_verified_border_point(tmp_path):
    connection = sqlite3.connect(tmp_path / "border.db3")
    connection.executescript("""
        CREATE TABLE Waypoints (ID INTEGER, Ident TEXT, Collocated INTEGER, Name TEXT, Latitude REAL, Longtitude REAL, NavaidID INTEGER);
        CREATE TABLE WaypointLookup (Ident TEXT, Country TEXT, ID INTEGER);
        CREATE TABLE Navaids (ID INTEGER, Ident TEXT, Type TEXT, Latitude REAL, Longtitude REAL);
        INSERT INTO Waypoints VALUES (1, 'PAPA', 0, 'PAPA', 21.9775, 113.65611111, NULL);
    """)
    source = SourceRef("fixture", 1)
    model = NavModel(Path("."), waypoints=[Waypoint("new", "PAPA", "PAPA", 21.97833333, 113.65666667, source, "CN")])

    assert _insert_waypoints(connection, model)["designated_waypoints_inserted"] == 1
