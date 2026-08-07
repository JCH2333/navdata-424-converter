import sqlite3

from navdata_converter.reference_delta import inspect_reference_delta


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
