"""Detect a SQLite database created before Alembic was introduced.

Prints ``stamp`` when the schema exists but no revision has been recorded, so
the setup script can mark it as the current head instead of re-creating tables.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main(path: str) -> int:
    database = Path(path)
    if not database.exists():
        print("ready")
        return 0
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type='table'"
            )
        }
        revisions = 0
        if "alembic_version" in tables:
            revisions = connection.execute(
                "select count(*) from alembic_version"
            ).fetchone()[0]
    print("stamp" if "articles" in tables and revisions == 0 else "ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
