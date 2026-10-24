"""Library and Playlists views: the original analyzer's features, served from SQLite.

Replaces script.js's browser-side Spotify calls (findLikedSongsNotInPlaylists,
getAllLikedSongsAnalysis, browsePlaylistsMode, Save as Playlist) with server-side queries
over the data sync.py already stored. Popularity is gone (Spotify removed it in Feb 2026),
so it is no longer a column or a dedupe tie-break.
"""
import json
from collections import Counter

import config
import spotify_client as sp
import sync

VIBES = {v['key']: v for v in config.VIBE_PLAYLISTS}


def _maps(conn):
    genres = {aid: json.loads(g) for aid, g in conn.execute('SELECT artist_id, genres_json FROM artists')}
    tags = {tid: [t[0] for t in json.loads(tj)] for tid, tj in conn.execute('SELECT track_id, tags_json FROM track_tags')}
    names = {}
    membership = {}
    for pid, name, tid in conn.execute('SELECT p.playlist_id, p.name, pi.track_id FROM playlist_items pi '
                                       'JOIN playlists p USING(playlist_id)'):
        names[pid] = name
        membership.setdefault(tid, []).append(pid)
    return genres, tags, membership, names


def _row(track, genres, tags, membership):
    tid, name, aj, album, release, uri, added_at = track
    artists = json.loads(aj)
    g = []
    for a in artists:
        for x in genres.get(a.get('id'), []):
            if x not in g:
                g.append(x)
    return {'track_id': tid, 'name': name, 'artists': [a['name'] for a in artists], 'album': album,
            'year': (release or '')[:4], 'uri': uri, 'added_at': added_at,
            'genres': g, 'tags': tags.get(tid, [])[:6], 'playlists': membership.get(tid, [])}


def _dedupe(rows, cover_keys=None):
    """Same key as script.js deduplicateTracks(). Keeps the version in the most playlists,
    then the most recently liked. cover_keys: keys already covered by a playlist version."""
    groups = {}
    for r in rows:
        key = sync.normalize_for_dedup(r['name'], r['artists'][0] if r['artists'] else '')
        if cover_keys and key in cover_keys:
            continue
        groups.setdefault(key, []).append(r)
    return [max(g, key=lambda r: (len(r['playlists']), r['added_at'] or '')) for g in groups.values()]


def get_library(conn, scope='liked', genre=None, artist=None, date_from=None, date_to=None,
                dedupe=False, ignore=()):
    """Liked songs with filters. scope='not_in_playlists' keeps songs in none of your playlists,
    except playlists listed in `ignore` (e.g. an old export playlist) don't count."""
    genres, tags, membership, names = _maps(conn)
    ignore = set(ignore or ())
    if ignore:
        membership = {t: [p for p in pids if p not in ignore] for t, pids in membership.items()}
    tracks = conn.execute('SELECT t.track_id, t.name, t.artists_json, t.album, t.release_date, t.uri, l.added_at '
                          'FROM liked l JOIN tracks t USING(track_id) ORDER BY l.added_at DESC').fetchall()
    rows = [_row(t, genres, tags, membership) for t in tracks]
    liked_total = len(rows)
    in_playlists = sum(1 for r in rows if r['playlists'])

    if scope == 'not_in_playlists':
        rows = [r for r in rows if not r['playlists']]
    if dedupe:
        cover = None
        if scope == 'not_in_playlists':
            cover = set()
            for (tid, name, aj) in conn.execute('SELECT DISTINCT t.track_id, t.name, t.artists_json FROM playlist_items pi '
                                                'JOIN tracks t USING(track_id)'):
                if membership.get(tid):
                    a = json.loads(aj)
                    cover.add(sync.normalize_for_dedup(name, a[0]['name'] if a else ''))
        rows = _dedupe(rows, cover)
    if genre:
        rows = [r for r in rows if genre in r['genres'] or genre in r['tags']]
    if artist:
        needle = artist.lower()
        rows = [r for r in rows if any(needle in a.lower() for a in r['artists'])]
    # Month inputs give 'YYYY-MM'; ISO timestamps compare correctly as strings
    if date_from:
        rows = [r for r in rows if (r['added_at'] or '') >= date_from]
    if date_to:
        rows = [r for r in rows if (r['added_at'] or '')[:len(date_to)] <= date_to]

    used = {p for r in rows for p in r['playlists']}
    return {'tracks': rows, 'liked_total': liked_total, 'in_playlists': in_playlists,
            'playlist_names': {p: names[p] for p in used},
            'genre_options': genre_options(conn, genres, tags),
            'analytics': analytics(rows)}


