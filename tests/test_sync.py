import spotify_client as sp
import sync


def test_match_playlists_tolerates_case_whitespace_and_curly_quotes():
    user = [{'id': 'a', 'name': 'Summer Time  Vibes'},
            {'id': 'b', 'name': 'damn i’m good'},
            {'id': 'c', 'name': '🔥m🔥o👿o🔥d🔥'}]
    vibes = [{'key': 'summer', 'name': 'summer time vibes'},
             {'key': 'damn', 'name': "damn i'm good"},
             {'key': 'fire', 'name': '🔥m🔥o👿o🔥d🔥'},
             {'key': 'missing', 'name': 'log cabins'}]
    matched, unmatched = sync.match_playlists(user, vibes)
    assert {k: p['id'] for k, p in matched.items()} == {'summer': 'a', 'damn': 'b', 'fire': 'c'}
    assert [v['key'] for v in unmatched] == ['missing']


def test_normalize_for_dedup_matches_script_js():
    assert sync.normalize_for_dedup('Song (Remastered 2011) [Live]', ' Artist ') == 'song|artist'


def test_track_from_item_handles_new_and_old_shapes_and_skips_non_tracks():
    t = {'id': 'x', 'type': 'track'}
    assert sync._track_from_item({'item': t}) is t
    assert sync._track_from_item({'track': t}) is t
    assert sync._track_from_item({'item': {'id': 'e', 'type': 'episode'}}) is None
    assert sync._track_from_item({'item': {'id': None, 'type': 'track'}}) is None
    assert sync._track_from_item({'item': None}) is None


class FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.content = b'x'
        self.text = ''

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append(url)
        return self.responses.pop(0)


def test_request_waits_out_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(sp, '_access_token', lambda: 'tok')
    slept = []
    monkeypatch.setattr(sp.time, 'sleep', slept.append)
    s = FakeSession([FakeResp(429, headers={'Retry-After': '2'}), FakeResp(200, {'ok': 1})])
    assert sp.request('GET', '/me', _session=s) == {'ok': 1}
    assert slept == [3]


def test_request_gives_up_on_long_ban(monkeypatch):
    monkeypatch.setattr(sp, '_access_token', lambda: 'tok')
    s = FakeSession([FakeResp(429, headers={'Retry-After': '99999'})])
    try:
        sp.request('GET', '/me', _session=s)
        assert False
    except sp.SpotifyError as e:
        assert 'Rate limited' in str(e)


def test_paginate_follows_next(monkeypatch):
    pages = {'/x': {'items': [1, 2], 'next': 'http://n'}, 'http://n': {'items': [3], 'next': None}}
    monkeypatch.setattr(sp, 'get', lambda url, params=None: pages[url])
    assert list(sp.paginate('/x')) == [1, 2, 3]
