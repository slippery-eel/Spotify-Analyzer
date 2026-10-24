"""Classify liked songs into vibe playlists with gpt-4o-mini.

Each batch of songs is sent with every vibe playlist's definition (your description, hard rule,
reviewed/drafted profile text, typical example songs). The model returns a one-line vibe summary
per song and every playlist it fits with a 0-100 score and a reason. Scores >= MIN_SCORE become
'pending' suggestions for the Review page; playlists a song (or another version of it) is already
in are never suggested.

Pilot mode classifies a small mix: liked songs in no vibe playlist, plus "holdout" songs that
already are in vibe playlists. The model isn't told where holdout songs live, so comparing its
picks with their real playlists measures accuracy before paying for the whole library.

Usage: python classify.py pilot | all
"""
import json
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import openai

import config
import profiles
import storage
import sync

MODEL = 'gpt-4o-mini'
BATCH_SIZE = 20
MIN_SCORE = 60
LYRICS_CHARS = 600
# USD per 1M tokens for gpt-4o-mini (input, cached input, output); for estimates only
PRICE = {'input': 0.15, 'cached': 0.075, 'output': 0.60}
PILOT_UNSORTED = 40
N_RANGE_EXAMPLES = 8
PILOT_HOLDOUT = 20


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ---------- prompt ----------

def playlist_examples(conn):
    """{vibe: (size, typical examples, extra range examples)}. The extra examples are a fixed random
    sample so the model sees each playlist's range, not only its most typical songs."""
    profs = {p['key']: p for p in profiles.list_profiles(conn)}
    members = {}
    for vibe, tid, name, aj in conn.execute(
            'SELECT p.vibe_key, t.track_id, t.name, t.artists_json FROM playlist_items pi JOIN playlists p USING(playlist_id) '
            'JOIN tracks t USING(track_id) WHERE p.vibe_key IS NOT NULL ORDER BY t.track_id'):
        artists = json.loads(aj)
        members.setdefault(vibe, []).append({'track_id': tid, 'name': name, 'artist': artists[0]['name'] if artists else ''})
    out = {}
    for v in config.VIBE_PLAYLISTS:
        stats = (profs.get(v['key']) or {}).get('stats')
        typical = stats['examples'] if stats else []
        seen = {e['track_id'] for e in typical}
        pool = [m for m in members.get(v['key'], []) if m['track_id'] not in seen]
        more = random.Random(v['key']).sample(pool, min(N_RANGE_EXAMPLES, len(pool)))
        out[v['key']] = (len(members.get(v['key'], [])), typical, more)
    return out


def playlist_block(conn):
    """Static part of the prompt: every vibe playlist's definition. Kept identical across batches
    so OpenAI's automatic prompt caching applies."""
    profs = {p['key']: p for p in profiles.list_profiles(conn)}
    examples = playlist_examples(conn)
    liked = conn.execute('SELECT COUNT(*) FROM liked').fetchone()[0] or 1
    song = lambda e: f"{e['name']} - {e['artist']}"  # noqa: E731
    parts = []
    for v in config.VIBE_PLAYLISTS:
        p = profs.get(v['key'], {})
        size, typical, more = examples[v['key']]
        share = size * 100 // liked
        breadth = ('a BROAD playlist: many songs belong here' if share >= 15 else
                   'a mid-sized playlist' if share >= 5 else 'a narrow, selective playlist')
        lines = [f"### {v['key']}  (\"{v['name']}\")",
                 f"Size: {size} songs (about {share}% of the liked library), {breadth}.",
                 f"Owner's description: {v['description']}"]
        if v.get('rule'):
            lines.append(f"HARD RULE: {v['rule']}")
        if p.get('profile_text'):
            lines.append('Profile:\n' + p['profile_text'])
        if typical:
            lines.append('Typical songs: ' + '; '.join(song(e) for e in typical))
        if more:
            lines.append('More songs in it: ' + '; '.join(song(e) for e in more))
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


SYSTEM = """You sort songs into a listener's personal "vibe" playlists.
For each song, judge its sound, energy, mood and lyrics against EVERY playlist below. The owner's
descriptions matter most; the profile and typical songs show what the owner actually puts there.
A song can fit several playlists, or none. Use what you know about the song and artist, plus the
genres, tags and lyrics provided.

The owner sorts generously: most songs belong in 2-4 playlists, and BROAD playlists hold a large
share of the library, so don't reserve them for perfect matches. "artist_history" shows where the
owner put OTHER songs by the same artist; it is strong evidence of their taste, though each song is
still judged on its own sound and mood.

Scores: 90-100 = obviously belongs; 75-89 = strong fit; 60-74 = plausible, owner should decide.
Use the whole range. Only list playlists scoring 60 or more. Never break a HARD RULE.
Each reason: one short sentence naming the specific quality that fits (not just the genre).
"vibe": one short phrase describing the song's sound and mood.

PLAYLISTS
"""


