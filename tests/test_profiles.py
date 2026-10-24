import json

import pytest

import config
import profiles
import storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 'p.db'))
    monkeypatch.setattr(config, 'VIBE_PLAYLISTS', [
        {'key': 'spooky', 'name': 'Spooky', 'description': 'halloween party'},
        {'key': 'cozy', 'name': 'cozy', 'description': 'calm'},
        {'key': 'missing', 'name': 'Not synced', 'description': 'x'}])
    storage.init_db()
    c = storage.get_connection()
    def track(tid, artist, aid, year, tags, pls, liked=True):
        c.execute('INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (tid, f'Song {tid}', json.dumps([{'id': aid, 'name': artist}]), 'A', f'{year}-01-01', 1, f'u:{tid}'))
        c.execute('INSERT INTO track_tags VALUES (?, ?, ?, ?)', (tid, json.dumps([[t, 100] for t in tags]), 'track', 'now'))
        if liked:
            c.execute('INSERT INTO liked VALUES (?, ?)', (tid, 'now'))
        for p in pls:
            c.execute('INSERT INTO playlist_items VALUES (?, ?, ?)', (p, tid, 'now'))
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('ps', 'spooky', 'Spooky')")
    c.execute("INSERT INTO playlists (playlist_id, vibe_key, name) VALUES ('pc', 'cozy', 'cozy')")
    # spooky: dark electronic from 3 artists; one artist alone brings "black metal" + a place tag
    track('s1', 'Lorn', 'a1', 2014, ['electronic', 'dark', 'denmark'], ['ps'])
    track('s2', 'Woodkid', 'a2', 2013, ['electronic', 'dark'], ['ps'])
    track('s3', 'Blood Cultures', 'a3', 2021, ['electronic', 'dark', 'indie'], ['ps', 'pc'])
    track('s4', 'Heilung', 'a4', 2018, ['black metal', 'dark'], ['ps'])
    track('s5', 'Heilung', 'a4', 2019, ['black metal'], ['ps'])
    track('s6', 'Heilung', 'a4', 2017, ['black metal'], ['ps'])
    # cozy + plain liked songs make the library baseline mostly indie/folk
    for i in range(8):
        track(f'c{i}', f'Folk{i}', f'f{i}', 2015, ['indie', 'folk'], ['pc'])
    for i in range(10):
        track(f'l{i}', f'Lib{i}', f'l{i}', 2016, ['indie'], [])
    c.execute("INSERT INTO lyrics VALUES ('s1', NULL, 1, 1, 'now')")
    c.execute("INSERT INTO lyrics VALUES ('s2', 'words', 0, 1, 'now')")
    c.commit()
    yield c
    c.close()


def test_stats_distinctive_needs_two_artists_and_skips_places(conn):
    s = profiles.compute(conn)['spooky']
    labels = [l for l, _ in s['distinctive']]
    assert labels[0] in ('dark', 'electronic') and 'dark' in labels and 'electronic' in labels
    assert 'black metal' not in labels          # only one artist
    assert all('denmark' not in l for l, _ in s['common'])
    assert s['size'] == 6 and s['instrumental_pct'] == 50
    assert s['decades'][0] == ('2010s', 83)
    assert ('cozy', 16) in s['overlaps']        # 1 of 6 spooky songs is also in cozy


def test_examples_one_per_artist(conn):
    ex = profiles.compute(conn)['spooky']['examples']
    artists = [e['artist'] for e in ex]
    assert len(artists) == len(set(artists)) == 4


def test_draft_edit_redraft_reset_and_review(conn):
    profiles.draft_all(conn)
    p = {x['key']: x for x in profiles.list_profiles(conn)}
    assert p['spooky']['profile_text'].startswith('Stands out for:') and not p['spooky']['is_edited']
    assert p['missing']['profile_text'] is None
    profiles.update_profile(conn, 'spooky', profile_text='Halloween party, not scary.')
    profiles.update_profile(conn, 'spooky', reviewed=True)
    profiles.draft_all(conn)  # re-draft keeps the edit and the review
    p = {x['key']: x for x in profiles.list_profiles(conn)}['spooky']
    assert p['profile_text'] == 'Halloween party, not scary.' and p['is_edited'] and p['reviewed_at']
    assert p['draft_text'].startswith('Stands out for:') and p['playlist_id'] == 'ps'
    profiles.update_profile(conn, 'spooky', reset=True)
    p = {x['key']: x for x in profiles.list_profiles(conn)}['spooky']
    assert p['profile_text'] == p['draft_text'] and not p['is_edited']


def test_saving_unchanged_draft_is_not_an_edit(conn):
    profiles.draft_all(conn)
    draft = {x['key']: x for x in profiles.list_profiles(conn)}['cozy']['draft_text']
    profiles.update_profile(conn, 'cozy', profile_text=draft + '\n')
    assert not {x['key']: x for x in profiles.list_profiles(conn)}['cozy']['is_edited']


def test_update_before_draft_errors(conn):
    with pytest.raises(ValueError):
        profiles.update_profile(conn, 'cozy', reviewed=True)
