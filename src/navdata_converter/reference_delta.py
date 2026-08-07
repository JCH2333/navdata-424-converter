"""Read-only diagnostics for records added to a local Fenix reference database."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _db(path: Path) -> Path:
    return path / "nd.db3" if path.is_dir() else path


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    }


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _id_delta(base: sqlite3.Connection, reference: sqlite3.Connection, table: str) -> dict[str, object]:
    columns = _columns(reference, table)
    if "ID" not in columns or columns != _columns(base, table):
        return {"id_diagnostic": False}
    id_index = columns.index("ID")
    quoted = ", ".join(f'"{column}"' for column in columns)
    base_rows = {row[id_index]: row for row in base.execute(f'SELECT {quoted} FROM "{table}"')}
    reference_rows = {row[id_index]: row for row in reference.execute(f'SELECT {quoted} FROM "{table}"')}
    added_ids = [row[0] for row in reference.execute(f'SELECT "ID" FROM "{table}" ORDER BY rowid') if row[0] not in base_rows]
    changed_ids = sorted(identifier for identifier in base_rows.keys() & reference_rows.keys() if base_rows[identifier] != reference_rows[identifier])
    return {
        "id_diagnostic": True,
        "base_max_id": max(base_rows, default=None),
        "added_rows": len(added_ids),
        "added_ids_in_physical_order": added_ids[:20],
        "added_ids_tail": added_ids[-20:],
        "physical_id_order_ascending": added_ids == sorted(added_ids),
        "changed_existing_rows": len(changed_ids),
        "changed_id_sample": changed_ids[:20],
    }


def inspect_reference_delta(official: Path, reference: Path) -> dict[str, object]:
    """Compare an official base with a local finished database without copying data."""
    official, reference = _db(official), _db(reference)
    with sqlite3.connect(f"file:{official}?mode=ro", uri=True) as base, sqlite3.connect(f"file:{reference}?mode=ro", uri=True) as finished:
        base_tables = _tables(base)
        reference_tables = _tables(finished)
        result: dict[str, dict[str, object]] = {}
        for table in sorted(base_tables | reference_tables):
            if table not in base_tables or table not in reference_tables:
                result[table] = {"present": [table in base_tables, table in reference_tables]}
                continue
            item: dict[str, object] = {
                "base_rows": base.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                "reference_rows": finished.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
            }
            item.update(_id_delta(base, finished, table))
            result[table] = item
    return {"tables": result}