def _lyrics_excerpt(text):
    if not text:
        return None
    seen, lines = set(), []
    for line in text.splitlines():
        line = line.strip()
        if line and line.lower() not in seen:  # drop repeated chorus lines to fit more of the song
            seen.add(line.lower())
            lines.append(line)
    excerpt = ' / '.join(lines)
    return excerpt[:LYRICS_CHARS] + ('…' if len(excerpt) > LYRICS_CHARS else '')


def artist_placements(conn):
    """artist_id -> [(song dedupe key, vibe key)] for every vibe-playlist song by that artist."""
    out = {}
    for vibe, name, aj in conn.execute(
            'SELECT p.vibe_key, t.name, t.artists_json FROM playlist_items pi JOIN playlists p USING(playlist_id) '
            'JOIN tracks t USING(track_id) WHERE p.vibe_key IS NOT NULL'):
        artists = json.loads(aj)
        key = sync.normalize_for_dedup(name, artists[0]['name'] if artists else '')
        for a in artists:
            out.setdefault(a.get('id'), []).append((key, vibe))
    return out


def artist_history(placements, names, name, artists):
    """Where the owner put other songs by these artists (never this song or its other versions)."""
    own = sync.normalize_for_dedup(name, artists[0]['name'] if artists else '')
    counts = Counter()
    for a in artists:
        counts.update(v for key, v in placements.get(a.get('id'), []) if key != own)
    return ', '.join(f'{names[v]} x{n}' for v, n in counts.most_common(5))


def song_entries(conn, track_ids):
    genres = {a: json.loads(g) for a, g in conn.execute('SELECT artist_id, genres_json FROM artists')}
    placements = artist_placements(conn)
    names = {v['key']: v['key'] for v in config.VIBE_PLAYLISTS}
    out = []
    for i, tid in enumerate(track_ids, 1):
        name, aj, album, release = conn.execute(
            'SELECT name, artists_json, album, release_date FROM tracks WHERE track_id = ?', (tid,)).fetchone()
        artists = json.loads(aj)
        g = sorted({x for a in artists for x in genres.get(a.get('id'), [])})
        tag_row = conn.execute('SELECT tags_json FROM track_tags WHERE track_id = ?', (tid,)).fetchone()
        lyr = conn.execute('SELECT plain_lyrics, instrumental FROM lyrics WHERE track_id = ?', (tid,)).fetchone()
        entry = {'id': f's{i}', 'title': name, 'artists': ', '.join(a['name'] for a in artists),
                 'album': album, 'year': (release or '')[:4]}
        if g:
            entry['genres'] = ', '.join(g[:8])
        if tag_row and json.loads(tag_row[0]):
            entry['tags'] = ', '.join(t[0] for t in json.loads(tag_row[0])[:8])
        history = artist_history(placements, names, name, artists)
        if history:
            entry['artist_history'] = history
        if lyr and lyr[1]:
            entry['instrumental'] = True
        elif lyr and lyr[0]:
            entry['lyrics_excerpt'] = _lyrics_excerpt(lyr[0])
        out.append(entry)
    return out


def response_schema():
    keys = [v['key'] for v in config.VIBE_PLAYLISTS]
    match = {'type': 'object', 'additionalProperties': False, 'required': ['playlist', 'score', 'reason'],
             'properties': {'playlist': {'type': 'string', 'enum': keys}, 'score': {'type': 'integer'},
                            'reason': {'type': 'string'}}}
    song = {'type': 'object', 'additionalProperties': False, 'required': ['id', 'vibe', 'matches'],
            'properties': {'id': {'type': 'string'}, 'vibe': {'type': 'string'},
                           'matches': {'type': 'array', 'items': match}}}
    return {'name': 'vibe_classification', 'strict': True,
            'schema': {'type': 'object', 'additionalProperties': False, 'required': ['songs'],
                       'properties': {'songs': {'type': 'array', 'items': song}}}}


def call_model(client, system_prompt, entries, instruction='Classify these songs:', schema=None):
    """Returns (parsed songs list, usage dict). fitcheck.py passes its own instruction and schema."""
    r = client.chat.completions.create(
        model=MODEL, temperature=0.2,
        messages=[{'role': 'system', 'content': system_prompt},
                  {'role': 'user', 'content': instruction + '\n' + json.dumps(entries, ensure_ascii=False)}],
        response_format={'type': 'json_schema', 'json_schema': schema or response_schema()})
    u = r.usage
    cached = getattr(getattr(u, 'prompt_tokens_details', None), 'cached_tokens', 0) or 0
    usage = {'input': u.prompt_tokens - cached, 'cached': cached, 'output': u.completion_tokens}
    return json.loads(r.choices[0].message.content)['songs'], usage


