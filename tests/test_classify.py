import json
from types import SimpleNamespace

import openai
import pytest

import classify
import config
import storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 'c.db'))
    monkeypatch.setattr(config, 'VIBE_PLAYLISTS', [
        {'key': 'summer', 'name': 'summer', 'description': 'beach fun'},
        {'key': 'cozy', 'name': 'cozy', 'description': 'calm'},
        {'key': 'cabins', 'name': 'Log cabins', 'description': 'folk', 'rule': 'Only acoustic or folk.'}])
    monkeypatch.setattr(classify.time, 'sleep', lambda s: None)
    storage.init_db()
    c = storage.get_connection()
    for tid, name in (('t1', 'Riptide'), ('t2', 'Riptide (Live)'), ('t3', 'Cherry'), ('t4', 'Kyoto')):
        c.execute('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (tid, name, json.dumps([{'id': 'a', 'name': 'Vance Joy' if tid < 't3' else 'Other'}]),
                   'Alb', '2015-01-01', 1, f'u:{tid}'))
        c.execute('INSERT INTO liked VALUES (?, ?)', (tid, '2026-01-01'))
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('ps', 'summer', 'summer')")
    c.execute("INSERT INTO playlist_items VALUES ('ps', 't1', 'now')")
    c.execute("INSERT INTO lyrics VALUES ('t3', 'la la\nla la\nhello there', 0, 1, 'now')")
    c.execute("INSERT INTO lyrics VALUES ('t4', NULL, 1, 1, 'now')")
    c.commit()
    yield c
    c.close()


class FakeClient:
    """Mimics client.chat.completions.create; `script` is a list of responses or exceptions."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=200,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=400))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'songs': item})))],
                               usage=usage)


def song(i, *matches):
    return {'id': f's{i}', 'vibe': f'vibe {i}', 'matches': [{'playlist': p, 'score': s, 'reason': f'r {p}'} for p, s in matches]}


def test_song_entries_lyrics_dedupe_and_instrumental(conn):
    e = classify.song_entries(conn, ['t3', 't4'])
    assert e[0]['id'] == 's1' and e[0]['lyrics_excerpt'] == 'la la / hello there'
    assert e[1]['instrumental'] is True and 'lyrics_excerpt' not in e[1]


def test_prompt_contains_rules_and_schema_enum(conn):
    block = classify.playlist_block(conn)
    assert 'HARD RULE: Only acoustic or folk.' in block and "Owner's description: beach fun" in block
    assert classify.response_schema()['schema']['properties']['songs']['items']['properties']['matches']['items'][
        'properties']['playlist']['enum'] == ['summer', 'cozy', 'cabins']


def test_saves_suggestions_skipping_low_scores_and_covered_versions(conn):
    client = FakeClient([[song(1, ('summer', 90), ('cozy', 70)), song(2, ('summer', 85), ('cabins', 40)),
                          song(3, ('cozy', 61))]])
    matches, usage, failed, stopped = classify.run_batches(conn, ['t1', 't2', 't3'], lambda *a, **k: None, client)
    rows = sorted(conn.execute('SELECT track_id, vibe_key, score FROM suggestions').fetchall())
    # t1 is in summer; t2 is another version of t1, so summer is covered for it too; cabins 40 is dropped
    assert rows == [('t1', 'cozy', 70), ('t3', 'cozy', 61)]
    assert matches['t2'] == [('summer', 85, 'r summer')]          # kept for accuracy checks
    assert usage == {'input': 600, 'cached': 400, 'output': 200} and not failed and not stopped
    assert conn.execute('SELECT COUNT(*) FROM classified').fetchone()[0] == 3


def test_reclassify_keeps_decisions(conn):
    classify.run_batches(conn, ['t3'], lambda *a, **k: None, FakeClient([[song(1, ('cozy', 70), ('summer', 65))]]))
    conn.execute("UPDATE suggestions SET status = 'declined' WHERE vibe_key = 'summer'")
    conn.commit()
    classify.run_batches(conn, ['t3'], lambda *a, **k: None, FakeClient([[song(1, ('summer', 80), ('cabins', 75))]]))
    rows = dict(conn.execute('SELECT vibe_key, status FROM suggestions').fetchall())
    assert rows == {'summer': 'declined', 'cabins': 'pending'}   # old pending 'cozy' replaced


def test_retry_then_skip_and_quota_stop(conn):
    err = ValueError('bad json')
    matches, _, failed, stopped = classify.run_batches(conn, ['t3'], lambda *a, **k: None, FakeClient([err, err]))
    assert failed == 1 and not matches and not stopped
    resp = SimpleNamespace(status_code=429, headers={}, request=None)
    quota = openai.RateLimitError('insufficient_quota', response=SimpleNamespace(**vars(resp)), body=None)
    client = FakeClient([quota, [song(1)]])
    monkey_batches = classify.BATCH_SIZE
    classify.BATCH_SIZE = 1
    try:
        _, _, _, stopped = classify.run_batches(conn, ['t3', 't4'], lambda *a, **k: None, client)
    finally:
        classify.BATCH_SIZE = monkey_batches
    assert stopped and len(client.calls) == 1   # stopped at once, second batch never sent


def test_evaluate_holdout():
    covered = {'a': {'summer', 'cozy'}, 'b': {'cabins'}}
    matches = {'a': [('summer', 90, ''), ('cabins', 70, '')], 'b': []}
    ev = classify.evaluate(['a', 'b'], matches, covered)
    assert ev['recall'] == 33 and ev['songs_with_a_hit'] == 50 and ev['precision'] == 50
    assert [m['track_id'] for m in ev['misses']] == ['a', 'b']
