import json
from types import SimpleNamespace

import pytest

import config
import fitcheck
import storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 'f.db'))
    monkeypatch.setattr(config, 'VIBE_PLAYLISTS', [
        {'key': 'spooky', 'name': 'Spooky', 'description': 'halloween party'},
        {'key': 'cozy', 'name': 'cozy', 'description': 'calm'}])
    monkeypatch.setattr(fitcheck.time, 'sleep', lambda s: None)
    storage.init_db()
    c = storage.get_connection()
    for i in range(3):
        c.execute('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (f't{i}', f'Song {i}', json.dumps([{'id': 'a', 'name': 'A'}]), 'Al', '2015', 1, f'u:t{i}'))
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('ps', 'spooky', 'Spooky')")
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('pc', 'cozy', 'cozy')")
    for t in ('t0', 't1', 't2'):
        c.execute("INSERT INTO playlist_items VALUES ('ps', ?, 'now')", (t,))
    c.execute("INSERT INTO playlist_items VALUES ('pc', 't0', 'now')")
    c.commit()
    yield c
    c.close()


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'songs': item})))],
                               usage=usage)


def fit(i, score, better=()):
    return {'id': f's{i}', 'fit': score, 'reason': f'r{i}', 'better': list(better)}


def test_checks_one_playlist_and_saves_scores(conn):
    client = FakeClient([[fit(1, 90), fit(2, 30, ['cozy', 'spooky']), fit(3, 55)]])
    summary = fitcheck.run(vibe='spooky', client=client)
    rows = {t: (f, json.loads(b), s) for t, f, b, s in conn.execute(
        "SELECT track_id, fit, better_json, status FROM fit_checks WHERE vibe_key = 'spooky'")}
    assert rows == {'t0': (90, [], 'unreviewed'), 't1': (30, ['cozy'], 'unreviewed'), 't2': (55, [], 'unreviewed')}
    assert 'currently in the playlist "spooky"' in client.calls[0]['messages'][1]['content']
    assert summary.startswith('Checked 3 songs, 1 look like a poor fit')


def test_recheck_keeps_decisions_and_skips_checked(conn):
    fitcheck.run(vibe='spooky', client=FakeClient([[fit(1, 90), fit(2, 30), fit(3, 55)]]))
    conn.execute("UPDATE fit_checks SET status = 'keep' WHERE track_id = 't1'")
    conn.commit()
    assert fitcheck.run(vibe='spooky', client=FakeClient([])) == 'Everything is already checked'
    fitcheck.run(vibe='spooky', recheck=True, client=FakeClient([[fit(1, 80), fit(2, 20), fit(3, 60)]]))
    assert conn.execute("SELECT fit, status FROM fit_checks WHERE track_id = 't1'").fetchone() == (20, 'keep')


def test_all_playlists_and_failed_batch(conn):
    client = FakeClient([ValueError('x'), ValueError('x'), [fit(1, 70)]])
    summary = fitcheck.run(client=client)
    assert 'batches failed' in summary
    assert conn.execute('SELECT COUNT(*) FROM fit_checks').fetchone()[0] == 1   # only cozy's t0
