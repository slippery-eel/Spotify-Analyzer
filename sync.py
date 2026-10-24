"""Read-only pull from Spotify into SQLite: liked songs, the vibe playlists and their songs,
and artist genres. Safe to re-run: playlists whose snapshot_id hasn't changed are skipped,
and artists already fetched are not fetched again.

Usage: python sync.py
"""
import difflib
import json
import re
import sys
from datetime import datetime, timezone

import config
import spotify_client as sp
import storage


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def normalize_name(name):
    name = name.replace('’', "'").replace('‘', "'").lower()
    return re.sub(r'\s+', ' ', name).strip()


def normalize_for_dedup(title, first_artist):
    """Same key as deduplicateTracks() in script.js: title without (...)/[...] + first artist."""
    t = re.sub(r'\s*[\(\[].*?[\)\]]', '', title.lower()).strip()
    return f'{t}|{first_artist.strip().lower()}'


def match_playlists(user_playlists, vibes=None):
    """Match config vibes to the user's playlists by normalized name.

    user_playlists: [{'id', 'name', ...}]. Returns (matched {vibe_key: playlist}, unmatched [vibe]).
    """
    vibes = vibes or config.VIBE_PLAYLISTS
    by_name = {}
    for p in user_playlists:
        by_name.setdefault(normalize_name(p['name']), p)
    matched, unmatched = {}, []
    for v in vibes:
        p = by_name.get(normalize_name(v['name']))
        if p:
            matched[v['key']] = p
        else:
            unmatched.append(v)
    return matched, unmatched


def _track_from_item(it):
    """Playlist/library items carry the track under 'item' (post-Feb-2026) or 'track'."""
    t = it.get('item') or it.get('track')
    if not t or t.get('type', 'track') != 'track' or not t.get('id'):
        return None  # local files, episodes, unavailable tracks
    return t


def sync_liked(conn):
    rows = []
    for it in sp.paginate('/me/tracks', {'limit': 50}):
        t = _track_from_item(it)
        if t:
            storage.upsert_track(conn, t)
            rows.append((t['id'], it.get('added_at')))
    conn.execute('DELETE FROM liked')  # full refresh so un-liked songs drop out
    conn.executemany('INSERT OR REPLACE INTO liked (track_id, added_at) VALUES (?, ?)', rows)
    conn.commit()
    return len(rows)


def sync_playlists(conn):
    user_playlists = list(sp.paginate('/me/playlists', {'limit': 50}))
    matched, unmatched = match_playlists(user_playlists)
    changed = 0
    for vibe_key, p in matched.items():
        row = conn.execute('SELECT snapshot_id FROM playlists WHERE playlist_id = ?', (p['id'],)).fetchone()
        old_snapshot = row[0] if row else None
        # A vibe re-pointed at a different playlist: drop the old one
        for (old_id,) in conn.execute('SELECT playlist_id FROM playlists WHERE vibe_key = ? AND playlist_id != ?',
                                      (vibe_key, p['id'])).fetchall():
            conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (old_id,))
            conn.execute('DELETE FROM playlists WHERE playlist_id = ?', (old_id,))
        # snapshot_id is only updated after the items are saved, so a crash mid-fetch re-fetches next run
        conn.execute('INSERT OR REPLACE INTO playlists (playlist_id, vibe_key, name, snapshot_id, synced_at) '
                     'VALUES (?, ?, ?, ?, ?)', (p['id'], vibe_key, p['name'], old_snapshot, _now()))
        if old_snapshot and old_snapshot == p.get('snapshot_id'):
            continue
        changed += 1
        rows = []
        for it in sp.paginate(f"/playlists/{p['id']}/items", {'limit': 50}):
            t = _track_from_item(it)
            if t:
                storage.upsert_track(conn, t)
                rows.append((p['id'], t['id'], it.get('added_at')))
        conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (p['id'],))
        conn.executemany('INSERT OR IGNORE INTO playlist_items (playlist_id, track_id, added_at) '
                         'VALUES (?, ?, ?)', rows)
        conn.execute('UPDATE playlists SET snapshot_id = ? WHERE playlist_id = ?', (p.get('snapshot_id'), p['id']))
        conn.commit()
        print(f"  {p['name']}: {len(rows)} songs")
    conn.commit()
    return matched, unmatched, user_playlists, changed


def sync_artists(conn):
    known = {r[0] for r in conn.execute('SELECT artist_id FROM artists')}
    needed = set()
    for (aj,) in conn.execute('SELECT artists_json FROM tracks'):
        needed.update(a['id'] for a in json.loads(aj) if a.get('id'))
    todo = sorted(needed - known)
    for i, artist_id in enumerate(todo, 1):
        a = sp.get(f'/artists/{artist_id}')
        conn.execute('INSERT OR REPLACE INTO artists (artist_id, name, genres_json, fetched_at) VALUES (?, ?, ?, ?)',
                     (artist_id, a.get('name'), json.dumps(a.get('genres') or []), _now()))
        if i % 50 == 0:
            conn.commit()
            print(f'  artists {i}/{len(todo)}')
    conn.commit()
    return len(todo)


def report(conn, matched, unmatched, user_playlists):
    print('\n=== Sync report ===')
    print(f"Liked songs: {conn.execute('SELECT COUNT(*) FROM liked').fetchone()[0]}")
    print(f'Vibe playlists matched: {len(matched)}/{len(config.VIBE_PLAYLISTS)}')
    names = [p['name'] for p in user_playlists]
    for v in unmatched:
        close = difflib.get_close_matches(v['name'], names, n=3, cutoff=0.4)
        print(f"  NOT FOUND: {v['name']!r}  (closest: {close})")
    with_genres = conn.execute("SELECT COUNT(*) FROM artists WHERE genres_json != '[]'").fetchone()[0]
    total_artists = conn.execute('SELECT COUNT(*) FROM artists').fetchone()[0]
    print(f'Artists with Spotify genres: {with_genres}/{total_artists}')
    for v in config.VIBE_PLAYLISTS:
        if v['key'] not in matched:
            continue
        pid = matched[v['key']]['id']
        n = conn.execute('SELECT COUNT(*) FROM playlist_items WHERE playlist_id = ?', (pid,)).fetchone()[0]
        samples = conn.execute(
            'SELECT t.name, t.artists_json FROM playlist_items pi JOIN tracks t USING(track_id) '
            'WHERE pi.playlist_id = ? ORDER BY RANDOM() LIMIT 5', (pid,)).fetchall()
        sample_str = '; '.join(f"{name} - {json.loads(aj)[0]['name']}" for name, aj in samples)
        print(f"\n[{v['name']}] {n} songs\n  e.g. {sample_str}")


def main():
    sys.stdout.reconfigure(encoding='utf-8')  # Windows console defaults to cp1252; playlist names have emoji
    storage.init_db()
    conn = storage.get_connection()
    try:
        print('Syncing liked songs...')
        n = sync_liked(conn)
        print(f'  {n} liked songs')
        print('Syncing vibe playlists...')
        matched, unmatched, user_playlists, changed = sync_playlists(conn)
        print(f'  {changed} playlists re-fetched')
        print('Fetching artist genres...')
        print(f'  {sync_artists(conn)} new artists')
        report(conn, matched, unmatched, user_playlists)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
