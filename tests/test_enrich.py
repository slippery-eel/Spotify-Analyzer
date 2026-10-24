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
