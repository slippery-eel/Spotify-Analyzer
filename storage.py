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
    vibe_key    TEXT UNIQUE,                 -- NULL for non-vibe playlists
    name        TEXT NOT NULL,
    owner_id    TEXT,
    is_owned    INTEGER NOT NULL DEFAULT 1,  -- owned or collaborative: tracks are readable
    track_total INTEGER,
    image_url   TEXT,
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
    profile_text TEXT NOT NULL,           -- what the classifier uses (draft, or your edit)
    draft_text   TEXT,                    -- latest auto draft, for "reset to draft"
    stats_json   TEXT,                    -- tags/eras/artists/overlaps/examples behind the draft
    is_edited    INTEGER NOT NULL DEFAULT 0,
    reviewed_at  TEXT,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS classified (
    track_id      TEXT PRIMARY KEY REFERENCES tracks(track_id),
    vibe_summary  TEXT,
    classified_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,                   -- user_id, display_name, last_sync_at, ...
    value TEXT
);
CREATE TABLE IF NOT EXISTS job_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',  -- running|success|error|interrupted
    done        INTEGER DEFAULT 0,
    total       INTEGER,
    message     TEXT,
    summary     TEXT,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS fit_checks (
    track_id    TEXT NOT NULL REFERENCES tracks(track_id),
    vibe_key    TEXT NOT NULL,
    fit         INTEGER,                  -- 0-100: how well the song fits this playlist it's in
    reason      TEXT,
    better_json TEXT NOT NULL DEFAULT '[]',  -- vibe keys it would fit better
    status      TEXT NOT NULL DEFAULT 'unreviewed',  -- unreviewed|keep|remove|removed
    move_to     TEXT,                     -- vibe key when "move" was chosen
    position    INTEGER,                  -- index in the playlist when removed, for "put back"
    checked_at  TEXT,
    decided_at  TEXT,
    removed_at  TEXT,
    PRIMARY KEY (track_id, vibe_key)
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
    _migrate_playlists(conn)
    conn.executescript(SCHEMA)
    _add_columns(conn, 'playlist_profiles', {'draft_text': 'TEXT', 'stats_json': 'TEXT',
                                             'is_edited': 'INTEGER NOT NULL DEFAULT 0', 'reviewed_at': 'TEXT'})
    conn.commit()
    conn.close()


def _add_columns(conn, table, columns):
    """Add columns that CREATE TABLE IF NOT EXISTS can't add to an existing table."""
    have = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    for name, decl in columns.items():
        if name not in have:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')


def _migrate_playlists(conn):
    """Rebuild the original vibe-only playlists table (vibe_key NOT NULL, no owner columns)."""
    cols = [r[1] for r in conn.execute('PRAGMA table_info(playlists)')]
    if not cols or 'owner_id' in cols:
        return
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.executescript("""
        BEGIN;
        CREATE TABLE playlists_new (
            playlist_id TEXT PRIMARY KEY, vibe_key TEXT UNIQUE, name TEXT NOT NULL, owner_id TEXT,
            is_owned INTEGER NOT NULL DEFAULT 1, track_total INTEGER, image_url TEXT,
            snapshot_id TEXT, synced_at TEXT);
        INSERT INTO playlists_new (playlist_id, vibe_key, name, snapshot_id, synced_at)
            SELECT playlist_id, vibe_key, name, snapshot_id, synced_at FROM playlists;
        DROP TABLE playlists;
        ALTER TABLE playlists_new RENAME TO playlists;
        COMMIT;
    """)
    conn.execute('PRAGMA foreign_keys = ON')


def get_meta(conn, key, default=None):
    row = conn.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value):
    conn.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (key, value))


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
