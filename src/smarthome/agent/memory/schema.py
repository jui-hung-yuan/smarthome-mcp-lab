"""SQLite schema creation and migrations for the agent memory system."""

import sqlite3
from pathlib import Path


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and virtual tables if they don't exist."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        -- Track indexed Markdown files for incremental sync
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            hash TEXT,
            mtime REAL,
            size INTEGER
        );

        -- Text chunks parsed from Markdown
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,        -- "{path}:L{start}-{end}"
            path TEXT,
            start_line INTEGER,
            end_line INTEGER,
            text TEXT,
            hash TEXT,
            updated_at REAL
        );

        -- BM25 full-text search (SQLite FTS5 uses BM25 as its ranking algorithm)
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text,
            id UNINDEXED,
            path UNINDEXED
        );

        -- Timestamped device event log (too verbose for Markdown)
        CREATE TABLE IF NOT EXISTS device_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            action TEXT,
            params TEXT,    -- JSON
            result TEXT,    -- JSON
            timestamp REAL
        );
    """)
    conn.commit()


def load_vec_extension(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec extension. Returns True if successful."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def create_vec_table(conn: sqlite3.Connection) -> bool:
    """Create the vector table if sqlite-vec is available. Returns True if created."""
    if not load_vec_extension(conn):
        return False
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec
            USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[384])
        """)
        conn.commit()
        return True
    except Exception:
        return False


def open_db(db_path: Path) -> tuple[sqlite3.Connection, bool]:
    """Open (or create) the SQLite database, apply schema, return (conn, vec_available)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    vec_available = create_vec_table(conn)
    return conn, vec_available
