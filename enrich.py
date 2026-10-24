"""Add Last.fm tags and LRCLIB lyrics to every synced track (liked + vibe playlist songs).

Results, including misses, are cached in track_tags / lyrics so re-runs only fetch new tracks.
Tags: track.getTopTags, retried with a cleaned title, falling back to artist.getTopTags.
Lyrics: LRCLIB /api/get (exact match on title/artist/album/duration), falling back to /api/search.

Usage: python enrich.py            (tags + lyrics)
       python enrich.py tags|lyrics
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

import config
import storage

LASTFM_URL = 'https://ws.audioscrobbler.com/2.0/'
LRCLIB_URL = 'https://lrclib.net/api'
USER_AGENT = 'Spotify-Analyzer/0.1 (personal playlist sorter)'
LASTFM_MIN_INTERVAL = 0.22  # Last.fm asks for <= 5 requests/second
MIN_TAG_COUNT = 5
MAX_TAGS = 12
JUNK_TAGS = {'seen live', 'favorites', 'favourites', 'favorite', 'my favorites', 'love', 'awesome',
             'beautiful', 'spotify', 'under 2000 listeners', 'albums i own', 'check out', 'good'}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def clean_title(title):
    """'Song (feat. X) - Remastered 2011' -> 'Song'. Used only as a lookup retry."""
    t = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)
    t = re.sub(r'\s+-\s+.*$', '', t)
    return t.strip() or title


def filter_tags(raw_tags):
    """Last.fm tag list -> cleaned [(name, count)] keeping meaningful, reasonably-weighted tags."""
    out, seen = [], set()
    for t in raw_tags:
        name = t.get('name', '').strip().lower()
        count = int(t.get('count', 0))
        if not name or name in seen or name in JUNK_TAGS or re.fullmatch(r"\d{2,4}s?|'\d0s", name):
            continue
        if count < MIN_TAG_COUNT:
            continue
        seen.add(name)
        out.append((name, count))
    return out[:MAX_TAGS]


# ---------- Last.fm ----------

_last_call = [0.0]


def _lastfm(method, **params):
    wait = LASTFM_MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    for attempt in range(3):
        try:
            r = requests.get(LASTFM_URL, params={'method': method, 'api_key': config.LASTFM_API_KEY,
                                                  'format': 'json', 'autocorrect': 1, **params},
                             headers={'User-Agent': USER_AGENT}, timeout=20)
            data = r.json()
        except (requests.RequestException, ValueError):
            time.sleep(2 * (attempt + 1))
            continue
        if data.get('error') == 29:  # rate limit exceeded
            time.sleep(5)
            continue
        return data
    return {}


def fetch_tags(title, artist, artist_cache):
    """Returns (tags, source) where source is 'track', 'artist' or 'none'."""
    for t in dict.fromkeys([title, clean_title(title)]):
        data = _lastfm('track.gettoptags', artist=artist, track=t)
        tags = filter_tags(data.get('toptags', {}).get('tag', []))
        if tags:
            return tags, 'track'
    if artist not in artist_cache:
        data = _lastfm('artist.gettoptags', artist=artist)
        artist_cache[artist] = filter_tags(data.get('toptags', {}).get('tag', []))
    if artist_cache[artist]:
        return artist_cache[artist], 'artist'
    return [], 'none'


def enrich_tags(conn):
    rows = conn.execute('SELECT track_id, name, artists_json FROM tracks '
                        'WHERE track_id NOT IN (SELECT track_id FROM track_tags)').fetchall()
    print(f'Last.fm tags: {len(rows)} tracks to fetch')
    artist_cache = {}
    for i, (track_id, name, aj) in enumerate(rows, 1):
        artist = json.loads(aj)[0]['name']
        tags, source = fetch_tags(name, artist, artist_cache)
        conn.execute('INSERT OR REPLACE INTO track_tags (track_id, tags_json, source, fetched_at) VALUES (?, ?, ?, ?)',
                     (track_id, json.dumps(tags), source, _now()))
        if i % 50 == 0:
            conn.commit()
            print(f'  tags {i}/{len(rows)}')
    conn.commit()


# ---------- LRCLIB ----------

def fetch_lyrics(title, artist, album, duration_ms):
    """Returns (plain_lyrics or None, instrumental bool, found bool)."""
    headers = {'User-Agent': USER_AGENT}
    params = {'track_name': title, 'artist_name': artist}
    attempts = [('get', {**params, 'album_name': album or '', 'duration': round((duration_ms or 0) / 1000)})]
    attempts.append(('search', params))
    if clean_title(title) != title:
        attempts.append(('search', {**params, 'track_name': clean_title(title)}))
    for kind, p in attempts:
        try:
            r = requests.get(f'{LRCLIB_URL}/{kind}', params=p, headers=headers, timeout=20)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        data = r.json()
        if kind == 'search':
            data = data[0] if data else None
        if not data:
            continue
        instrumental = str(data.get('instrumental')).lower() == 'true'
        if data.get('plainLyrics') or instrumental:
            return data.get('plainLyrics'), instrumental, True
    return None, False, False


def enrich_lyrics(conn):
    rows = conn.execute('SELECT track_id, name, artists_json, album, duration_ms FROM tracks '
                        'WHERE track_id NOT IN (SELECT track_id FROM lyrics)').fetchall()
    print(f'LRCLIB lyrics: {len(rows)} tracks to fetch')

    def work(row):
        track_id, name, aj, album, dur = row
        return track_id, fetch_lyrics(name, json.loads(aj)[0]['name'], album, dur)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, (track_id, (text, instrumental, found)) in enumerate(pool.map(work, rows), 1):
            conn.execute('INSERT OR REPLACE INTO lyrics (track_id, plain_lyrics, instrumental, found, fetched_at) '
                         'VALUES (?, ?, ?, ?, ?)', (track_id, text, int(instrumental), int(found), _now()))
            if i % 50 == 0:
                conn.commit()
                print(f'  lyrics {i}/{len(rows)}')
    conn.commit()


def report(conn):
    q = lambda s: conn.execute(s).fetchone()[0]
    total = q('SELECT COUNT(*) FROM tracks')
    print('\n=== Enrichment report ===')
    for source in ('track', 'artist', 'none'):
        n = q(f"SELECT COUNT(*) FROM track_tags WHERE source = '{source}'")
        print(f'Tags from {source:>6}: {n:5} ({n * 100 // max(total, 1)}%)')
    lyr = q('SELECT COUNT(*) FROM lyrics WHERE plain_lyrics IS NOT NULL')
    inst = q('SELECT COUNT(*) FROM lyrics WHERE instrumental = 1')
    miss = q('SELECT COUNT(*) FROM lyrics WHERE found = 0')
    print(f'Lyrics found: {lyr} ({lyr * 100 // max(total, 1)}%), instrumental: {inst}, not found: {miss}')
    no_signal = q("""SELECT COUNT(*) FROM tracks t
        WHERE t.track_id IN (SELECT track_id FROM track_tags WHERE source = 'none')
          AND NOT EXISTS (SELECT 1 FROM json_each(t.artists_json) j
                          JOIN artists a ON a.artist_id = json_extract(j.value, '$.id')
                          WHERE a.genres_json != '[]')""")
    print(f'Tracks with no tags AND no Spotify genres: {no_signal}')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if not config.LASTFM_API_KEY:
        sys.exit('Set LASTFM_API_KEY in .env first.')
    which = sys.argv[1:] or ['tags', 'lyrics']
    storage.init_db()
    conn = storage.get_connection()
    try:
        if 'tags' in which:
            enrich_tags(conn)
        if 'lyrics' in which:
            enrich_lyrics(conn)
        report(conn)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
