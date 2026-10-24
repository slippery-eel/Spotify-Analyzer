import enrich


def test_clean_title_strips_feat_and_remaster_suffix():
    assert enrich.clean_title('Stylo (feat. Mos Def) - Remastered 2011') == 'Stylo'
    assert enrich.clean_title('Plain') == 'Plain'


def test_filter_tags_drops_years_junk_low_counts_and_dupes():
    raw = [{'name': 'psychedelic', 'count': 100}, {'name': '2015', 'count': 50},
           {'name': 'seen live', 'count': 40}, {'name': 'Psychedelic', 'count': 30},
           {'name': '80s', 'count': 20}, {'name': 'synthpop', 'count': 19},
           {'name': 'australian', 'count': 1}]
    assert enrich.filter_tags(raw) == [('psychedelic', 100), ('synthpop', 19)]


def test_fetch_tags_falls_back_to_artist_and_caches(monkeypatch):
    calls = []

    def fake(method, **p):
        calls.append(method)
        if method == 'artist.gettoptags':
            return {'toptags': {'tag': [{'name': 'folk', 'count': 100}]}}
        return {'error': 6}
    monkeypatch.setattr(enrich, '_lastfm', fake)
    cache = {}
    assert enrich.fetch_tags('Song (Live)', 'A', cache) == ([('folk', 100)], 'artist')
    assert enrich.fetch_tags('Other', 'A', cache) == ([('folk', 100)], 'artist')
    assert calls.count('artist.gettoptags') == 1


def test_fetch_lyrics_uses_later_search_results(monkeypatch):
    def fake(kind, params):
        if kind == 'get':
            return 404, None
        return 200, [{'plainLyrics': None, 'instrumental': False}, {'plainLyrics': 'la la', 'instrumental': False}]
    monkeypatch.setattr(enrich, '_lrclib', fake)
    assert enrich.fetch_lyrics('Song', 'A', 'Al', 1000) == ('la la', False, True)


def test_fetch_lyrics_returns_none_when_server_keeps_failing(monkeypatch):
    monkeypatch.setattr(enrich, '_lrclib', lambda kind, params: (None, None))
    assert enrich.fetch_lyrics('Song', 'A', 'Al', 1000) is None


def test_fetch_lyrics_real_miss_is_cached_as_not_found(monkeypatch):
    monkeypatch.setattr(enrich, '_lrclib', lambda kind, params: (404, None) if kind == 'get' else (200, []))
    assert enrich.fetch_lyrics('Song', 'A', 'Al', 1000) == (None, False, False)
