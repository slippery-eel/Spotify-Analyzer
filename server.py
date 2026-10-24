"""Local review server: login, JSON API for the review queue, and the static review page.

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

import review
import spotify_client as sp
import storage

_HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(_HERE, 'web')

app = FastAPI(title='Spotify Vibe Sorter')
app.mount('/web', StaticFiles(directory=WEB), name='web')


@app.on_event('startup')
def _startup():
    storage.init_db()


@app.get('/')
def index():
    return FileResponse(os.path.join(WEB, 'review.html'))


@app.get('/login')
def login():
    return RedirectResponse(sp.auth_url())


@app.get('/callback')
def callback(code: Optional[str] = None, error: Optional[str] = None):
    if not code:
        raise HTTPException(400, f'Login failed: {error}')
    sp.exchange_code(code)
    return RedirectResponse('/')


@app.get('/api/stats')
def stats():
    conn = storage.get_connection()
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
    conn = storage.get_connection()
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
    conn = storage.get_connection()
    try:
        return review.apply_decisions(conn, [d.model_dump() for d in body.items])
    finally:
        conn.close()


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('PORT', '8080')))
