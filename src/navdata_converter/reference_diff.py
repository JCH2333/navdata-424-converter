"""Deterministic diagnostics for a generated Fenix database and a local oracle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def _db(path: Path) -> Path:
    return path / "nd.db3" if path.is_dir() else path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_hash(connection: sqlite3.Connection, table: str) -> tuple[int, str]:
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    quoted = ", ".join(f'"{column}"' for column in columns)
    # SQLite value ordering is stable here and exposes content drift separately
    # from page layout drift, which is required for byte-level troubleshooting.
    rows = connection.execute(f'SELECT {quoted} FROM "{table}" ORDER BY {quoted}')
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        digest.update(json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def compare_databases(candidate: Path, reference: Path) -> dict[str, object]:
    """Compare every schema/table content hash before considering binary layout."""
    candidate, reference = _db(candidate), _db(reference)
    with sqlite3.connect(f"file:{candidate}?mode=ro", uri=True) as left, sqlite3.connect(f"file:{reference}?mode=ro", uri=True) as right:
        left_tables = {row[0] for row in left.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        right_tables = {row[0] for row in right.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        tables: dict[str, dict[str, object]] = {}
        for table in sorted(left_tables | right_tables):
            if table not in left_tables or table not in right_tables:
                tables[table] = {"present": [table in left_tables, table in right_tables]}
                continue
            left_sql = left.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            right_sql = right.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            left_count, left_hash = _table_hash(left, table)
            right_count, right_hash = _table_hash(right, table)
            tables[table] = {"schema_equal": left_sql == right_sql, "candidate_rows": left_count, "reference_rows": right_count,
                             "content_equal": left_hash == right_hash, "candidate_hash": left_hash, "reference_hash": right_hash}
    return {"byte_equal": _sha256(candidate) == _sha256(reference), "candidate_sha256": _sha256(candidate), "reference_sha256": _sha256(reference), "tables": tables}
