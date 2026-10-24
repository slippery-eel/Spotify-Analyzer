"""The app's local server: Spotify login, background jobs, the JSON API, and the web UI.

Run: python server.py   then open http://127.0.0.1:8080
(Port 8080 matches the redirect URI registered with Spotify.)
"""
import json
import os
from typing import List, Literal, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import classify
import config
import enrich
import fitcheck
import jobs
import library
import profiles
import push
import review
import spotify_client as sp
import storage
import sync

_HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(_HERE, 'web')

app = FastAPI(title='Spotify Analyzer')
class NoCacheStatic(StaticFiles):
    """Make the browser re-check app files on every load (cheap 304s locally), so a reload always
    picks up new code instead of a stale cached module."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers['Cache-Control'] = 'no-cache'
        return response


app.mount('/web', NoCacheStatic(directory=WEB), name='web')

jobs.register('sync', 'Sync from Spotify', lambda progress: sync.run(progress)[0])
jobs.register('enrich', 'Fetch tags + lyrics', lambda progress: enrich.run(progress))
jobs.register('profiles', 'Draft vibe profiles', lambda progress: profiles.run(progress))
jobs.register('classify_pilot', 'Classifier test run', lambda progress: classify.run_pilot(progress))
jobs.register('classify_all', 'Classify liked songs', lambda progress: classify.run_all(progress))
jobs.register('push', 'Apply changes to Spotify', lambda progress: push.run(progress))
jobs.register('fitcheck', 'Check playlist fit', lambda progress, vibe=None: fitcheck.run(progress, vibe=vibe))
jobs.register('retry_lyrics', 'Retry missing lyrics',
              lambda progress: enrich.run(progress, which=('lyrics',), retry_misses=True))


@app.on_event('startup')
def _startup():
    storage.init_db()
    jobs.mark_interrupted()


def _db():
    return storage.get_connection()


# ---------- pages + auth ----------

@app.get('/')
def index():
    return FileResponse(os.path.join(WEB, 'index.html'), headers={'Cache-Control': 'no-cache'})


@app.get('/login')
def login():
    if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
        raise HTTPException(400, 'Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env first.')
    return RedirectResponse(sp.auth_url())


@app.get('/callback')
def callback(code: Optional[str] = None, error: Optional[str] = None):
    if not code:
        raise HTTPException(400, f'Login failed: {error}')
    sp.exchange_code(code)
    return RedirectResponse('/#/')


@app.post('/api/logout')
def logout():
    if os.path.exists(config.TOKEN_FILE):
        os.remove(config.TOKEN_FILE)
    return {'ok': True}


# ---------- overview ----------

def _next_step(o):
    if not o['account']['logged_in']:
        return 'account'
    if not o['sync']['last_sync_at']:
        return 'sync'
    c = o['enrich']
    if c['tags_pending'] or c['lyrics_pending']:
        return 'enrich'
    if not o['profiles'] or o['profiles_reviewed'] < o['sync']['vibe_matched']:
        return 'profiles'
    if not o['pilot']:
        return 'classify'
    if o['review']['pending']:
        return 'review'
    if o['unclassified']:
        return 'classify'
    if o['review']['approved'] or o['fit']['remove']:
        return 'push'
    if not o['fit']['checked']:
        return 'fitcheck'
    if o['fit']['flagged']:
        return 'fitcheck'
    return None


def _pilot_summary(conn):
    raw = storage.get_meta(conn, 'pilot_report')
    if not raw:
        return None
    r = json.loads(raw)
    r['holdout'] = {k: v for k, v in r['holdout'].items() if k != 'misses'}
    return r


@app.get('/api/classify/pilot')
def pilot_report():
    """Full pilot report, with names for the holdout songs it missed."""
    conn = _db()
    try:
        raw = storage.get_meta(conn, 'pilot_report')
        if not raw:
            return {'report': None}
        r = json.loads(raw)
        for m in r['holdout']['misses']:
            name, aj = conn.execute('SELECT name, artists_json FROM tracks WHERE track_id = ?', (m['track_id'],)).fetchone()
            m['name'], m['artist'] = name, json.loads(aj)[0]['name']
            m['vibe'] = (conn.execute('SELECT vibe_summary FROM classified WHERE track_id = ?',
                                      (m['track_id'],)).fetchone() or [None])[0]
        return {'report': r, 'names': {v['key']: v['name'] for v in config.VIBE_PLAYLISTS}}
    finally:
        conn.close()


@app.get('/api/overview')
def overview():
    conn = _db()
    try:
        q = lambda sql: conn.execute(sql).fetchone()[0]
        stats = review.get_stats(conn)
        o = {
            'account': {'logged_in': sp.load_token() is not None,
                        'display_name': storage.get_meta(conn, 'display_name')},
            'keys': {'spotify': bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET),
                     'lastfm': bool(config.LASTFM_API_KEY), 'openai': bool(config.OPENAI_API_KEY)},
            'sync': {'last_sync_at': storage.get_meta(conn, 'last_sync_at'), 'liked': stats['liked'],
                     'playlists': q('SELECT COUNT(*) FROM playlists'),
                     'vibe_matched': q('SELECT COUNT(*) FROM playlists WHERE vibe_key IS NOT NULL'),
                     'vibe_total': len(config.VIBE_PLAYLISTS)},
            'enrich': enrich.coverage(conn),
            'profiles': q('SELECT COUNT(*) FROM playlist_profiles'),
            'profiles_reviewed': q('SELECT COUNT(*) FROM playlist_profiles WHERE reviewed_at IS NOT NULL'),
            'profiles_edited': q('SELECT COUNT(*) FROM playlist_profiles WHERE is_edited = 1'),
            'classified': stats['classified'],
            'unclassified': q('SELECT COUNT(*) FROM liked WHERE track_id NOT IN (SELECT track_id FROM classified)'),
            'pilot': _pilot_summary(conn),
            'review': stats['counts'],
            'fit': review.fit_stats(conn, FIT_THRESHOLD)['totals'],
            'last_jobs': {t: jobs.last_success(t) for t in
                          ('sync', 'enrich', 'retry_lyrics', 'profiles', 'classify_pilot', 'classify_all', 'push',
                           'fitcheck')},
            'job': jobs.current(),
        }
    finally:
        conn.close()
    o['next_step'] = _next_step(o)
    return o


# ---------- jobs ----------

class JobStart(BaseModel):
    type: str
    vibe: Optional[str] = None   # fitcheck: check just this playlist


@app.get('/api/jobs')
def list_jobs():
    return {'current': jobs.current(), 'recent': jobs.recent(), 'types': jobs.job_types()}


@app.post('/api/jobs')
def start_job(body: JobStart):
    try:
        return jobs.start(body.type, **({'vibe': body.vibe} if body.vibe else {}))
    except KeyError:
        raise HTTPException(404, f'Unknown job {body.type}')
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))


# ---------- library + playlists ----------

@app.get('/api/library')
def get_library(scope: Literal['liked', 'not_in_playlists'] = 'liked', genre: Optional[str] = None,
                artist: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                dedupe: bool = False, ignore: Optional[str] = None):
    conn = _db()
    try:
        return library.get_library(conn, scope, genre or None, artist or None, date_from or None, date_to or None,
                                   dedupe, [i for i in (ignore or '').split(',') if i])
    finally:
        conn.close()


@app.get('/api/playlists')
def get_playlists():
    conn = _db()
    try:
        return {'playlists': library.list_playlists(conn)}
    finally:
        conn.close()


@app.get('/api/playlists/{playlist_id}/tracks')
def get_playlist_tracks(playlist_id: str):
    conn = _db()
    try:
        return library.playlist_tracks(conn, playlist_id)
    finally:
        conn.close()


class SavePlaylist(BaseModel):
    track_ids: List[str]
    name: Optional[str] = None
    playlist_id: Optional[str] = None


@app.post('/api/save-playlist')
def save_playlist(body: SavePlaylist):
    if jobs.current():
        raise HTTPException(409, 'Wait for the running job to finish first')
    conn = _db()
    try:
        return library.save_as_playlist(conn, body.track_ids, body.name, body.playlist_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except sp.SpotifyError as e:
        msg = str(e)
        if '403' in msg:
            msg = 'Spotify refused the change (403). Log out and back in on the Account page to grant write access.'
        raise HTTPException(502, msg)
    finally:
        conn.close()


# ---------- profiles ----------

@app.get('/api/profiles')
def get_profiles():
    conn = _db()
    try:
        return {'profiles': profiles.list_profiles(conn)}
    finally:
        conn.close()


class ProfileUpdate(BaseModel):
    profile_text: Optional[str] = None
    reviewed: Optional[bool] = None
    reset: bool = False


@app.post('/api/profiles/{vibe_key}')
def update_profile(vibe_key: str, body: ProfileUpdate):
    if vibe_key not in review.VIBES:
        raise HTTPException(404, 'Unknown playlist')
    conn = _db()
    try:
        profiles.update_profile(conn, vibe_key, body.profile_text, body.reviewed, body.reset)
        return next(p for p in profiles.list_profiles(conn) if p['key'] == vibe_key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


# ---------- push ----------

@app.get('/api/apply')
def get_apply():
    conn = _db()
    try:
        return {'adds': review.get_push_queue(conn), 'removes': review.get_remove_queue(conn),
                'recent_added': review.recent_added(conn), 'recent_removed': review.recent_removed(conn)}
    finally:
        conn.close()


class Restore(BaseModel):
    track_id: str
    vibe_key: str


@app.post('/api/apply/restore')
def restore(body: Restore):
    if jobs.current():
        raise HTTPException(409, 'Wait for the running job to finish first')
    try:
        push.restore(body.track_id, body.vibe_key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {'ok': True}


# ---------- playlist fit check ----------

FIT_THRESHOLD = 50


@app.get('/api/fit')
def get_fit(view: Literal['flagged', 'all', 'decided'] = 'flagged', vibe: Optional[str] = None,
            threshold: int = Query(FIT_THRESHOLD, ge=0, le=100), q: Optional[str] = None,
            offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    conn = _db()
    try:
        data = review.get_fit_queue(conn, view, vibe or None, threshold, q or None, offset, limit)
        data['stats'] = review.fit_stats(conn, threshold)
        return data
    finally:
        conn.close()


class FitDecision(BaseModel):
    track_id: str
    vibe_key: str
    status: Literal['keep', 'remove', 'unreviewed']
    move_to: Optional[str] = None


class FitDecisions(BaseModel):
    items: List[FitDecision]


@app.post('/api/fit/decide')
def fit_decide(body: FitDecisions):
    conn = _db()
    try:
        return review.apply_fit_decisions(conn, [d.model_dump() for d in body.items])
    finally:
        conn.close()


# ---------- review ----------

@app.get('/api/stats')
def stats():
    conn = _db()
    try:
        data = review.get_stats(conn)
    finally:
        conn.close()
    data['logged_in'] = sp.load_token() is not None
    return data


@app.get('/api/queue')
def queue(view: Literal['todo', 'done'] = 'todo',
          vibe: Optional[str] = None, q: Optional[str] = None,
          sort: Literal['score', 'added'] = 'score',
          offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    conn = _db()
    try:
        return review.get_queue(conn, view, vibe or None, q or None, sort, offset, limit)
    finally:
        conn.close()


class Decision(BaseModel):
    track_id: str
    vibe_key: str
    status: Literal['pending', 'approved', 'declined', 'removed']


class Decisions(BaseModel):
    items: List[Decision]


@app.post('/api/decide')
def decide(body: Decisions):
    conn = _db()
    try:
        return review.apply_decisions(conn, [d.model_dump() for d in body.items])
    finally:
        conn.close()


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('PORT', '8080')))
