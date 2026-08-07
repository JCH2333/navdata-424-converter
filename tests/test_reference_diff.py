import sqlite3

from navdata_converter.reference_diff import compare_databases


def _make_db(path, value: str) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sample (id INTEGER, value TEXT)")
        db.execute("INSERT INTO sample VALUES (1, ?)", (value,))


def test_diff_separates_content_and_bytes(tmp_path):
    first, second = tmp_path / "first.db3", tmp_path / "second.db3"
    _make_db(first, "one")
    _make_db(second, "two")
    diff = compare_databases(first, second)
    assert diff["byte_equal"] is False
    assert diff["tables"]["sample"]["content_equal"] is False