def is_quota_error(e):
    return isinstance(e, openai.RateLimitError) and 'insufficient_quota' in str(e)


# ---------- saving ----------

def covered_vibes(conn):
    """track_id -> vibe keys it's already in, counting other versions of the same song."""
    by_key = {}
    direct = {}
    for vibe, tid, name, aj in conn.execute(
            'SELECT p.vibe_key, t.track_id, t.name, t.artists_json FROM playlist_items pi '
            'JOIN playlists p USING(playlist_id) JOIN tracks t USING(track_id) WHERE p.vibe_key IS NOT NULL'):
        a = json.loads(aj)
        by_key.setdefault(sync.normalize_for_dedup(name, a[0]['name'] if a else ''), set()).add(vibe)
        direct.setdefault(tid, set()).add(vibe)
    out = {}
    for tid, name, aj in conn.execute('SELECT track_id, name, artists_json FROM tracks'):
        a = json.loads(aj)
        v = direct.get(tid, set()) | by_key.get(sync.normalize_for_dedup(name, a[0]['name'] if a else ''), set())
        if v:
            out[tid] = v
    return out


def save_results(conn, track_ids, songs, covered):
    """Store vibe summaries and suggestions. Returns {track_id: [(vibe, score, reason), ...]} of
    every match the model gave (including covered ones, for accuracy checks)."""
    by_id = {s['id']: s for s in songs}
    valid = {v['key'] for v in config.VIBE_PLAYLISTS}
    all_matches = {}
    now = _now()
    for i, tid in enumerate(track_ids, 1):
        s = by_id.get(f's{i}')
        if not s:
            continue
        matches = []
        for m in s['matches']:
            score = max(0, min(100, int(m['score'])))
            if m['playlist'] in valid and score >= MIN_SCORE:
                matches.append((m['playlist'], score, m['reason'].strip()))
        all_matches[tid] = matches
        conn.execute('INSERT OR REPLACE INTO classified (track_id, vibe_summary, classified_at) VALUES (?, ?, ?)',
                     (tid, s['vibe'].strip(), now))
        # Re-classifying replaces old undecided suggestions; decisions you made are kept
        conn.execute("DELETE FROM suggestions WHERE track_id = ? AND status = 'pending' AND score IS NOT NULL", (tid,))
        for vibe, score, reason in matches:
            if vibe in covered.get(tid, ()):
                continue
            conn.execute('INSERT OR IGNORE INTO suggestions (track_id, vibe_key, score, reason, status, classified_at) '
                         "VALUES (?, ?, ?, ?, 'pending', ?)", (tid, vibe, score, reason, now))
    conn.commit()
    return all_matches


# ---------- runs ----------

def _cost(usage):
    return sum(usage[k] * PRICE[k] for k in PRICE) / 1_000_000


def run_batches(conn, track_ids, progress, client=None):
    """Classify track_ids in batches. Returns (all_matches, usage, failed_batches, stopped_reason)."""
    client = client or openai.OpenAI(api_key=config.OPENAI_API_KEY)
    system_prompt = SYSTEM + playlist_block(conn)
    covered = covered_vibes(conn)
    usage = {'input': 0, 'cached': 0, 'output': 0}
    all_matches, failed, stopped = {}, 0, None
    batches = [track_ids[i:i + BATCH_SIZE] for i in range(0, len(track_ids), BATCH_SIZE)]
    for n, batch in enumerate(batches, 1):
        progress(f'Classifying batch {n}/{len(batches)}', (n - 1) * BATCH_SIZE, len(track_ids))
        entries = song_entries(conn, batch)
        for attempt in (1, 2):
            try:
                songs, u = call_model(client, system_prompt, entries)
                for k in usage:
                    usage[k] += u[k]
                all_matches.update(save_results(conn, batch, songs, covered))
                break
            except Exception as e:  # noqa: BLE001 - report, retry once, then skip the batch
                if is_quota_error(e):
                    stopped = 'OpenAI quota exceeded; add credit and run again to continue'
                    break
                if attempt == 2:
                    failed += 1
                else:
                    time.sleep(5)
        if stopped:
            break
    progress('Classifying', len(track_ids), len(track_ids))
    return all_matches, usage, failed, stopped


