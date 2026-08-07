from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .profile import ProfileError, validate_fenix_profile


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_candidate(candidate: Path, reference: Path | None = None) -> dict[str, object]:
    db = candidate / "nd.db3"
    profile = validate_fenix_profile(db)
    with sqlite3.connect(db) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ProfileError(f"SQLite integrity_check 失败: {integrity}")
        orphan_legs = connection.execute("SELECT COUNT(*) FROM TerminalLegs l LEFT JOIN Terminals t ON t.ID=l.TerminalID WHERE t.ID IS NULL").fetchone()[0]
        unmatched_ex = connection.execute("SELECT COUNT(*) FROM TerminalLegs l LEFT JOIN TerminalLegsEx x ON x.ID=l.ID WHERE x.ID IS NULL").fetchone()[0]
        if orphan_legs or unmatched_ex:
            raise ProfileError(f"程序引用无效: 孤立航段={orphan_legs}, 缺少扩展航段={unmatched_ex}")
    report = {"integrity": integrity, "journal_mode": profile["journal_mode"], "sha256": sha256(db), "byte_equal_reference": None}
    if reference:
        reference_db = reference / "nd.db3" if reference.is_dir() else reference
        report["byte_equal_reference"] = sha256(db) == sha256(reference_db)
    return report