def genre_options(conn, genres=None, tags=None, limit=80):
    """Most common genres/tags across liked songs, for the filter dropdown."""
    if genres is None:
        genres, tags, _, _ = _maps(conn)
    counts = Counter()
    for tid, aj in conn.execute('SELECT t.track_id, t.artists_json FROM liked l JOIN tracks t USING(track_id)'):
        labels = set(tags.get(tid, []))
        for a in json.loads(aj):
            labels.update(genres.get(a.get('id'), []))
        counts.update(labels)
    return [{'name': g, 'count': n} for g, n in counts.most_common(limit)]


def analytics(rows):
    """Chart data, ported from script.js generateAnalytics(). Genre falls back to Last.fm tags
    when Spotify has no genres for the artist."""
    genre_counts = Counter()
    for r in rows:
        labels = r['genres'] or r['tags'][:3]
        genre_counts.update(labels or ['Unknown'])
    artist_counts = Counter(r['artists'][0] for r in rows if r['artists'])
    months = Counter((r['added_at'] or '')[:7] for r in rows if r['added_at'])
    if len(months) > 24:  # same rule as the old app: switch to yearly buckets
        timeline = sorted(Counter(m[:4] for m in months.elements()).items())
        unit = 'year'
    else:
        timeline = sorted(months.items())
        unit = 'month'
    return {'genres': genre_counts.most_common(10), 'artists': artist_counts.most_common(10),
            'timeline': timeline, 'timeline_unit': unit,
            'unique_genres': len(genre_counts), 'unique_artists': len(artist_counts)}


def list_playlists(conn):
    sizes = dict(conn.execute('SELECT playlist_id, COUNT(*) FROM playlist_items GROUP BY playlist_id'))
    liked = {r[0] for r in conn.execute('SELECT track_id FROM liked')}
    liked_in = Counter(pid for pid, tid in conn.execute('SELECT playlist_id, track_id FROM playlist_items')
                       if tid in liked)
    out = []
    for pid, vibe, name, owned, total, image in conn.execute(
            'SELECT playlist_id, vibe_key, name, is_owned, track_total, image_url FROM playlists '
            'ORDER BY vibe_key IS NULL, name COLLATE NOCASE'):
        v = VIBES.get(vibe) if vibe else None
        out.append({'playlist_id': pid, 'name': name, 'vibe_key': vibe, 'is_owned': bool(owned),
                    'track_total': total, 'synced_tracks': sizes.get(pid, 0), 'liked_tracks': liked_in.get(pid, 0),
                    'image_url': image, 'description': v['description'] if v else None})
    return out


def playlist_tracks(conn, playlist_id):
    genres, tags, membership, names = _maps(conn)
    liked = dict(conn.execute('SELECT track_id, added_at FROM liked'))
    tracks = conn.execute('SELECT t.track_id, t.name, t.artists_json, t.album, t.release_date, t.uri, pi.added_at '
                          'FROM playlist_items pi JOIN tracks t USING(track_id) WHERE pi.playlist_id = ? '
                          'ORDER BY pi.added_at', (playlist_id,)).fetchall()
    rows = []
    for t in tracks:
        r = _row(t, genres, tags, membership)
        r['liked'] = r['track_id'] in liked
        rows.append(r)
    used = {p for r in rows for p in r['playlists']}
    return {'tracks': rows, 'playlist_names': {p: names[p] for p in used}}


def save_as_playlist(conn, track_ids, name=None, playlist_id=None):
    """Create a private playlist (or add to an existing one) on Spotify, then re-sync it.

    Songs already in an existing playlist are skipped. Returns {playlist_id, name, added, skipped}.
    """
    if not track_ids:
        raise ValueError('No songs selected')
    if playlist_id:
        row = conn.execute('SELECT name, is_owned FROM playlists WHERE playlist_id = ?', (playlist_id,)).fetchone()
        if not row:
            raise ValueError('Unknown playlist')
        if not row[1]:
            raise ValueError("You can only add to playlists you own or collaborate on")
        pl_name = row[0]
        present = {r[0] for r in conn.execute('SELECT track_id FROM playlist_items WHERE playlist_id = ?', (playlist_id,))}
    else:
        if not (name or '').strip():
            raise ValueError('Playlist name is required')
        created = sp.post('/me/playlists', {'name': name.strip(), 'public': False,
                                            'description': 'Saved from Spotify Analyzer'})
        playlist_id, pl_name, present = created['id'], created['name'], set()
    to_add = [t for t in dict.fromkeys(track_ids) if t not in present]
    uris = dict(conn.execute(f"SELECT track_id, uri FROM tracks WHERE track_id IN ({','.join('?' * len(to_add))})",
                             to_add)) if to_add else {}
    batch = [uris[t] for t in to_add if t in uris]
    for i in range(0, len(batch), 100):
        sp.post(f'/playlists/{playlist_id}/items', {'uris': batch[i:i + 100]})
    sync.sync_playlists(conn, progress=lambda *a, **k: None, only_ids={playlist_id})
    return {'playlist_id': playlist_id, 'name': pl_name, 'added': len(batch), 'skipped': len(track_ids) - len(batch)}