def pick_pilot(conn, seed=7):
    """40 liked songs in no vibe playlist + 20 holdout songs already in vibe playlists
    (never one of the example songs the prompt shows, which would give the answer away)."""
    rnd = random.Random(seed)
    covered = covered_vibes(conn)
    liked = [r[0] for r in conn.execute('SELECT track_id FROM liked ORDER BY track_id')]
    examples = {e['track_id'] for _, typical, more in playlist_examples(conn).values() for e in typical + more}
    unsorted = [t for t in liked if t not in covered]
    holdout = [t for t in liked if t in covered and t not in examples]
    return rnd.sample(unsorted, min(PILOT_UNSORTED, len(unsorted))), rnd.sample(holdout, min(PILOT_HOLDOUT, len(holdout)))


def evaluate(holdout, all_matches, covered):
    """How well picks for holdout songs match the playlists they're really in."""
    actual_total = hit = songs_hit = picked_total = picked_right = 0
    misses = []
    for tid in holdout:
        actual = covered.get(tid, set())
        picked = {v for v, _, _ in all_matches.get(tid, [])}
        actual_total += len(actual)
        hit += len(actual & picked)
        picked_total += len(picked)
        picked_right += len(actual & picked)
        songs_hit += bool(actual & picked)
        if actual - picked:
            misses.append({'track_id': tid, 'actual': sorted(actual), 'picked': sorted(picked)})
    return {'songs': len(holdout),
            'recall': round(hit * 100 / actual_total) if actual_total else None,
            'songs_with_a_hit': round(songs_hit * 100 / len(holdout)) if holdout else None,
            'precision': round(picked_right * 100 / picked_total) if picked_total else None,
            'misses': misses}


def run_pilot(progress=lambda *a, **k: None, client=None):
    if not config.OPENAI_API_KEY and client is None:
        raise RuntimeError('Set OPENAI_API_KEY in .env first.')
    storage.init_db()
    conn = storage.get_connection()
    try:
        unsorted, holdout = pick_pilot(conn)
        covered = covered_vibes(conn)
        ids = unsorted + holdout
        all_matches, usage, failed, stopped = run_batches(conn, ids, progress, client)
        ev = evaluate(holdout, all_matches, covered)
        per_song = _cost(usage) / max(len(all_matches), 1)
        remaining = conn.execute('SELECT COUNT(*) FROM liked WHERE track_id NOT IN (SELECT track_id FROM classified)').fetchone()[0]
        report = {'at': _now(), 'model': MODEL, 'classified': len(all_matches), 'unsorted': len(unsorted),
                  'holdout': ev, 'usage': usage, 'cost': round(_cost(usage), 4),
                  'remaining': remaining, 'est_full_cost': round(per_song * remaining, 2),
                  'failed_batches': failed, 'stopped': stopped,
                  'suggested': sum(1 for t in unsorted if all_matches.get(t))}
        storage.set_meta(conn, 'pilot_report', json.dumps(report))
        conn.commit()
    finally:
        conn.close()
    if stopped:
        raise RuntimeError(stopped)
    return (f"Pilot: {report['classified']} songs, {ev['recall']}% of known playlist placements found "
            f"({ev['songs_with_a_hit']}% of test songs got at least one right). Cost ${report['cost']:.3f}; "
            f"all {remaining} remaining songs ≈ ${report['est_full_cost']:.2f}")


def run_all(progress=lambda *a, **k: None, client=None):
    if not config.OPENAI_API_KEY and client is None:
        raise RuntimeError('Set OPENAI_API_KEY in .env first.')
    storage.init_db()
    conn = storage.get_connection()
    try:
        ids = [r[0] for r in conn.execute('SELECT track_id FROM liked WHERE track_id NOT IN '
                                          '(SELECT track_id FROM classified) ORDER BY added_at DESC')]
        all_matches, usage, failed, stopped = run_batches(conn, ids, progress, client)
    finally:
        conn.close()
    summary = (f'{len(all_matches)} songs classified, '
               f'{sum(1 for m in all_matches.values() if m)} with suggestions. Cost ${_cost(usage):.2f}')
    if failed:
        summary += f'; {failed} batches failed, run again to retry them'
    if stopped:
        raise RuntimeError(f'{stopped} ({summary})')
    return summary


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    mode = (sys.argv[1:] or [''])[0]
    progress = lambda msg, done=None, total=None: print(f'  {msg}')  # noqa: E731
    if mode == 'pilot':
        print(run_pilot(progress))
    elif mode == 'all':
        print(run_all(progress))
    else:
        print('Usage: python classify.py pilot | all')


if __name__ == '__main__':
    main()
