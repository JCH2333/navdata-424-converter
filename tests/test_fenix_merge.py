import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from navdata_converter.fenix import ConversionBlocked, _clear_china_airport_domain, _insert_ilses, _insert_model, _insert_terminal_procedures, _insert_waypoints, build_rejection_report, encode_frequency, fenix_procedure_name, fenix_procedure_type, fenix_terminal_identity, missing_navaids, project_ad219_ils, project_database_terminal_leg, resolve_terminal_waypoint, runway_threshold
from navdata_converter.model import Airport, ChartTerminalLeg, Ils, Navaid, NavModel, ProcedureSegment, RejectedRecord, Runway, SourceRef, TerminalWaypoint, Waypoint


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


def test_clears_only_china_airport_domain_in_foreign_key_order(tmp_path):
    connection = sqlite3.connect(tmp_path / "regional-replace.db3")
    connection.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE Airports (ID INTEGER PRIMARY KEY, ICAO TEXT, PrimaryID INTEGER REFERENCES Airports(ID));
        CREATE TABLE AirportLookup (extID TEXT PRIMARY KEY, ID INTEGER REFERENCES Airports(ID));
        CREATE TABLE Runways (ID INTEGER PRIMARY KEY, AirportID INTEGER REFERENCES Airports(ID));
        CREATE TABLE Terminals (ID INTEGER PRIMARY KEY, AirportID INTEGER REFERENCES Airports(ID));
        CREATE TABLE TerminalLegsEx (ID INTEGER PRIMARY KEY);
        CREATE TABLE TerminalLegs (ID INTEGER PRIMARY KEY REFERENCES TerminalLegsEx(ID), TerminalID INTEGER REFERENCES Terminals(ID));
        INSERT INTO Airports VALUES (1, 'ZBAA', NULL), (2, 'KJFK', NULL);
        INSERT INTO AirportLookup VALUES ('ZBAA', 1), ('KJFK', 2);
        INSERT INTO Runways VALUES (10, 1), (20, 2);
        INSERT INTO Terminals VALUES (100, 1), (200, 2);
        INSERT INTO TerminalLegsEx VALUES (1000), (2000);
        INSERT INTO TerminalLegs VALUES (1000, 100), (2000, 200);
    """)

    counts = _clear_china_airport_domain(connection)

    assert counts == {
        "airports_replaced": 1,
        "airport_lookups_removed": 1,
        "runways_removed": 1,
        "terminals_removed": 1,
        "terminal_legs_removed": 1,
        "terminal_leg_extensions_removed": 1,
    }
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("SELECT ID FROM Airports").fetchall() == [(2,)]
    assert connection.execute("SELECT ID FROM AirportLookup").fetchall() == [(2,)]
    assert connection.execute("SELECT ID FROM Runways").fetchall() == [(20,)]
    assert connection.execute("SELECT ID FROM Terminals").fetchall() == [(200,)]
    assert connection.execute("SELECT ID FROM TerminalLegs").fetchall() == [(2000,)]
    assert connection.execute("SELECT ID FROM TerminalLegsEx").fetchall() == [(2000,)]


def test_fenix_navaid_frequency_uses_observed_bcd_contract():
    assert encode_frequency(112.4, "VOR") == 0x01124000
    assert encode_frequency(111.55, "VOR") == 0x01115500
    assert encode_frequency(108.950, "VOR") == 0x01089500
    assert encode_frequency(495, "NDB") == 0x04950000


def test_projects_complete_ad219_ils_using_observed_fenix_units():
    source = SourceRef("Terminal/ZBCF/赤峰玉龙.pdf", page=12, sha256="hash")
    ils = Ils("ZBCF", "21", "ICF", 108.5, "I", 42.1436666667, 118.8319722222, 212.0, 3.2, 15.0, 42.1684, 118.8440, 42.1684, 118.8439, 616.0, source)

    assert project_ad219_ils(ils).__dict__ == {
        "frequency": 0x01085000, "glide_slope_angle": 3.2,
        "latitude": 42.143667, "longitude": 118.831972,
        "category": "1", "ident": "ICF", "localizer_course": 212.0,
        "crossing_height": "50", "elevation_feet": 2021,
    }
    assert project_ad219_ils(replace(ils, crossing_height_meters=16.2)).crossing_height == "50"
    assert project_ad219_ils(replace(ils, dme_elevation_meters=26.0)).elevation_feet == 86


def test_inserts_only_complete_source_backed_ils_rows(tmp_path):
    connection = sqlite3.connect(tmp_path / "ilses.db3")
    connection.executescript("""
        CREATE TABLE Airports (ID INTEGER, ICAO TEXT);
        CREATE TABLE Runways (ID INTEGER, AirportID INTEGER, Ident TEXT);
        CREATE TABLE ILSes (ID INTEGER, RunwayID INTEGER, Freq INTEGER, GsAngle REAL, Latitude REAL, Longtitude REAL, Category TEXT, Ident TEXT, LocCourse REAL, CrossingHeight TEXT, HasDme INTEGER, Elevation INTEGER);
        INSERT INTO Airports VALUES (10, 'ZBCF');
        INSERT INTO Runways VALUES (20, 10, '21');
    """)
    source = SourceRef("Terminal/ZBCF/赤峰玉龙.pdf", page=12, sha256="hash")
    complete = Ils("ZBCF", "21", "ICF", 108.5, "I", 42.1436666667, 118.8319722222, 212.0, 3.2, 15.0, 42.1684, 118.8440, 42.1684, 118.8439, 616.0, source)
    missing_dme = Ils("ZBCF", "21", "BAD", 108.7, "I", 42.0, 118.0, 212.0, 3.0, 15.0, None, None, None, None, None, source)

    result = _insert_ilses(connection, NavModel(tmp_path, ilses=[complete, missing_dme]))

    assert result["ilses_inserted"] == 1
    assert result["ils_rejections"] == [{"airport": "ZBCF", "runway": "21", "ident": "BAD", "reason": "ILS ZBCF/21/BAD missing DME elevation", "source": source.__dict__}]
    assert connection.execute("SELECT RunwayID, Freq, GsAngle, Latitude, Longtitude, Category, Ident, LocCourse, CrossingHeight, HasDme, Elevation FROM ILSes").fetchall() == [
        (20, 0x01085000, 3.2, 42.143667, 118.831972, "1", "ICF", 212.0, "50", 1, 2021),
    ]


def test_ils_projection_can_be_limited_to_new_airports(tmp_path):
    connection = sqlite3.connect(tmp_path / "limited-ilses.db3")
    connection.executescript("""
        CREATE TABLE Airports (ID INTEGER, ICAO TEXT);
        CREATE TABLE Runways (ID INTEGER, AirportID INTEGER, Ident TEXT);
        CREATE TABLE ILSes (ID INTEGER, RunwayID INTEGER, Freq INTEGER, GsAngle REAL, Latitude REAL, Longtitude REAL, Category TEXT, Ident TEXT, LocCourse REAL, CrossingHeight TEXT, HasDme INTEGER, Elevation INTEGER);
        INSERT INTO Airports VALUES (10, 'ZBCF'), (11, 'ZBAA');
        INSERT INTO Runways VALUES (20, 10, '21'), (21, 11, '01');
    """)
    source = SourceRef("fixture.pdf", page=1, sha256="hash")
    def row(airport, runway, ident):
        return Ils(airport, runway, ident, 108.5, "I", 42.1, 118.8, 212.0, 3.0, 15.0, 42.2, 118.9, 42.2, 118.9, 616.0, source)

    result = _insert_ilses(connection, NavModel(tmp_path, ilses=[row("ZBCF", "21", "ICF"), row("ZBAA", "01", "INJ")]), {"ZBCF"})

    assert result == {"ilses_inserted": 1, "ils_rejections": []}
    assert connection.execute("SELECT RunwayID, Ident FROM ILSes").fetchall() == [(20, "ICF")]


def test_fenix_procedure_name_matches_observed_database_labels():
    assert fenix_procedure_name("P389-09D") == "P8909D"
    assert fenix_procedure_name("P528-9ZD") == "P289ZD"
    assert fenix_procedure_name("KAKAT-9ZA") == "KAK9ZA"
    assert fenix_procedure_name("BM-09D") == "BM09D"
    assert fenix_procedure_type("TGO-9ZD", "离场") == "2"
    assert fenix_procedure_type("TGO-9ZA", "进场") == "1"


def test_database_approach_segments_keep_explicit_fenix_variant_identity():
    source = SourceRef("Terminal/ZBHZ/ZBHZ-4Z02.pdf", 1, 1, "hash")
    approach = ProcedureSegment("ZBHZ", "R29", "进近", "29", "", (), source)
    variant = ProcedureSegment("ZBMZ", "R30-Z", "进近", "30", "", (), source)
    missed_variant = ProcedureSegment("ZBMZ", "R30-Y", "复飞", "30", "", (), source)
    departure = ProcedureSegment("ZYYK", "BM-09D", "离场", "04", "", (), source)

    assert fenix_terminal_identity(approach) == ("3", "R29", "29")
    assert fenix_terminal_identity(variant) == ("3", "R30-Z", "30")
    assert fenix_terminal_identity(missed_variant) == ("3", "R30-Y", "30")
    assert fenix_terminal_identity(departure) == ("2", "BM09D", "04")


def test_projects_database_leg_constraints_into_fenix_leg_and_extension_fields():
    cf = ChartTerminalLeg("P389-09D", "04", "CF", "YK551", "CF YK551", course_degrees=37.0, speed_limit_knots=220)
    df = ChartTerminalLeg("P389-09D", "04", "DF", "YK404", "DF YK404", altitude_meters=900.0, turn_direction="L")
    ca = ChartTerminalLeg("P387-09D", "04", "CA", None, "CA", course_degrees=37.0, altitude_meters=300.0, speed_limit_knots=220)

    assert project_database_terminal_leg(cf, "2", "RW04", (327066, 40.624444, 122.418333)).__dict__ == {
        "type_code": "5", "transition": "RW04", "track_code": "CF", "waypoint_id": 327066,
        "waypoint_latitude": 40.624444, "waypoint_longitude": 122.418333, "turn_direction": None,
        "course": 37.0, "altitude": None, "waypoint_description": "E", "speed_limit": 220.0,
        "speed_limit_description": "B", "center_id": None, "center_latitude": None, "center_longitude": None,
    }
    assert project_database_terminal_leg(df, "2", "RW04", (327054, 40.522222, 122.343889)).altitude == "3000A"
    assert project_database_terminal_leg(ca, "2", "RW04").altitude == "1000A"
    assert project_database_terminal_leg(ChartTerminalLeg("BM-09D", "04", "IF", "YK551", "IF YK551"), "2", "RW04", (327066, 40.624444, 122.418333)).track_code == "IF"
    rf = ChartTerminalLeg("P363-9D", "10", "RF", "XH604", "RF[XHC20, 4] XH604", "离场", turn_direction="L", center_ident="XHC20")
    assert project_database_terminal_leg(rf, "2", "RW10", (322765, 34.8075, 102.709917), (322766, 34.87325, 102.695861)).center_id == 322766


def test_inserts_fully_resolved_source_sid_with_paired_extension_legs(tmp_path):
    connection = sqlite3.connect(tmp_path / "terminals.db3")
    connection.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE Airports (ID INTEGER PRIMARY KEY, ICAO TEXT);
        CREATE TABLE Runways (ID INTEGER, AirportID INTEGER, Ident TEXT);
        CREATE TABLE Waypoints (ID INTEGER PRIMARY KEY, Ident TEXT, Latitude REAL, Longtitude REAL);
        CREATE TABLE Terminals (ID INTEGER PRIMARY KEY, AirportID INTEGER, Proc TEXT, ICAO TEXT, FullName TEXT, Name TEXT, Rwy TEXT, RwyID INTEGER, IlsID INTEGER);
        CREATE TABLE TerminalLegs (ID INTEGER REFERENCES TerminalLegsEx(ID), TerminalID INTEGER, Type TEXT, Transition TEXT, TrackCode TEXT, WptID INTEGER REFERENCES Waypoints(ID), WptLat REAL, WptLon REAL, TurnDir TEXT, NavID INTEGER, NavLat REAL, NavLon REAL, NavBear REAL, NavDist REAL, Course REAL, Distance REAL, Alt TEXT, Vnav REAL, CenterID INTEGER, CenterLat REAL, CenterLon REAL, WptDescCode TEXT);
        CREATE TABLE TerminalLegsEx (ID INTEGER PRIMARY KEY, IsFlyOver INTEGER, SpeedLimit REAL, SpeedLimitDescription TEXT);
        INSERT INTO Airports VALUES (10, 'ZYYK');
        INSERT INTO Runways VALUES (20, 10, '04');
        INSERT INTO Waypoints VALUES (30, 'YK551', 40.624444, 122.418333);
        INSERT INTO Waypoints VALUES (31, 'YK404', 40.522222, 122.343889);
    """)
    source = SourceRef("Terminal/ZYYK/ZYYK-4Z01.pdf", 1, 1, "hash")
    model = NavModel(tmp_path, terminal_waypoints=[
        TerminalWaypoint("first", "ZYYK", "YK551", 40.624444, 122.418333, source),
        TerminalWaypoint("second", "ZYYK", "YK404", 40.522222, 122.343889, source),
    ], procedure_segments=[
        ProcedureSegment("ZYYK", "BM-09D", "离场", "04", "", (
            ChartTerminalLeg("BM-09D", "04", "CF", "YK551", "CF YK551", "离场", course_degrees=37.0, speed_limit_knots=220),
            ChartTerminalLeg("BM-09D", "04", "DF", "YK404", "DF YK404", "离场", altitude_meters=900.0, turn_direction="L"),
        ), source),
    ])

    counts = _insert_terminal_procedures(connection, model)

    assert counts == {"terminal_procedures_inserted": 1, "terminal_legs_inserted": 2, "terminal_procedure_rejections": [], "terminal_holding_rejections": []}
    assert connection.execute("SELECT ID, AirportID, Proc, Name, Rwy, RwyID FROM Terminals").fetchall() == [(1, 10, "2", "BM09D", "04", 20)]
    assert connection.execute("SELECT ID, TerminalID, Type, Transition, TrackCode, WptID, Course, Alt, WptDescCode FROM TerminalLegs ORDER BY ID").fetchall() == [
        (1, 1, "5", "RW04", "CF", 30, 37.0, None, "E"),
        (2, 1, "5", "RW04", "DF", 31, None, "3000A", "E"),
    ]
    assert connection.execute("SELECT * FROM TerminalLegsEx ORDER BY ID").fetchall() == [(1, 0, 220.0, "B"), (2, 0, None, None)]

    model.procedure_segments.append(ProcedureSegment("ZYYK", "CC-09D", "离场", "04", "", (
        ChartTerminalLeg("CC-09D", "04", "TF", "W", "TF W", "离场"),
    ), source))

    rejected = _insert_terminal_procedures(connection, model)["terminal_procedure_rejections"]

    assert rejected == [{"airport": "ZYYK", "label": "CC-09D", "reason": "terminal fix ZYYK/W has no source coordinate evidence", "source": source.__dict__}]


