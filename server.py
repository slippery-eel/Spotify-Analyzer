"""The app's local server: Spotify login, background jobs, the JSON API, and the web UI.

Run: python server.py   then open http://127.0.0.1:8080
(Port 8080 matches the redirect URI registered with Spotify.)
"""
import os
from typing import List, Literal, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import enrich
import jobs
import library
import review
import spotify_client as sp
import storage
import sync

_HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(_HERE, 'web')

app = FastAPI(title='Spotify Analyzer')
app.mount('/web', StaticFiles(directory=WEB), name='web')

jobs.register('sync', 'Sync from Spotify', lambda progress: sync.run(progress)[0])
jobs.register('enrich', 'Fetch tags + lyrics', lambda progress: enrich.run(progress))
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
    return FileResponse(os.path.join(WEB, 'index.html'))


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
    if not o['profiles']:
        return 'profiles'
    if not o['classified']:
        return 'classify'
    if o['review']['pending']:
        return 'review'
    if o['review']['approved']:
        return 'push'
    return None


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
            'classified': stats['classified'],
            'review': stats['counts'],
            'last_jobs': {t: jobs.last_success(t) for t in ('sync', 'enrich', 'retry_lyrics')},
            'job': jobs.current(),
        }
    finally:
        conn.close()
    o['next_step'] = _next_step(o)
    return o


# ---------- jobs ----------

class JobStart(BaseModel):
    type: str


@app.get('/api/jobs')
def list_jobs():
    return {'current': jobs.current(), 'recent': jobs.recent(), 'types': jobs.job_types()}


@app.post('/api/jobs')
def start_job(body: JobStart):
    try:
        return jobs.start(body.type)
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
def queue(view: Literal['pending', 'approved', 'declined', 'added'] = 'pending',
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
