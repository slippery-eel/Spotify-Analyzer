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


def _print_progress(msg, done=None, total=None):
    print(f'  {msg}' + (f' ({done}/{total})' if total else ''))


def sync_liked(conn, progress=_print_progress):
    rows = []
    for it in sp.paginate('/me/tracks', {'limit': 50}):
        t = _track_from_item(it)
        if t:
            storage.upsert_track(conn, t)
            rows.append((t['id'], it.get('added_at')))
        if len(rows) % 500 == 0 and rows:
            progress(f'Liked songs: {len(rows)} so far')
    conn.execute('DELETE FROM liked')  # full refresh so un-liked songs drop out
    conn.executemany('INSERT OR REPLACE INTO liked (track_id, added_at) VALUES (?, ?)', rows)
    conn.commit()
    progress(f'{len(rows)} liked songs')
    return len(rows)


def _store_items(conn, playlist_id):
    rows = []
    for it in sp.paginate(f'/playlists/{playlist_id}/items', {'limit': 50}):
        t = _track_from_item(it)
        if t:
            storage.upsert_track(conn, t)
            rows.append((playlist_id, t['id'], it.get('added_at')))
    conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
    conn.executemany('INSERT OR IGNORE INTO playlist_items (playlist_id, track_id, added_at) '
                     'VALUES (?, ?, ?)', rows)
    return len(rows)


def sync_playlists(conn, progress=_print_progress, only_ids=None):
    """Store every playlist you have; fetch songs for the ones you own or collaborate on.

    Spotify only lets apps read the songs of playlists you own or collaborate on, so followed
    playlists are listed without songs. only_ids limits the song re-fetch to those playlists.
    """
    me = sp.get('/me')
    storage.set_meta(conn, 'user_id', me['id'])
    storage.set_meta(conn, 'display_name', me.get('display_name') or me['id'])
    user_playlists = [p for p in sp.paginate('/me/playlists', {'limit': 50}) if p]
    matched, unmatched = match_playlists(user_playlists)
    vibe_by_id = {p['id']: k for k, p in matched.items()}
    seen = set()
    changed = 0
    for i, p in enumerate(user_playlists, 1):
        if p['id'] in seen:
            continue
        seen.add(p['id'])
        owned = (p.get('owner') or {}).get('id') == me['id'] or bool(p.get('collaborative'))
        paging = p.get('items') or p.get('tracks') or {}
        row = conn.execute('SELECT snapshot_id FROM playlists WHERE playlist_id = ?', (p['id'],)).fetchone()
        old_snapshot = row[0] if row else None
        vibe_key = vibe_by_id.get(p['id'])
        if vibe_key:  # a vibe re-pointed at a different playlist: release the old row's key
            conn.execute('UPDATE playlists SET vibe_key = NULL WHERE vibe_key = ? AND playlist_id != ?',
                         (vibe_key, p['id']))
        # snapshot_id is only updated after the items are saved, so a crash mid-fetch re-fetches next run
        conn.execute('INSERT OR REPLACE INTO playlists (playlist_id, vibe_key, name, owner_id, is_owned, track_total, '
                     'image_url, snapshot_id, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (p['id'], vibe_key, p['name'], (p.get('owner') or {}).get('id'), int(owned),
                      paging.get('total'), ((p.get('images') or [{}])[0] or {}).get('url'), old_snapshot, _now()))
        conn.commit()
        if not owned or (only_ids is not None and p['id'] not in only_ids):
            continue
        if old_snapshot and old_snapshot == p.get('snapshot_id'):
            continue
        n = _store_items(conn, p['id'])
        conn.execute('UPDATE playlists SET snapshot_id = ? WHERE playlist_id = ?', (p.get('snapshot_id'), p['id']))
        conn.commit()
        changed += 1
        progress(f"Playlist {p['name']}: {n} songs", i, len(user_playlists))
    # Playlists you deleted or unfollowed
    gone = [r[0] for r in conn.execute('SELECT playlist_id FROM playlists') if r[0] not in seen]
    for pid in gone:
        conn.execute('DELETE FROM playlist_items WHERE playlist_id = ?', (pid,))
        conn.execute('DELETE FROM playlists WHERE playlist_id = ?', (pid,))
    conn.commit()
    return matched, unmatched, user_playlists, changed


def sync_artists(conn, progress=_print_progress):
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
            progress('Artist genres', i, len(todo))
    conn.commit()
    return len(todo)


def run(progress=_print_progress):
    """Full sync. Returns (summary string, report args)."""
    storage.init_db()
    conn = storage.get_connection()
    try:
        progress('Syncing liked songs')
        n = sync_liked(conn, progress)
        progress('Syncing playlists')
        matched, unmatched, user_playlists, changed = sync_playlists(conn, progress)
        progress('Fetching artist genres')
        new_artists = sync_artists(conn, progress)
        storage.set_meta(conn, 'last_sync_at', _now())
        conn.commit()
        summary = (f'{n} liked songs, {len(user_playlists)} playlists ({changed} re-fetched), '
                   f'{len(matched)}/{len(config.VIBE_PLAYLISTS)} vibe playlists matched, {new_artists} new artists')
        if unmatched:
            summary += f"; not found: {', '.join(v['name'] for v in unmatched)}"
        return summary, (matched, unmatched, user_playlists)
    finally:
        conn.close()


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
    summary, (matched, unmatched, user_playlists) = run()
    print(summary)
    conn = storage.get_connection()
    try:
        report(conn, matched, unmatched, user_playlists)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
