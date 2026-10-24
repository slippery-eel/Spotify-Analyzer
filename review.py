"""Review-queue reads and decision writes used by server.py.

Decisions follow Youtube-Explorer's services/decisions.py rules: only pending/approved/declined
rows are editable ('added' rows are owned by the push step), approving a playlist the classifier
never suggested creates a manual row, and status 'removed' deletes that manual row again (undo).
"""
import json
from datetime import datetime, timezone

import config

EDITABLE = ('pending', 'approved', 'declined')
VIEWS = ('pending', 'approved', 'declined', 'added')
MANUAL = 'Added manually'
VIBES = {v['key']: v for v in config.VIBE_PLAYLISTS}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def get_stats(conn):
    counts = {v: 0 for v in VIEWS}
    for status, n in conn.execute('SELECT status, COUNT(DISTINCT track_id) FROM suggestions GROUP BY status'):
        counts[status] = n
    per_vibe = {k: {v: 0 for v in VIEWS} for k in VIBES}
    for vibe, status, n in conn.execute('SELECT vibe_key, status, COUNT(*) FROM suggestions GROUP BY vibe_key, status'):
        if vibe in per_vibe:
            per_vibe[vibe][status] = n
    sizes = dict(conn.execute('SELECT p.vibe_key, COUNT(pi.track_id) FROM playlists p '
                              'LEFT JOIN playlist_items pi USING(playlist_id) GROUP BY p.vibe_key'))
    playlists = [{'key': k, 'name': v['name'], 'description': v['description'],
                  'size': sizes.get(k, 0), 'counts': per_vibe[k]} for k, v in VIBES.items()]
    liked = conn.execute('SELECT COUNT(*) FROM liked').fetchone()[0]
    classified = conn.execute('SELECT COUNT(*) FROM classified').fetchone()[0]
    return {'counts': counts, 'playlists': playlists, 'liked': liked, 'classified': classified}


def get_queue(conn, view='pending', vibe=None, q=None, sort='score', offset=0, limit=20):
    """Tracks with at least one suggestion in `view` status (for `vibe`, if given)."""
    where = ['s.status = ?']
    params = [view]
    if vibe:
        where.append('s.vibe_key = ?')
        params.append(vibe)
    if q:
        where.append('(t.name LIKE ? OR t.artists_json LIKE ? OR t.album LIKE ?)')
        params += [f'%{q}%'] * 3
    order = 'max_score DESC, t.name' if sort == 'score' else 'l.added_at DESC, t.name'
    base = (f'FROM suggestions s JOIN tracks t USING(track_id) LEFT JOIN liked l USING(track_id) '
            f'WHERE {" AND ".join(where)}')
    total = conn.execute(f'SELECT COUNT(DISTINCT s.track_id) {base}', params).fetchone()[0]
    ids = [r[0] for r in conn.execute(
        f'SELECT s.track_id, MAX(s.score) AS max_score {base} GROUP BY s.track_id ORDER BY {order} '
        f'LIMIT ? OFFSET ?', params + [limit, offset])]
    return {'total': total, 'offset': offset, 'tracks': [get_track(conn, tid) for tid in ids]}


def get_track(conn, track_id):
    name, aj, album, release, uri = conn.execute(
        'SELECT name, artists_json, album, release_date, uri FROM tracks WHERE track_id = ?', (track_id,)).fetchone()
    artists = json.loads(aj)
    genres = []
    for a in artists:
        row = conn.execute('SELECT genres_json FROM artists WHERE artist_id = ?', (a.get('id'),)).fetchone()
        for g in json.loads(row[0]) if row else []:
            if g not in genres:
                genres.append(g)
    tag_row = conn.execute('SELECT tags_json FROM track_tags WHERE track_id = ?', (track_id,)).fetchone()
    tags = [t[0] for t in json.loads(tag_row[0])][:8] if tag_row else []
    in_playlists = [r[0] for r in conn.execute(
        'SELECT p.vibe_key FROM playlist_items pi JOIN playlists p USING(playlist_id) WHERE pi.track_id = ?',
        (track_id,))]
    summary = conn.execute('SELECT vibe_summary FROM classified WHERE track_id = ?', (track_id,)).fetchone()
    added_at = conn.execute('SELECT added_at FROM liked WHERE track_id = ?', (track_id,)).fetchone()
    suggestions = [{'vibe_key': k, 'score': s, 'reason': r, 'status': st} for k, s, r, st in conn.execute(
        'SELECT vibe_key, score, reason, status FROM suggestions WHERE track_id = ? ORDER BY score DESC',
        (track_id,))]
    return {'track_id': track_id, 'name': name, 'artists': [a['name'] for a in artists], 'album': album,
            'year': (release or '')[:4], 'uri': uri, 'genres': genres[:6], 'tags': tags,
            'in_playlists': in_playlists, 'liked_at': added_at[0] if added_at else None,
            'vibe_summary': summary[0] if summary else None, 'suggestions': suggestions}


def apply_decisions(conn, items):
    """items: [{'track_id', 'vibe_key', 'status'}], status in EDITABLE or 'removed'.

    Returns {'changed': [item + 'previous'], 'skipped': [item + 'reason']}. Undo = re-submit
    each changed item with status=previous ('removed' when previous is None).
    """
    changed, skipped = [], []
    for item in items:
        tid, vibe, new = item['track_id'], item['vibe_key'], item['status']
        if vibe not in VIBES:
            skipped.append({**item, 'reason': 'unknown playlist'})
            continue
        row = conn.execute('SELECT status, reason FROM suggestions WHERE track_id = ? AND vibe_key = ?',
                           (tid, vibe)).fetchone()
        if new == 'removed':
            if row and row[1] == MANUAL and row[0] in EDITABLE:
                conn.execute('DELETE FROM suggestions WHERE track_id = ? AND vibe_key = ?', (tid, vibe))
                changed.append({**item, 'previous': row[0]})
            else:
                skipped.append({**item, 'reason': 'only manual rows can be removed'})
            continue
        if new not in EDITABLE:
            skipped.append({**item, 'reason': f'bad status {new}'})
            continue
        if row is None:
            if new != 'approved':
                skipped.append({**item, 'reason': 'no suggestion to update'})
                continue
            if conn.execute('SELECT 1 FROM playlist_items pi JOIN playlists p USING(playlist_id) '
                            'WHERE pi.track_id = ? AND p.vibe_key = ?', (tid, vibe)).fetchone():
                skipped.append({**item, 'reason': 'already in that playlist'})
                continue
            conn.execute('INSERT INTO suggestions (track_id, vibe_key, score, reason, status, decided_at) '
                         'VALUES (?, ?, NULL, ?, ?, ?)', (tid, vibe, MANUAL, new, _now()))
            changed.append({**item, 'previous': None})
            continue
        if row[0] not in EDITABLE:
            skipped.append({**item, 'reason': f'already {row[0]}'})
            continue
        if row[0] != new:
            conn.execute('UPDATE suggestions SET status = ?, decided_at = ? WHERE track_id = ? AND vibe_key = ?',
                         (new, _now(), tid, vibe))
            changed.append({**item, 'previous': row[0]})
    conn.commit()
    return {'changed': changed, 'skipped': skipped}
