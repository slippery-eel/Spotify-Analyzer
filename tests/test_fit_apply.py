import json

import pytest

import config
import push
import review
import spotify_client as sp
import storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 'fa.db'))
    storage.init_db()
    c = storage.get_connection()
    for i in range(5):
        c.execute('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (f't{i}', f'Song {i}', json.dumps([{'id': 'a', 'name': 'A'}]), 'Al', '2015', 1, f'u:t{i}'))
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('ps', 'spooky', 'Spooky')")
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('pc', 'cozy', 'cozy')")
    for t in ('t0', 't1', 't2', 't3'):       # spooky order: t0 t1 t2 t3
        c.execute("INSERT INTO playlist_items VALUES ('ps', ?, 'now')", (t,))
    c.execute("INSERT INTO playlist_items VALUES ('pc', 't3', 'now')")
    for t, f, better in (('t0', 90, []), ('t1', 30, ['cozy']), ('t2', 45, ['spooky_x']), ('t3', 20, ['cozy'])):
        c.execute("INSERT INTO fit_checks (track_id, vibe_key, fit, reason, better_json) VALUES (?, 'spooky', ?, 'r', ?)",
                  (t, f, json.dumps(better)))
    c.commit()
    monkeypatch.setattr(push.sync, 'sync_playlists', lambda *a, **k: None)
    yield c
    c.close()


def ids(q):
    return [t['track_id'] for t in q['tracks']]


def test_flagged_queue_threshold_order_and_better(conn):
    q = review.get_fit_queue(conn, 'flagged', threshold=50)
    assert ids(q) == ['t3', 't1', 't2']
    by = {t['track_id']: t['check'] for t in q['tracks']}
    assert by['t1']['better'] == ['cozy']
    assert by['t3']['better'] == []          # already in cozy
    assert ids(review.get_fit_queue(conn, 'flagged', threshold=40)) == ['t3', 't1']
    assert ids(review.get_fit_queue(conn, 'all')) == ['t3', 't1', 't2', 't0']
    s = review.fit_stats(conn, 50)
    assert s['totals']['flagged'] == 3 and next(p for p in s['playlists'] if p['key'] == 'spooky')['checked'] == 4


def test_keep_remove_move_and_undo(conn):
    review.apply_fit_decisions(conn, [{'track_id': 't3', 'vibe_key': 'spooky', 'status': 'keep'}])
    res = review.apply_fit_decisions(conn, [{'track_id': 't1', 'vibe_key': 'spooky', 'status': 'remove', 'move_to': 'cozy'}])
    assert res['changed'][0]['previous'] == 'unreviewed'
    assert ids(review.get_fit_queue(conn, 'flagged')) == ['t2']
    assert conn.execute("SELECT status, reason FROM suggestions WHERE track_id = 't1' AND vibe_key = 'cozy'").fetchone() == \
        ('approved', 'Moved from Spooky 👻')
    assert [g['key'] for g in review.get_remove_queue(conn)] == ['spooky']
    assert [g['key'] for g in review.get_push_queue(conn)] == ['cozy']
    # undo the move: the queued add disappears too
    review.apply_fit_decisions(conn, [{'track_id': 't1', 'vibe_key': 'spooky', 'status': 'unreviewed'}])
    assert review.get_push_queue(conn) == [] and review.get_remove_queue(conn) == []


def test_apply_removes_then_adds_records_position_and_blocks_resuggestion(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(push.sp, 'delete', lambda path, body: calls.append(('DELETE', path, body)) or {})
    monkeypatch.setattr(push.sp, 'post', lambda path, body: calls.append(('POST', path, body)) or {})
    review.apply_fit_decisions(conn, [{'track_id': 't1', 'vibe_key': 'spooky', 'status': 'remove', 'move_to': 'cozy'},
                                      {'track_id': 't2', 'vibe_key': 'spooky', 'status': 'remove'}])
    summary = push.run()
    assert calls == [('DELETE', '/playlists/ps/items', {'items': [{'uri': 'u:t1'}, {'uri': 'u:t2'}]}),
                     ('POST', '/playlists/pc/items', {'uris': ['u:t1']})]
    assert summary == 'Removed 2 songs from 1 playlist, added 1 song to 1 playlist'
    assert conn.execute("SELECT status, position FROM fit_checks WHERE track_id = 't2'").fetchone() == ('removed', 2)
    assert conn.execute("SELECT status FROM suggestions WHERE track_id = 't2' AND vibe_key = 'spooky'").fetchone() == ('declined',)
    assert not conn.execute("SELECT 1 FROM playlist_items WHERE playlist_id = 'ps' AND track_id = 't2'").fetchone()
    assert review.recent_removed(conn)[0]['vibe_key'] == 'spooky'
    # decisions on removed rows are refused (Put back is the way back)
    assert review.apply_fit_decisions(conn, [{'track_id': 't2', 'vibe_key': 'spooky', 'status': 'keep'}])['skipped']


def test_put_back_restores_position(conn, monkeypatch):
    monkeypatch.setattr(push.sp, 'delete', lambda path, body: {})
    review.apply_fit_decisions(conn, [{'track_id': 't2', 'vibe_key': 'spooky', 'status': 'remove'}])
    push.run()
    posts = []
    monkeypatch.setattr(push.sp, 'post', lambda path, body: posts.append((path, body)) or {})
    push.restore('t2', 'spooky')
    assert posts == [('/playlists/ps/items', {'uris': ['u:t2'], 'position': 2})]
    assert conn.execute("SELECT status FROM fit_checks WHERE track_id = 't2'").fetchone() == ('keep',)
    assert not conn.execute("SELECT 1 FROM suggestions WHERE track_id = 't2' AND vibe_key = 'spooky'").fetchone()
    with pytest.raises(ValueError):
        push.restore('t2', 'spooky')


def test_removal_failure_keeps_queue(conn, monkeypatch):
    def boom(path, body):
        raise sp.SpotifyError('DELETE x -> 500: nope')
    monkeypatch.setattr(push.sp, 'delete', boom)
    review.apply_fit_decisions(conn, [{'track_id': 't1', 'vibe_key': 'spooky', 'status': 'remove'}])
    with pytest.raises(RuntimeError, match='run again to continue'):
        push.run()
    assert conn.execute("SELECT status FROM fit_checks WHERE track_id = 't1'").fetchone() == ('remove',)
