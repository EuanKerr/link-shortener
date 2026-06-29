import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.shortcode import generate

_MAX_CODE_ATTEMPTS = 10

# Short codes claimed by web-layer routes; get_or_create() never hands these
# out. Set by init_db() rather than hardcoded, so a newly added route can't
# leave a code collidable.
_reserved_codes: frozenset[str] = frozenset()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    code       TEXT PRIMARY KEY,
    url        TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(get_settings().db_path)
    con.row_factory = sqlite3.Row
    # Wait, rather than fail immediately, when another writer holds the lock.
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def init_db(reserved_codes: frozenset[str] = frozenset()) -> None:
    """Create the schema (idempotent) and record the route-reserved codes.

    `reserved_codes` is passed in by the web layer (which owns the route table)
    rather than hardcoded here. See `_reserved_codes`.
    """
    global _reserved_codes
    _reserved_codes = reserved_codes
    # Create the DB's parent directory once at startup, not per _connect().
    Path(get_settings().db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as con:
        # WAL lets readers and a writer proceed concurrently. Persisted in the
        # DB file header, so it applies to every later connection.
        con.execute("PRAGMA journal_mode = WAL")
        con.execute(_SCHEMA)
        con.commit()


def lookup(code: str) -> str | None:
    with closing(_connect()) as con:
        row = con.execute("SELECT url FROM links WHERE code = ?", (code,)).fetchone()
        return row["url"] if row else None


def list_all() -> list[sqlite3.Row]:
    """Return every link as (code, url, created_at) rows, newest first."""
    with closing(_connect()) as con:
        return con.execute(
            "SELECT code, url, created_at FROM links ORDER BY created_at DESC"
        ).fetchall()


def delete(code: str) -> bool:
    """Remove the link with this code. Return True if a row was deleted."""
    with closing(_connect()) as con:
        cur = con.execute("DELETE FROM links WHERE code = ?", (code,))
        con.commit()
        return cur.rowcount > 0


def get_or_create(url: str) -> str:
    with closing(_connect()) as con:
        row = con.execute("SELECT code FROM links WHERE url = ?", (url,)).fetchone()
        if row:
            return row["code"]

        created_at = datetime.now(timezone.utc).isoformat()
        for _ in range(_MAX_CODE_ATTEMPTS):
            code = generate()
            if code in _reserved_codes:
                continue
            try:
                con.execute(
                    "INSERT INTO links (code, url, created_at) VALUES (?, ?, ?)",
                    (code, url, created_at),
                )
                con.commit()
                return code
            except sqlite3.IntegrityError:
                # Either the code collided (PK) or the url was inserted
                # concurrently (UNIQUE). Roll back, then return the url's code
                # if it now exists.
                con.rollback()
                existing = con.execute(
                    "SELECT code FROM links WHERE url = ?", (url,)
                ).fetchone()
                if existing:
                    return existing["code"]
                # Otherwise it was a code collision; try a new code.
        raise RuntimeError("could not generate a unique short code")
