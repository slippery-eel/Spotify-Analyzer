"""Vibe profiles: a summary of each vibe playlist drawn from the songs already in it.

The draft is built from local data only (no API calls): common and distinctive genres/tags,
eras, how much is instrumental, frequent artists, overlap with other vibe playlists, and
"typical" example songs. You then edit the text in the app; edited text survives re-drafts.
The classifier uses your description + this profile text + the example songs.

Usage: python profiles.py   (draft/refresh all profiles and print them)
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone

import config
import storage

N_EXAMPLES = 8
MIN_DISTINCTIVE_ARTISTS = 2   # a label must come from 2+ artists, so one artist can't define a playlist
MIN_LIFT = 1.5
# Place/nationality tags describe where an artist is from, not how a song feels (plus junk tags)
SKIP_TAGS = {'all', 'american', 'british', 'english', 'uk', 'usa', 'french', 'france', 'german', 'germany', 'australian',
              'australia', 'canadian', 'canada', 'swedish', 'sweden', 'danish', 'denmark', 'norwegian', 'norway',
              'icelandic', 'iceland', 'irish', 'scottish', 'dutch', 'belgian', 'polish', 'japanese', 'korean',
              'italian', 'spanish', 'brazilian', 'mexican', 'new zealand', 'south africa', 'south african',
              'los angeles', 'london', 'new york', 'brooklyn', 'seattle', 'chicago', 'portland', 'nordic'}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _labels_by_track(conn):
    """track_id -> set of Spotify artist genres + top Last.fm tags."""
    genres = {a: json.loads(g) for a, g in conn.execute('SELECT artist_id, genres_json FROM artists')}
    tags = {t: [x[0] for x in json.loads(tj)[:6]] for t, tj in conn.execute('SELECT track_id, tags_json FROM track_tags')}
    out = {}
    for tid, aj in conn.execute('SELECT track_id, artists_json FROM tracks'):
        labels = set(tags.get(tid, []))
        for a in json.loads(aj):
            labels.update(genres.get(a.get('id'), []))
        out[tid] = {l for l in labels if l not in SKIP_TAGS}
    return out


def compute(conn):
    """Stats + examples for every matched vibe playlist. Returns {vibe_key: dict}."""
    labels = _labels_by_track(conn)
    members = {}
    for vibe, tid in conn.execute('SELECT p.vibe_key, pi.track_id FROM playlist_items pi '
                                  'JOIN playlists p USING(playlist_id) WHERE p.vibe_key IS NOT NULL'):
        members.setdefault(vibe, []).append(tid)
    # Baseline: liked songs + every vibe-playlist song, so "distinctive" means distinctive for *your* library
    base_ids = {r[0] for r in conn.execute('SELECT track_id FROM liked')} | {t for ids in members.values() for t in ids}
    base = Counter(l for t in base_ids for l in labels.get(t, ()))
    base_n = max(len(base_ids), 1)
    tracks = {tid: (name, json.loads(aj), rel) for tid, name, aj, rel in
              conn.execute('SELECT track_id, name, artists_json, release_date FROM tracks')}
    lyr = {tid: (inst, found, text is not None) for tid, inst, found, text in
           conn.execute('SELECT track_id, instrumental, found, plain_lyrics FROM lyrics')}
    names = {v['key']: v['name'] for v in config.VIBE_PLAYLISTS}

    out = {}
    for vibe, ids in members.items():
        n = len(ids)
        cnt = Counter(l for t in ids for l in labels.get(t, ()))
        common = [(l, c * 100 // n) for l, c in cnt.most_common(10)]
        label_artists = {}
        for t in ids:
            for l in labels.get(t, ()):
                label_artists.setdefault(l, set()).add(tracks[t][1][0]['name'] if tracks[t][1] else '')
        # Rank by how much bigger the label's share is here than across the library (percentage points),
        # which favours labels that are both common here and over-represented
        distinctive = sorted(
            ((l, c, (c / n) / (base[l] / base_n), c / n - base[l] / base_n) for l, c in cnt.items()
             if len(label_artists[l]) >= MIN_DISTINCTIVE_ARTISTS and (c / n) / (base[l] / base_n) >= MIN_LIFT),
            key=lambda x: -x[3])[:10]
        decades = Counter()
        for t in ids:
            year = (tracks[t][2] or '')[:4]
            if year.isdigit():
                decades[f'{year[:3]}0s'] += 1
        known = [lyr[t] for t in ids if t in lyr and (lyr[t][0] or lyr[t][2])]
        instrumental_pct = sum(1 for inst, _, _ in known if inst) * 100 // len(known) if known else None
        artists = Counter(tracks[t][1][0]['name'] for t in ids if tracks[t][1])
        overlaps = sorted(((other, len(set(ids) & set(o_ids)) * 100 // n)
                           for other, o_ids in members.items() if other != vibe), key=lambda x: -x[1])
        # Typical songs: label sets closest to the playlist's overall mix. Dividing by sqrt(#labels)
        # stops songs that simply have many tags from always winning.
        weight = {l: c / n for l, c in cnt.items()}

        def typicality(t):
            ls = labels.get(t, ())
            return sum(weight[l] for l in ls) / (len(ls) ** 0.5) if ls else 0
        scored = sorted(ids, key=lambda t: (-typicality(t), tracks[t][0]))
        seen_artists, examples = set(), []
        for t in scored:  # one song per artist so examples show the playlist's range
            artist = tracks[t][1][0]['name'] if tracks[t][1] else ''
            if artist in seen_artists:
                continue
            seen_artists.add(artist)
            examples.append({'track_id': t, 'name': tracks[t][0], 'artist': artist})
            if len(examples) == N_EXAMPLES:
                break
        out[vibe] = {
            'size': n,
            'common': common,
            'distinctive': [(l, round(lift, 1)) for l, _, lift, _ in distinctive],
            'decades': [(d, c * 100 // n) for d, c in decades.most_common(3)],
            'instrumental_pct': instrumental_pct,
            'artists': artists.most_common(6),
            'overlaps': [(names.get(o, o), p) for o, p in overlaps[:3] if p >= 10],
            'examples': examples,
        }
    return out


def draft_text(stats):
    """Plain-language draft you edit in the app."""
    lines = []
    if stats['distinctive']:
        lines.append('Stands out for: ' + ', '.join(l for l, _ in stats['distinctive'][:6]) + '.')
    if stats['common']:
        lines.append('Common sounds: ' + ', '.join(f'{l} ({p}%)' for l, p in stats['common'][:6]) + '.')
    if stats['decades']:
        top, p = stats['decades'][0]
        rest = ', '.join(d for d, _ in stats['decades'][1:])
        lines.append(f'Era: mostly {top} ({p}%)' + (f', some {rest}.' if rest else '.'))
    ip = stats['instrumental_pct']
    if ip is not None:
        lines.append('Vocals: ' + ('mostly instrumental' if ip >= 60 else 'mix of vocal and instrumental' if ip >= 25
                                   else 'mostly songs with vocals') + f' ({ip}% instrumental).')
    if stats['artists']:
        lines.append('Frequent artists: ' + ', '.join(a for a, _ in stats['artists'][:5]) + '.')
    if stats['overlaps']:
        lines.append('Overlaps with: ' + ', '.join(f'{n} ({p}% of these songs)' for n, p in stats['overlaps']) + '.')
    return '\n'.join(lines)


def draft_all(conn, progress=lambda *a, **k: None):
    """(Re)draft every profile. Edited text is kept; stats/examples/draft always refresh.
    Returns (drafted, kept_edits)."""
    stats = compute(conn)
    drafted = kept = 0
    for i, (vibe, s) in enumerate(stats.items(), 1):
        draft = draft_text(s)
        row = conn.execute('SELECT is_edited FROM playlist_profiles WHERE vibe_key = ?', (vibe,)).fetchone()
        if row and row[0]:
            conn.execute('UPDATE playlist_profiles SET draft_text = ?, stats_json = ?, updated_at = ? WHERE vibe_key = ?',
                         (draft, json.dumps(s), _now(), vibe))
            kept += 1
        else:
            conn.execute('INSERT OR REPLACE INTO playlist_profiles (vibe_key, profile_text, draft_text, stats_json, '
                         'is_edited, reviewed_at, updated_at) VALUES (?, ?, ?, ?, 0, '
                         '(SELECT reviewed_at FROM playlist_profiles WHERE vibe_key = ?), ?)',
                         (vibe, draft, draft, json.dumps(s), vibe, _now()))
            drafted += 1
        progress('Drafting profiles', i, len(stats))
    conn.commit()
    return drafted, kept


def list_profiles(conn):
    rows = {r[0]: r for r in conn.execute('SELECT vibe_key, profile_text, draft_text, stats_json, is_edited, '
                                          'reviewed_at, updated_at FROM playlist_profiles')}
    playlist_ids = dict(conn.execute('SELECT vibe_key, playlist_id FROM playlists WHERE vibe_key IS NOT NULL'))
    out = []
    for v in config.VIBE_PLAYLISTS:
        r = rows.get(v['key'])
        out.append({'key': v['key'], 'name': v['name'], 'description': v['description'], 'rule': v.get('rule'),
                    'playlist_id': playlist_ids.get(v['key']),
                    'profile_text': r[1] if r else None, 'draft_text': r[2] if r else None,
                    'stats': json.loads(r[3]) if r and r[3] else None, 'is_edited': bool(r[4]) if r else False,
                    'reviewed_at': r[5] if r else None, 'updated_at': r[6] if r else None})
    return out


def update_profile(conn, vibe, profile_text=None, reviewed=None, reset=False):
    row = conn.execute('SELECT draft_text FROM playlist_profiles WHERE vibe_key = ?', (vibe,)).fetchone()
    if not row:
        raise ValueError('Draft the profiles first')
    if reset:
        conn.execute('UPDATE playlist_profiles SET profile_text = draft_text, is_edited = 0, updated_at = ? '
                     'WHERE vibe_key = ?', (_now(), vibe))
    elif profile_text is not None:
        text = profile_text.strip()
        conn.execute('UPDATE playlist_profiles SET profile_text = ?, is_edited = ?, updated_at = ? WHERE vibe_key = ?',
                     (text, int(text != (row[0] or '').strip()), _now(), vibe))
    if reviewed is not None:
        conn.execute('UPDATE playlist_profiles SET reviewed_at = ? WHERE vibe_key = ?',
                     (_now() if reviewed else None, vibe))
    conn.commit()


def run(progress=lambda *a, **k: None):
    storage.init_db()
    conn = storage.get_connection()
    try:
        drafted, kept = draft_all(conn, progress)
    finally:
        conn.close()
    return f'{drafted} profiles drafted' + (f', {kept} edited profiles kept (stats refreshed)' if kept else '')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print(run())
    conn = storage.get_connection()
    try:
        for p in list_profiles(conn):
            if p['stats']:
                ex = '; '.join(f"{e['name']} - {e['artist']}" for e in p['stats']['examples'])
                print(f"\n[{p['name']}] {p['stats']['size']} songs\n{p['profile_text']}\nExamples: {ex}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
