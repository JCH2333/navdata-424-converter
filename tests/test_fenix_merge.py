import json
import sqlite3
from pathlib import Path

from navdata_converter.fenix import _insert_model, build_rejection_report, encode_frequency
from navdata_converter.model import Airport, NavModel, RejectedRecord, Runway, SourceRef


def test_merge_preserves_existing_airport_and_appends_only_missing_rows(tmp_path):
    db = sqlite3.connect(tmp_path / "test.db3")
    db.executescript("""
        CREATE TABLE Airports (ID INTEGER, Name TEXT, ICAO TEXT, PrimaryID INTEGER, Latitude REAL, Longtitude REAL, Elevation INTEGER, TransitionAltitude INTEGER, TransitionLevel INTEGER, SpeedLimit INTEGER, SpeedLimitAltitude INTEGER);
        CREATE TABLE AirportLookup (extID TEXT, ID INTEGER);
        CREATE TABLE Runways (ID INTEGER, AirportID INTEGER, Ident TEXT, TrueHeading REAL, Length INTEGER, Width INTEGER, Surface TEXT, Latitude REAL, Longtitude REAL, Elevation INTEGER);
        INSERT INTO Airports VALUES (10, 'BASE', 'ZBAA', NULL, 0, 0, 0, 0, 0, 250, 10000);
    """)
    source = SourceRef("fixture.csv", 1)
    model = NavModel(Path("."), airports={
        "old": Airport("old", "ZBAA", "changed", 1, 2, 3, 4, 5, source),
        "new": Airport("new", "ZBCF", "new", 1, 2, 3, 4, 5, source),
    }, runways=[Runway("new-rwy", "new", "03", 30, 1000, 30, "ASP", 3, source)])
    counts = _insert_model(db, model)
    assert counts == {"airports_inserted": 1, "airports_preserved": 1, "runways_inserted": 1}
    assert db.execute("SELECT ID, Name FROM Airports WHERE ICAO='ZBAA'").fetchone() == (10, "BASE")
    assert db.execute("SELECT ID FROM Airports WHERE ICAO='ZBCF'").fetchone() == (11,)
    assert db.execute("SELECT AirportID FROM Runways").fetchone() == (11,)
    db.commit()


def test_fenix_navaid_frequency_uses_observed_bcd_contract():
    assert encode_frequency(112.4, "VOR") == 0x01124000
    assert encode_frequency(495, "NDB") == 0x04950000


def test_rejection_report_preserves_unmapped_source_record(tmp_path):
    model = NavModel(tmp_path, rejected_records=[RejectedRecord("VOR", "TD", "unmapped country", SourceRef("VOR.csv", 13))])

    report = json.loads(build_rejection_report(model, tmp_path / "report").read_text(encoding="utf-8"))

    assert report["rejected_records"] == [{"kind": "VOR", "key": "TD", "reason": "unmapped country", "source": {"file": "VOR.csv", "row": 13, "page": None, "sha256": None}}]
