"""Apply review decisions to Spotify: remove songs you chose to take out of a vibe playlist
(Playlist check), then add approved suggestions. Liked Songs is never touched, and a removal only
affects that one playlist.

Same shape as Youtube-Explorer's migration_core (membership check -> filter -> change):
1. re-sync the affected playlists so the membership check is current,
2. removals: remember each song's position (for "put back"), delete in batches of 100,
3. additions: songs already there (or another version of them) are marked added without a call,
   the rest are added in batches of 100,
each batch is marked as it succeeds. If something fails partway, finished batches stay done and the
rest stay queued, so running it again continues where it stopped.

Usage: python push.py
"""
import sys
from datetime import datetime, timezone

import classify
import review
import spotify_client as sp
import storage
import sync

BATCH = 100
REMOVED_REASON = 'Removed by you'


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _s(n):
    return '' if n == 1 else 's'


def _spotify(call, what, so_far):
    try:
        return call()
    except sp.SpotifyError as e:
        if '403' in str(e):
            raise RuntimeError('Spotify refused the change (403). Log in again on the Account page to grant '
                               f'write access, then retry. Done so far: {so_far}.') from e
        raise RuntimeError(f'{e} while {what} ({so_far} so far; run again to continue)') from e


def _mark_added(conn, vibe, track_ids):
    conn.executemany("UPDATE suggestions SET status = 'added', added_at = ? "
                     "WHERE track_id = ? AND vibe_key = ? AND status = 'approved'",
                     [(_now(), t, vibe) for t in track_ids])
    conn.commit()


def _mark_removed(conn, vibe, playlist_id, positions):
    """positions: {track_id: index in the playlist before removal (None if it was already gone)}."""
    now = _now()
    for tid, pos in positions.items():
        conn.execute("UPDATE fit_checks SET status = 'removed', removed_at = ?, position = ? "
                     "WHERE track_id = ? AND vibe_key = ? AND status = 'remove'", (now, pos, tid, vibe))
        conn.execute('DELETE FROM playlist_items WHERE playlist_id = ? AND track_id = ?', (playlist_id, tid))
        # So the classifier never suggests it back for this playlist
        conn.execute("INSERT INTO suggestions (track_id, vibe_key, score, reason, status, decided_at) "
                     "VALUES (?, ?, NULL, ?, 'declined', ?) ON CONFLICT(track_id, vibe_key) DO UPDATE SET "
                     "status = 'declined', reason = excluded.reason, decided_at = excluded.decided_at",
                     (tid, vibe, REMOVED_REASON, now))
    conn.commit()


def run(progress=lambda *a, **k: None):
    """Apply queued removals, then approved additions."""
    storage.init_db()
    conn = storage.get_connection()
    try:
        removes = [g for g in review.get_remove_queue(conn) if g['playlist_id']]
        adds = [g for g in review.get_push_queue(conn) if g['playlist_id']]
        total = sum(len(g['songs']) for g in removes + adds)
        if not total:
            return 'Nothing to apply'
        touched = {g['playlist_id'] for g in removes + adds}
        progress('Checking playlists', 0, total)
        sync.sync_playlists(conn, progress=lambda *a, **k: None, only_ids=touched)
        uris = dict(conn.execute('SELECT track_id, uri FROM tracks'))
        done = removed = added = already = removed_from = added_to = 0

        for g in removes:
            order = [r[0] for r in conn.execute('SELECT track_id FROM playlist_items WHERE playlist_id = ? '
                                                'ORDER BY rowid', (g['playlist_id'],))]
            ids = [s['track_id'] for s in g['songs']]
            positions = {t: (order.index(t) if t in order else None) for t in ids}
            gone = [t for t in ids if positions[t] is None]   # you already removed it in Spotify
            _mark_removed(conn, g['key'], g['playlist_id'], {t: None for t in gone})
            done += len(gone)
            to_remove = [t for t in ids if t not in gone]
            for i in range(0, len(to_remove), BATCH):
                batch = to_remove[i:i + BATCH]
                _spotify(lambda: sp.delete(f"/playlists/{g['playlist_id']}/items",
                                           {'items': [{'uri': uris[t]} for t in batch]}),
                         f"removing from {g['name']}", f'{removed} removed, {added} added')
                _mark_removed(conn, g['key'], g['playlist_id'], {t: positions[t] for t in batch})
                removed += len(batch)
                done += len(batch)
                progress(f"Removing from {g['name']}", done, total)
            removed_from += bool(to_remove)

        covered = classify.covered_vibes(conn)
        for g in adds:
            ids = [s['track_id'] for s in g['songs']]
            present = [t for t in ids if g['key'] in covered.get(t, ())]
            to_add = [t for t in ids if t not in present]
            _mark_added(conn, g['key'], present)
            already += len(present)
            done += len(present)
            for i in range(0, len(to_add), BATCH):
                batch = to_add[i:i + BATCH]
                _spotify(lambda: sp.post(f"/playlists/{g['playlist_id']}/items", {'uris': [uris[t] for t in batch]}),
                         f"adding to {g['name']}", f'{removed} removed, {added} added')
                _mark_added(conn, g['key'], batch)
                added += len(batch)
                done += len(batch)
                progress(f"Adding to {g['name']}", done, total)
            added_to += bool(to_add)
        # Refresh local copies so Library/Playlists show the changes
        sync.sync_playlists(conn, progress=lambda *a, **k: None, only_ids=touched)
    finally:
        conn.close()
    parts = []
    if removes:
        parts.append(f'removed {removed} song{_s(removed)} from {removed_from} playlist{_s(removed_from)}')
    if adds:
        parts.append(f'added {added} song{_s(added)} to {added_to} playlist{_s(added_to)}'
                     + (f' ({already} were already there)' if already else ''))
    summary = ', '.join(parts)
    return summary[0].upper() + summary[1:]


def restore(track_id, vibe):
    """Put a removed song back into its playlist at the position it had."""
    conn = storage.get_connection()
    try:
        row = conn.execute("SELECT f.position, p.playlist_id, t.uri FROM fit_checks f "
                           "JOIN playlists p ON p.vibe_key = f.vibe_key JOIN tracks t ON t.track_id = f.track_id "
                           "WHERE f.track_id = ? AND f.vibe_key = ? AND f.status = 'removed'", (track_id, vibe)).fetchone()
        if not row:
            raise ValueError('Not a removed song')
        pos, playlist_id, uri = row
        size = conn.execute('SELECT COUNT(*) FROM playlist_items WHERE playlist_id = ?', (playlist_id,)).fetchone()[0]
        body = {'uris': [uri]}
        if pos is not None:
            body['position'] = min(pos, size)
        _spotify(lambda: sp.post(f'/playlists/{playlist_id}/items', body), 'putting it back', 'nothing')
        conn.execute("UPDATE fit_checks SET status = 'keep', removed_at = NULL, position = NULL, decided_at = ? "
                     'WHERE track_id = ? AND vibe_key = ?', (_now(), track_id, vibe))
        conn.execute('DELETE FROM suggestions WHERE track_id = ? AND vibe_key = ? AND reason = ?',
                     (track_id, vibe, REMOVED_REASON))
        conn.commit()
        sync.sync_playlists(conn, progress=lambda *a, **k: None, only_ids={playlist_id})
    finally:
        conn.close()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print(run(lambda msg, done=None, total=None: print(f'  {msg}' + (f' ({done}/{total})' if total else ''))))


if __name__ == '__main__':
    main()
