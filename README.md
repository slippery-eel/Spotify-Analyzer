# Spotify Playlist Helper

A browser-based tool for analyzing your Spotify library. Find liked songs that aren't in any playlist, explore your music taste with charts, browse your playlists, and save filtered results as new playlists — all without any server or account required.

**No data is ever collected.** Everything runs in your browser using your own Spotify credentials.

---

## Features

- **Liked Songs Not in Playlists** — find every liked song you haven't organized into a playlist
- **All Liked Songs Analysis** — genre breakdown, top artists, and a liked-over-time chart
- **Playlist Browser** — browse and filter tracks within any of your playlists
- Filter by genre, artist, or date range; sort any column; deduplicate similar tracks
- Select tracks and save them as a new Spotify playlist or add to an existing one

---

## Setup

### 1. Create a Spotify Developer App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in
2. Click **Create app**
3. Fill in any name and description
4. Under **Redirect URIs**, add: `http://127.0.0.1:8080`
5. Under **APIs used**, select **Web API**
6. Save — then open the app and copy your **Client ID** and **Client Secret**

### 2. Run the app locally

Clone or download this repo, then serve it with any static file server:

```bash
# Python (built-in)
python -m http.server 8080

# or Node
npx serve . -p 8080
```

Open **`http://127.0.0.1:8080`** in your browser (not `localhost` — Spotify blocks it).

### 3. Enter your credentials

Paste your Client ID, Client Secret, and `http://127.0.0.1:8080` as the Redirect URI, then click **Save & Authenticate**. You'll be redirected to Spotify to authorize the app.

---

## Privacy & Security

- Your credentials are encrypted with AES-GCM (Web Crypto API) before being stored in your browser's `localStorage`
- Nothing is sent to any server — all API calls go directly to Spotify's API from your browser
- No analytics, no tracking, no data collection of any kind
- To remove your stored credentials, click **Sign Out** in the app, or clear your browser's localStorage manually

---

## Notes

- The access token lasts for 1 hour. If queries start failing, refresh the page and re-authenticate
- Large libraries (1000+ liked songs) may take a moment to load — all pagination is handled automatically
- Write access (`playlist-modify-*`) is required for the "Save as Playlist" feature. If you authenticated before this was needed, you'll see a re-auth prompt
