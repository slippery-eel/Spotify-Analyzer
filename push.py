"""Add approved suggestions to their Spotify playlists. Add-only: nothing is removed anywhere,
and Liked Songs is never touched.

Same shape as Youtube-Explorer's migration_core (membership check -> filter -> add):
1. group approved suggestions by playlist,
2. re-sync those playlists so the membership check is current,
3. songs already there (or another version of them) are marked added without an API call,
4. the rest are added in batches of 100 and marked added as each batch succeeds.
If something fails partway, finished batches stay added and the rest stay approved, so running
it again continues where it stopped.

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


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _mark_added(conn, vibe, track_ids):
    conn.executemany("UPDATE suggestions SET status = 'added', added_at = ? "
                     "WHERE track_id = ? AND vibe_key = ? AND status = 'approved'",
                     [(_now(), t, vibe) for t in track_ids])
    conn.commit()


def run(progress=lambda *a, **k: None):
    storage.init_db()
    conn = storage.get_connection()
    try:
        groups = [g for g in review.get_push_queue(conn) if g['playlist_id']]
        total = sum(len(g['songs']) for g in groups)
        if not total:
            return 'Nothing approved to add'
        progress('Checking playlists', 0, total)
        sync.sync_playlists(conn, progress=lambda *a, **k: None, only_ids={g['playlist_id'] for g in groups})
        covered = classify.covered_vibes(conn)
        uris = dict(conn.execute('SELECT track_id, uri FROM tracks'))
        added = already = done = 0
        playlists_changed = 0
        for g in groups:
            ids = [s['track_id'] for s in g['songs']]
            present = [t for t in ids if g['key'] in covered.get(t, ())]
            to_add = [t for t in ids if t not in present]
            _mark_added(conn, g['key'], present)
            already += len(present)
            done += len(present)
            for i in range(0, len(to_add), BATCH):
                batch = to_add[i:i + BATCH]
                try:
                    sp.post(f"/playlists/{g['playlist_id']}/items", {'uris': [uris[t] for t in batch]})
                except sp.SpotifyError as e:
                    if '403' in str(e):
                        raise RuntimeError('Spotify refused the change (403). Log in again on the Account page to '
                                           f'grant write access, then retry. Added so far: {added}.') from e
                    raise RuntimeError(f'{e} (added so far: {added}; run again to continue)') from e
                _mark_added(conn, g['key'], batch)
                added += len(batch)
                done += len(batch)
                progress(f"Adding to {g['name']}", done, total)
            playlists_changed += bool(to_add)
        # Refresh local copies so Library/Playlists show the new songs
        sync.sync_playlists(conn, progress=lambda *a, **k: None, only_ids={g['playlist_id'] for g in groups})
    finally:
        conn.close()
    summary = f'Added {added} song{"" if added == 1 else "s"} to {playlists_changed} playlist{"" if playlists_changed == 1 else "s"}'
    if already:
        summary += f' ({already} were already there)'
    return summary


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print(run(lambda msg, done=None, total=None: print(f'  {msg}' + (f' ({done}/{total})' if total else ''))))


if __name__ == '__main__':
    main()
