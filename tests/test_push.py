import json

import pytest

import config
import push
import spotify_client as sp
import storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 'push.db'))
    storage.init_db()
    c = storage.get_connection()
    for i in range(5):
        c.execute('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (f't{i}', f'Song {i}', json.dumps([{'id': 'a', 'name': 'A'}]), 'Al', '2015', 1, f'u:t{i}'))
    c.execute("INSERT INTO tracks VALUES ('t9', 'Song 0 (Live)', ?, 'Al', '2015', 1, 'u:t9')", (json.dumps([{'id': 'a', 'name': 'A'}]),))
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('ps', 'summer', 'summer')")
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('pc', 'cozy', 'cozy')")
    c.execute("INSERT INTO playlist_items VALUES ('ps', 't9', 'now')")   # live version of t0 already in summer
    rows = [('t0', 'summer'), ('t1', 'summer'), ('t2', 'summer'), ('t3', 'cozy'), ('t4', 'cozy')]
    c.executemany("INSERT INTO suggestions (track_id, vibe_key, score, reason, status) VALUES (?, ?, 80, 'r', 'approved')", rows)
    c.execute("INSERT INTO suggestions (track_id, vibe_key, score, reason, status) VALUES ('t4', 'summer', 70, 'r', 'pending')")
    c.commit()
    monkeypatch.setattr(push.sync, 'sync_playlists', lambda *a, **k: None)
    yield c
    c.close()


def statuses(conn):
    return dict(((t, v), s) for t, v, s in conn.execute('SELECT track_id, vibe_key, status FROM suggestions'))


def test_adds_in_batches_skips_present_and_leaves_pending(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(push.sp, 'post', lambda path, body: calls.append((path, body['uris'])) or {})
    monkeypatch.setattr(push, 'BATCH', 1)
    summary = push.run()
    assert calls == [('/playlists/ps/items', ['u:t1']), ('/playlists/ps/items', ['u:t2']),
                     ('/playlists/pc/items', ['u:t3']), ('/playlists/pc/items', ['u:t4'])]
    st = statuses(conn)
    assert st[('t0', 'summer')] == 'added' and st[('t4', 'summer')] == 'pending'
    assert all(v == 'added' for k, v in st.items() if k != ('t4', 'summer'))
    assert summary == 'Added 4 songs to 2 playlists (1 were already there)'


def test_partial_failure_keeps_progress_and_rerun_continues(conn, monkeypatch):
    sent = []

    def flaky(path, body):
        if path.endswith('/pc/items') and not sent.count('fail'):
            sent.append('fail')
            raise sp.SpotifyError('POST x -> 500: boom')
        sent.append(path)
        return {}
    monkeypatch.setattr(push.sp, 'post', flaky)
    with pytest.raises(RuntimeError, match='run again to continue'):
        push.run()
    st = statuses(conn)
    assert st[('t1', 'summer')] == 'added' and st[('t3', 'cozy')] == 'approved'
    assert push.run() == 'Added 2 songs to 1 playlist'
    assert statuses(conn)[('t3', 'cozy')] == 'added'


def test_403_explains_relogin(conn, monkeypatch):
    def denied(path, body):
        raise sp.SpotifyError('POST x -> 403: Insufficient client scope')
    monkeypatch.setattr(push.sp, 'post', denied)
    with pytest.raises(RuntimeError, match='Log in again'):
        push.run()


def test_nothing_approved(conn, monkeypatch):
    conn.execute("UPDATE suggestions SET status = 'declined'")
    conn.commit()
    assert push.run() == 'Nothing approved to add'
