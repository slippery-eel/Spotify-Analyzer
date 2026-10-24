"""Fit check: how well does each song already in a vibe playlist fit that playlist?

Reuses classify.py's prompt pieces (the same cached playlist definitions, song entries with
genres/tags/lyrics/artist history) with a different question: songs from ONE playlist at a time
are rated 0-100 against that playlist, with a reason and better-fitting playlists if any.
Results go to fit_checks; your keep/remove decisions survive re-checks.

Usage: python fitcheck.py [vibe_key] [--recheck]
"""
import json
import sys
import time
from datetime import datetime, timezone

import openai

import classify
import config
import storage

BATCH_SIZE = 25

SYSTEM = """You audit a listener's personal "vibe" playlists.
You will get songs that are CURRENTLY in one playlist. For each song, judge how well it fits THAT
playlist: its sound, energy, mood and lyrics against the owner's description, profile and example
songs. The owner's description matters most. Be honest: the goal is to find songs that don't belong.

fit: 85-100 = clearly belongs; 60-84 = fits; 40-59 = questionable; 0-39 = doesn't fit.
reason: one short sentence on why it does or doesn't fit (name the specific quality; never refer to
other songs or their ids).
better: other playlists from the list that this song would fit clearly better than this one
(empty if none). Never suggest a playlist whose HARD RULE the song breaks.

PLAYLISTS
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def response_schema():
    keys = [v['key'] for v in config.VIBE_PLAYLISTS]
    song = {'type': 'object', 'additionalProperties': False, 'required': ['id', 'fit', 'reason', 'better'],
            'properties': {'id': {'type': 'string'}, 'fit': {'type': 'integer'}, 'reason': {'type': 'string'},
                           'better': {'type': 'array', 'items': {'type': 'string', 'enum': keys}}}}
    return {'name': 'playlist_fit', 'strict': True,
            'schema': {'type': 'object', 'additionalProperties': False, 'required': ['songs'],
                       'properties': {'songs': {'type': 'array', 'items': song}}}}


def members(conn, vibe):
    return [r[0] for r in conn.execute(
        'SELECT pi.track_id FROM playlist_items pi JOIN playlists p USING(playlist_id) '
        'WHERE p.vibe_key = ? ORDER BY pi.rowid', (vibe,))]


def save(conn, vibe, track_ids, songs):
    by_id = {s['id']: s for s in songs}
    saved = 0
    for i, tid in enumerate(track_ids, 1):
        s = by_id.get(f's{i}')
        if not s:
            continue
        better = [b for b in dict.fromkeys(s['better']) if b != vibe]
        conn.execute(
            'INSERT INTO fit_checks (track_id, vibe_key, fit, reason, better_json, checked_at) VALUES (?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(track_id, vibe_key) DO UPDATE SET fit = excluded.fit, reason = excluded.reason, '
            'better_json = excluded.better_json, checked_at = excluded.checked_at',
            (tid, vibe, max(0, min(100, int(s['fit']))), s['reason'].strip(), json.dumps(better), _now()))
        saved += 1
    conn.commit()
    return saved


def run(progress=lambda *a, **k: None, vibe=None, recheck=False, client=None):
    if not config.OPENAI_API_KEY and client is None:
        raise RuntimeError('Set OPENAI_API_KEY in .env first.')
    storage.init_db()
    conn = storage.get_connection()
    try:
        vibes = [vibe] if vibe else [v['key'] for v in config.VIBE_PLAYLISTS]
        checked = {(t, v) for t, v in conn.execute('SELECT track_id, vibe_key FROM fit_checks WHERE fit IS NOT NULL')}
        work = []
        for v in vibes:
            ids = [t for t in members(conn, v) if recheck or (t, v) not in checked]
            work += [(v, ids[i:i + BATCH_SIZE]) for i in range(0, len(ids), BATCH_SIZE)]
        total = sum(len(b) for _, b in work)
        if not total:
            return 'Everything is already checked'
        client = client or openai.OpenAI(api_key=config.OPENAI_API_KEY)
        system_prompt = SYSTEM + classify.playlist_block(conn)
        names = {v['key']: v['name'] for v in config.VIBE_PLAYLISTS}
        usage = {'input': 0, 'cached': 0, 'output': 0}
        saved = failed = done = 0
        for v, batch in work:
            progress(f'Checking {names[v]}', done, total)
            entries = classify.song_entries(conn, batch)
            instruction = f'These songs are currently in the playlist "{v}". Rate how well each fits it:'
            for attempt in (1, 2):
                try:
                    songs, u = classify.call_model(client, system_prompt, entries, instruction, response_schema())
                    for k in usage:
                        usage[k] += u[k]
                    saved += save(conn, v, batch, songs)
                    break
                except Exception as e:  # noqa: BLE001 - retry once, then skip the batch
                    if classify.is_quota_error(e):
                        raise RuntimeError(f'OpenAI quota exceeded after {saved} songs; add credit and run again') from e
                    if attempt == 2:
                        failed += 1
                    else:
                        time.sleep(5)
            done += len(batch)
        progress('Checking', total, total)
        low = conn.execute(f"SELECT COUNT(*) FROM fit_checks WHERE fit < 50 AND vibe_key IN ({','.join('?' * len(vibes))})",
                           vibes).fetchone()[0]
    finally:
        conn.close()
    summary = f'Checked {saved} songs, {low} look like a poor fit (score under 50). Cost ${classify._cost(usage):.2f}'
    if failed:
        summary += f'; {failed} batches failed, run again to retry them'
    return summary


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(run(lambda msg, done=None, total=None: print(f'  {msg}' + (f' ({done}/{total})' if total else '')),
              vibe=args[0] if args else None, recheck='--recheck' in sys.argv))


if __name__ == '__main__':
    main()
