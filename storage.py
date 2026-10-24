"""SQLite storage. Plain sqlite3, one connection per call site (same idiom as Youtube-Explorer)."""
import json
import sqlite3

import config


def get_connection():
    # No WAL: the DB lives in a OneDrive folder and -wal/-shm files don't sync safely.
    conn = sqlite3.connect(config.DB_FILE, timeout=30)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    track_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    artists_json  TEXT NOT NULL,          -- [{"id", "name"}, ...]
    album         TEXT,
    release_date  TEXT,
    duration_ms   INTEGER,
    uri           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artists (
    artist_id   TEXT PRIMARY KEY,
    name        TEXT,
    genres_json TEXT NOT NULL DEFAULT '[]',
    fetched_at  TEXT
);
CREATE TABLE IF NOT EXISTS liked (
    track_id TEXT PRIMARY KEY REFERENCES tracks(track_id),
    added_at TEXT
);
CREATE TABLE IF NOT EXISTS playlists (
    playlist_id TEXT PRIMARY KEY,
    vibe_key    TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    snapshot_id TEXT,
    synced_at   TEXT
);
CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id TEXT NOT NULL REFERENCES playlists(playlist_id),
    track_id    TEXT NOT NULL REFERENCES tracks(track_id),
    added_at    TEXT,
    PRIMARY KEY (playlist_id, track_id)
);
CREATE TABLE IF NOT EXISTS track_tags (
    track_id   TEXT PRIMARY KEY REFERENCES tracks(track_id),
    tags_json  TEXT NOT NULL DEFAULT '[]',
    source     TEXT,                      -- 'track' | 'artist' | 'none'
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS lyrics (
    track_id     TEXT PRIMARY KEY REFERENCES tracks(track_id),
    plain_lyrics TEXT,
    instrumental INTEGER DEFAULT 0,
    found        INTEGER DEFAULT 0,
    fetched_at   TEXT
);
CREATE TABLE IF NOT EXISTS playlist_profiles (
    vibe_key     TEXT PRIMARY KEY,
    profile_text TEXT NOT NULL,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS classified (
    track_id      TEXT PRIMARY KEY REFERENCES tracks(track_id),
    vibe_summary  TEXT,
    classified_at TEXT
);
CREATE TABLE IF NOT EXISTS suggestions (
    track_id      TEXT NOT NULL REFERENCES tracks(track_id),
    vibe_key      TEXT NOT NULL,
    score         INTEGER,
    reason        TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',   -- pending|approved|declined|added
    classified_at TEXT,
    decided_at    TEXT,
    added_at      TEXT,
    PRIMARY KEY (track_id, vibe_key)
);
"""


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def upsert_track(conn, t):
    """t is a Spotify track object."""
    conn.execute(
        'INSERT OR REPLACE INTO tracks (track_id, name, artists_json, album, release_date, duration_ms, uri) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (t['id'], t['name'],
         json.dumps([{'id': a.get('id'), 'name': a.get('name')} for a in t.get('artists', [])]),
         (t.get('album') or {}).get('name'),
         (t.get('album') or {}).get('release_date'),
         t.get('duration_ms'), t['uri']))