def test_defers_holding_leg_without_blocking_evidenced_terminal_legs(tmp_path):
    connection = sqlite3.connect(tmp_path / "holding.db3")
    connection.executescript("""
        CREATE TABLE Airports (ID INTEGER, ICAO TEXT);
        CREATE TABLE Runways (ID INTEGER, AirportID INTEGER, Ident TEXT);
        CREATE TABLE Waypoints (ID INTEGER, Ident TEXT, Latitude REAL, Longtitude REAL);
        CREATE TABLE Terminals (ID INTEGER, AirportID INTEGER, Proc TEXT, ICAO TEXT, FullName TEXT, Name TEXT, Rwy TEXT, RwyID INTEGER, IlsID INTEGER);
        CREATE TABLE TerminalLegs (ID INTEGER, TerminalID INTEGER, Type TEXT, Transition TEXT, TrackCode TEXT, WptID INTEGER, WptLat REAL, WptLon REAL, TurnDir TEXT, NavID INTEGER, NavLat REAL, NavLon REAL, NavBear REAL, NavDist REAL, Course REAL, Distance REAL, Alt TEXT, Vnav REAL, CenterID INTEGER, CenterLat REAL, CenterLon REAL, WptDescCode TEXT);
        CREATE TABLE TerminalLegsEx (ID INTEGER, IsFlyOver INTEGER, SpeedLimit REAL, SpeedLimitDescription TEXT);
        INSERT INTO Airports VALUES (10, 'ZYYK');
        INSERT INTO Runways VALUES (20, 10, '04');
        INSERT INTO Waypoints VALUES (30, 'YK551', 40.624444, 122.418333);
    """)
    source = SourceRef("Terminal/ZYYK/ZYYK-4Z01.pdf", 1, 1, "hash")
    model = NavModel(tmp_path, terminal_waypoints=[TerminalWaypoint("first", "ZYYK", "YK551", 40.624444, 122.418333, source)], procedure_segments=[
        ProcedureSegment("ZYYK", "BM-09D", "离场", "04", "", (
            ChartTerminalLeg("BM-09D", "04", "IF", "YK551", "IF YK551", "离场"),
            ChartTerminalLeg("BM-09D", "04", "HM", "YK551", "HM YK551", "离场"),
        ), source),
    ])

    result = _insert_terminal_procedures(connection, model)

    assert result["terminal_procedures_inserted"] == 1
    assert connection.execute("SELECT TrackCode FROM TerminalLegs").fetchall() == [("IF",)]
    assert result["terminal_holding_rejections"] == [{"airport": "ZYYK", "label": "BM-09D", "runway": "04", "fix_ident": "YK551", "raw": "HM YK551", "source": source.__dict__}]


def test_resolves_terminal_fix_only_when_source_and_target_are_both_unique(tmp_path):
    connection = sqlite3.connect(tmp_path / "waypoints.db3")
    connection.execute("CREATE TABLE Waypoints (ID INTEGER, Ident TEXT, Latitude REAL, Longtitude REAL)")
    connection.execute("INSERT INTO Waypoints VALUES (327066, 'YK551', 40.624444, 122.418333)")
    source = SourceRef("Terminal/ZYYK/ZYYK-4Y01.pdf", page=1, sha256="hash")
    model = NavModel(Path("."), terminal_waypoints=[TerminalWaypoint("source", "ZYYK", "YK551", 40.624444, 122.418333, source)])

    assert resolve_terminal_waypoint(connection, model, "ZYYK", "YK551") == (327066, 40.624444, 122.418333)
    with pytest.raises(ConversionBlocked, match="ZYYK/MISSING has 0 source locations"):
        resolve_terminal_waypoint(connection, model, "ZYYK", "MISSING")


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
