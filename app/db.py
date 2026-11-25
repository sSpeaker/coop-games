import os
import sqlite3
import threading

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (
    oc_id        INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL,
    name         TEXT NOT NULL,
    norm         TEXT NOT NULL,
    score        INTEGER,
    release_date TEXT,
    genres       TEXT,
    image        TEXT,
    seen_at      TEXT
);
CREATE INDEX IF NOT EXISTS catalog_norm ON catalog(norm);

CREATE TABLE IF NOT EXISTS catalog_platform (
    oc_id    INTEGER NOT NULL,
    platform TEXT NOT NULL,
    oc_coop  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (oc_id, platform)
);

CREATE TABLE IF NOT EXISTS coopt (
    coopt_id    INTEGER NOT NULL,
    platform    TEXT NOT NULL,
    title       TEXT NOT NULL,
    norm        TEXT NOT NULL,
    genre       TEXT,
    online      INTEGER,
    couch       INTEGER,
    lan         INTEGER,
    features    TEXT,
    release     TEXT,
    oc_id       INTEGER,
    PRIMARY KEY (coopt_id, platform)
);
CREATE INDEX IF NOT EXISTS coopt_norm ON coopt(norm);
CREATE INDEX IF NOT EXISTS coopt_oc ON coopt(oc_id);

CREATE TABLE IF NOT EXISTS games (
    id               INTEGER PRIMARY KEY,
    slug             TEXT NOT NULL,
    name             TEXT NOT NULL,
    norm             TEXT NOT NULL,
    score            INTEGER,
    release_date     TEXT,
    genres           TEXT,
    pegi             INTEGER,
    pegi_title       TEXT,
    pegi_checked_at  TEXT,
    image            TEXT,
    banner           TEXT,
    description      TEXT,
    trailers         TEXT,
    online           INTEGER,
    couch            INTEGER,
    lan              INTEGER,
    features         TEXT,
    source           TEXT,
    page_fetched_at  TEXT,
    genre_checked_at TEXT,
    updated_at       TEXT
);

CREATE TABLE IF NOT EXISTS game_platform (
    game_id  INTEGER NOT NULL,
    platform TEXT NOT NULL,
    PRIMARY KEY (game_id, platform)
);

CREATE TABLE IF NOT EXISTS game_genre (
    game_id INTEGER NOT NULL,
    genre   TEXT NOT NULL,
    PRIMARY KEY (game_id, genre)
);
CREATE INDEX IF NOT EXISTS game_genre_genre ON game_genre(genre);

CREATE TABLE IF NOT EXISTS played (
    game_id   INTEGER PRIMARY KEY,
    played_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS want (
    game_id  INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL
);

-- "Not interested": hidden from every list unless asked for
CREATE TABLE IF NOT EXISTS skip (
    game_id  INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS overrides (
    game_id INTEGER NOT NULL,
    field   TEXT NOT NULL,
    value   TEXT,
    PRIMARY KEY (game_id, field)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_write_lock = threading.Lock()


def connect():
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Columns added after the first release: (table, column, type)
MIGRATIONS = [
    ("games", "metascore", "INTEGER"),
    ("games", "mc_url", "TEXT"),
    ("games", "mc_checked_at", "TEXT"),
    ("games", "steam_appid", "INTEGER"),
    ("games", "eshop_url", "TEXT"),
    ("games", "stores_checked_at", "TEXT"),
]


def init():
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    conn.close()


def write_lock():
    return _write_lock


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, None if value is None else str(value)),
    )
