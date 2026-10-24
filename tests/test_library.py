import json

import pytest

import config
import library
import storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 'l.db'))
    storage.init_db()
    c = storage.get_connection()
    def track(tid, name, artist, aid):
        c.execute('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (tid, name, json.dumps([{'id': aid, 'name': artist}]), 'Alb', '2015-01-01', 1, f'spotify:track:{tid}'))
    track('t1', 'Riptide', 'Vance Joy', 'a1')
    track('t2', 'Riptide (Live)', 'Vance Joy', 'a1')   # duplicate of t1
    track('t3', 'Cherry', 'Ratatat', 'a2')
    track('t4', 'Kyoto', 'HAELOS', 'a3')
    for tid, added in (('t1', '2026-03-01T00:00:00Z'), ('t2', '2026-04-01T00:00:00Z'),
                       ('t3', '2025-01-05T00:00:00Z'), ('t4', '2026-05-01T00:00:00Z')):
        c.execute('INSERT INTO liked VALUES (?, ?)', (tid, added))
    c.execute("INSERT INTO artists VALUES ('a1', 'Vance Joy', '[\"folk pop\"]', 'now')")
    c.execute("INSERT INTO artists VALUES ('a2', 'Ratatat', '[]', 'now')")
    c.execute("INSERT INTO track_tags VALUES ('t3', '[[\"electronic\", 100]]', 'artist', 'now')")
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('p1', 'summer', 'summer')")
    c.execute("INSERT INTO playlists (playlist_id, name) VALUES ('px', 'Old export')")
    c.execute("INSERT INTO playlists (playlist_id, name, is_owned) VALUES ('pf', 'Followed', 0)")
    c.execute("INSERT INTO playlist_items VALUES ('p1', 't1', 'now')")
    c.execute("INSERT INTO playlist_items VALUES ('px', 't4', 'now')")
    c.commit()
    yield c
    c.close()


def ids(data):
    return sorted(r['track_id'] for r in data['tracks'])


def test_all_liked_with_genres_and_tags(conn):
    data = library.get_library(conn)
    assert ids(data) == ['t1', 't2', 't3', 't4'] and data['in_playlists'] == 2
    t3 = next(r for r in data['tracks'] if r['track_id'] == 't3')
    assert t3['genres'] == [] and t3['tags'] == ['electronic']


def test_not_in_playlists_respects_ignore_and_cross_dedupes(conn):
    assert ids(library.get_library(conn, scope='not_in_playlists')) == ['t2', 't3']
    assert ids(library.get_library(conn, scope='not_in_playlists', ignore=['px'])) == ['t2', 't3', 't4']
    # t2 is a live version of t1, which is already in a playlist
    assert ids(library.get_library(conn, scope='not_in_playlists', dedupe=True)) == ['t3']


def test_dedupe_prefers_version_in_playlists(conn):
    assert ids(library.get_library(conn, dedupe=True)) == ['t1', 't3', 't4']


def test_filters(conn):
    assert ids(library.get_library(conn, genre='folk pop')) == ['t1', 't2']
    assert ids(library.get_library(conn, genre='electronic')) == ['t3']
    assert ids(library.get_library(conn, artist='rata')) == ['t3']
    assert ids(library.get_library(conn, date_from='2026-04', date_to='2026-04')) == ['t2']


def test_analytics_counts(conn):
    a = library.get_library(conn)['analytics']
    assert ('Vance Joy', 2) in a['artists'] and a['timeline_unit'] == 'month'
    assert dict(a['genres'])['folk pop'] == 2


def test_list_playlists_vibes_first(conn):
    pls = library.list_playlists(conn)
    assert pls[0]['vibe_key'] == 'summer' and pls[0]['description']
    assert next(p for p in pls if p['playlist_id'] == 'pf')['is_owned'] is False


def test_save_as_new_playlist_batches_and_resyncs(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(library.sp, 'post', lambda path, body: calls.append((path, body)) or {'id': 'new', 'name': body.get('name')})
    resynced = []
    monkeypatch.setattr(library.sync, 'sync_playlists', lambda c, progress, only_ids: resynced.append(only_ids))
    res = library.save_as_playlist(conn, ['t1', 't3', 't3'], name=' Mix ')
    assert calls[0] == ('/me/playlists', {'name': 'Mix', 'public': False, 'description': 'Saved from Spotify Analyzer'})
    assert calls[1] == ('/playlists/new/items', {'uris': ['spotify:track:t1', 'spotify:track:t3']})
    assert res['added'] == 2 and resynced == [{'new'}]


def test_save_to_existing_skips_present_and_refuses_followed(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(library.sp, 'post', lambda path, body: calls.append((path, body)) or {})
    monkeypatch.setattr(library.sync, 'sync_playlists', lambda c, progress, only_ids: None)
    res = library.save_as_playlist(conn, ['t1', 't3'], playlist_id='p1')
    assert calls == [('/playlists/p1/items', {'uris': ['spotify:track:t3']})] and res['skipped'] == 1
    with pytest.raises(ValueError):
        library.save_as_playlist(conn, ['t1'], playlist_id='pf')
