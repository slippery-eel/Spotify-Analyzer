"""Spotify Web API access: OAuth (authorization code flow), token storage/refresh, and
GET/POST helpers that handle 401 (refresh once) and 429 (wait out Retry-After).

Only endpoints that survived Spotify's February 2026 dev-mode changes are used:
/me/tracks, /me/playlists, /playlists/{id}/items, /artists/{id}.

Run `python spotify_client.py login` once to authorize; the token is saved to token.json.
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

import config

API = 'https://api.spotify.com/v1'
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
MAX_RETRY_AFTER = 120  # seconds; a longer ban means stop and report, not hang


class SpotifyError(Exception):
    pass


# ---------- OAuth ----------

def auth_url():
    params = {
        'client_id': config.SPOTIFY_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': config.SPOTIFY_REDIRECT_URI,
        'scope': config.SPOTIFY_SCOPES,
    }
    return f'{AUTH_URL}?{urllib.parse.urlencode(params)}'


def _basic_auth_header():
    raw = f'{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}'.encode()
    return {'Authorization': 'Basic ' + base64.b64encode(raw).decode()}


def _save_token(data):
    data['expires_at'] = time.time() + data.get('expires_in', 3600) - 60
    old = load_token() or {}
    # Spotify may omit refresh_token on refresh; keep the previous one
    if 'refresh_token' not in data and 'refresh_token' in old:
        data['refresh_token'] = old['refresh_token']
    with open(config.TOKEN_FILE, 'w') as f:
        json.dump(data, f)
    return data


def load_token():
    if not os.path.exists(config.TOKEN_FILE):
        return None
    with open(config.TOKEN_FILE) as f:
        return json.load(f)


def exchange_code(code):
    r = requests.post(TOKEN_URL, headers=_basic_auth_header(), data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': config.SPOTIFY_REDIRECT_URI,
    }, timeout=30)
    if r.status_code != 200:
        raise SpotifyError(f'Token exchange failed: {r.status_code} {r.text}')
    return _save_token(r.json())


def refresh_token():
    tok = load_token()
    if not tok or 'refresh_token' not in tok:
        raise SpotifyError('Not logged in. Run: python spotify_client.py login')
    r = requests.post(TOKEN_URL, headers=_basic_auth_header(), data={
        'grant_type': 'refresh_token',
        'refresh_token': tok['refresh_token'],
    }, timeout=30)
    if r.status_code != 200:
        raise SpotifyError(f'Token refresh failed ({r.status_code}); log in again: '
                           f'python spotify_client.py login')
    return _save_token(r.json())


def _access_token():
    tok = load_token()
    if not tok:
        raise SpotifyError('Not logged in. Run: python spotify_client.py login')
    if time.time() >= tok.get('expires_at', 0):
        tok = refresh_token()
    return tok['access_token']


# ---------- requests ----------

def request(method, path_or_url, params=None, body=None, _session=requests):
    url = path_or_url if path_or_url.startswith('http') else API + path_or_url
    refreshed = False
    while True:
        headers = {'Authorization': f'Bearer {_access_token()}'}
        r = _session.request(method, url, params=params, json=body, headers=headers, timeout=30)
        if r.status_code == 401 and not refreshed:
            refresh_token()
            refreshed = True
            continue
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', '5'))
            if wait > MAX_RETRY_AFTER:
                raise SpotifyError(f'Rate limited by Spotify for {wait}s; try again later.')
            time.sleep(wait + 1)
            continue
        if r.status_code >= 400:
            raise SpotifyError(f'{method} {url} -> {r.status_code}: {r.text[:300]}')
        return r.json() if r.content else {}


def get(path_or_url, params=None):
    return request('GET', path_or_url, params=params)


def post(path, body):
    return request('POST', path, body=body)


def paginate(path, params=None):
    """Yield every item across all pages of a paging object, following `next`."""
    page = get(path, params)
    while True:
        yield from page.get('items', [])
        if not page.get('next'):
            return
        page = get(page['next'])


# ---------- CLI login ----------

def _login_cli():
    if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
        sys.exit('Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env first.')
    redirect = urllib.parse.urlparse(config.SPOTIFY_REDIRECT_URI)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != redirect.path:
                self.send_response(404)
                self.end_headers()
                return
            result['code'] = (qs.get('code') or [None])[0]
            result['error'] = (qs.get('error') or [None])[0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            msg = 'Logged in. You can close this tab.' if result['code'] else f"Login failed: {result['error']}"
            self.wfile.write(f'<h2>{msg}</h2>'.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer((redirect.hostname, redirect.port), Handler)
    url = auth_url()
    print(f'Opening browser to log in. If it does not open, visit:\n{url}')
    webbrowser.open(url)
    while 'code' not in result:
        server.handle_request()
    server.server_close()
    if not result['code']:
        sys.exit(f"Login failed: {result['error']}")
    exchange_code(result['code'])
    me = get('/me')
    print(f"Logged in as {me.get('display_name') or me.get('id')}. Token saved to token.json.")


if __name__ == '__main__':
    if sys.argv[1:] == ['login']:
        _login_cli()
    else:
        print('Usage: python spotify_client.py login')
