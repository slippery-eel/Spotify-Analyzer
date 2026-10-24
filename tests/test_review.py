import json

import pytest

import config
import review
import storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 't.db'))
    storage.init_db()
    c = storage.get_connection()
    for tid in ('t1', 't2'):
        c.execute('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (tid, f'Song {tid}', json.dumps([{'id': 'a1', 'name': 'Artist'}]), 'Album', '2015-01-01', 1000,
                   f'spotify:track:{tid}'))
        c.execute('INSERT INTO liked VALUES (?, ?)', (tid, '2026-01-01'))
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name, snapshot_id, synced_at) VALUES ('p1', 'cozy', 'mega cozy playlist', 's', 'now')")
    c.execute("INSERT INTO playlist_items VALUES ('p1', 't2', 'now')")
    c.execute("INSERT INTO suggestions (track_id, vibe_key, score, reason, status) VALUES "
              "('t1', 'summer', 90, 'sunny', 'pending'), ('t1', 'cozy', 70, 'calm', 'pending'), "
              "('t2', 'gym', 65, 'hard', 'added')")
    c.commit()
    yield c
    c.close()


def test_queue_todo_returns_undecided_songs_sorted(conn):
    data = review.get_queue(conn, 'todo')
    assert data['total'] == 1
    t = data['tracks'][0]
    assert t['track_id'] == 't1' and [s['vibe_key'] for s in t['suggestions']] == ['summer', 'cozy']
    assert review.get_queue(conn, 'todo', vibe='gym')['total'] == 0
    assert review.get_queue(conn, 'todo', q='nomatch')['total'] == 0


def test_song_moves_to_done_only_when_every_suggestion_is_decided(conn):
    review.apply_decisions(conn, [{'track_id': 't1', 'vibe_key': 'summer', 'status': 'approved'}])
    assert [t['track_id'] for t in review.get_queue(conn, 'todo')['tracks']] == ['t1']   # cozy still undecided
    assert [t['track_id'] for t in review.get_queue(conn, 'done')['tracks']] == ['t2']
    review.apply_decisions(conn, [{'track_id': 't1', 'vibe_key': 'cozy', 'status': 'declined'}])
    assert review.get_queue(conn, 'todo')['total'] == 0
    assert sorted(t['track_id'] for t in review.get_queue(conn, 'done')['tracks']) == ['t1', 't2']
    assert review.get_queue(conn, 'done', vibe='summer')['total'] == 1


def test_push_queue_groups_approved_by_playlist(conn):
    review.apply_decisions(conn, [{'track_id': 't1', 'vibe_key': 'summer', 'status': 'approved'},
                                  {'track_id': 't1', 'vibe_key': 'cozy', 'status': 'approved'}])
    q = review.get_push_queue(conn)
    assert [(g['key'], g['playlist_id'], [s['track_id'] for s in g['songs']]) for g in q] == [
        ('summer', None, ['t1']), ('cozy', 'p1', ['t1'])]
    assert review.recent_added(conn)[0]['vibe_key'] == 'gym'


def test_decide_approve_decline_and_undo(conn):
    res = review.apply_decisions(conn, [{'track_id': 't1', 'vibe_key': 'summer', 'status': 'approved'}])
    assert res['changed'][0]['previous'] == 'pending'
    review.apply_decisions(conn, [{'track_id': 't1', 'vibe_key': 'summer', 'status': 'pending'}])
    assert review.get_push_queue(conn) == []


def test_added_rows_are_locked(conn):
    res = review.apply_decisions(conn, [{'track_id': 't2', 'vibe_key': 'gym', 'status': 'declined'}])
    assert res['skipped'][0]['reason'] == 'already added'


def test_manual_approve_creates_row_and_removed_undoes_it(conn):
    res = review.apply_decisions(conn, [{'track_id': 't1', 'vibe_key': 'moody', 'status': 'approved'}])
    assert res['changed'][0]['previous'] is None
    res = review.apply_decisions(conn, [{'track_id': 't1', 'vibe_key': 'moody', 'status': 'removed'}])
    assert res['changed'] and not conn.execute(
        "SELECT 1 FROM suggestions WHERE track_id='t1' AND vibe_key='moody'").fetchone()


def test_manual_approve_skips_playlist_song_is_already_in(conn):
    res = review.apply_decisions(conn, [{'track_id': 't2', 'vibe_key': 'cozy', 'status': 'approved'}])
    assert res['skipped'][0]['reason'] == 'already in that playlist'


def test_stats_counts(conn):
    s = review.get_stats(conn)
    assert s['counts']['todo'] == 1 and s['counts']['done'] == 1
    assert s['counts']['pending'] == 2 and s['counts']['added'] == 1
    cozy = next(p for p in s['playlists'] if p['key'] == 'cozy')
    assert cozy['size'] == 1 and cozy['counts']['pending'] == 1
