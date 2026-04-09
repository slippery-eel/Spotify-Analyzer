# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git & GitHub Workflow

This project uses GitHub for version control. Repo: **slippery-eel/Spotify-Analyzer** (private), branch `master`.

- After every meaningful change, commit and push to GitHub so there's always a saved, revertable version.
- Use clean, descriptive commit messages that summarize *what* changed and *why*.
- Never force-push or rewrite published history — always create new commits.
- `.claude/` is gitignored (local IDE settings only).

```bash
git add <files>
git commit -m "Short description of change"
git push
```

## Standard Workflow
1. First think through the problem, read the codebase for relevant files, and write a plan to todo.md.
2. The plan should have a list of todo items that you can check off as you complete them.
3. Before you begin working, check in with me and I will verify the plan.
4. Then, begin working on the todo items, marking them as complete as you go.
5. Every step of the way give a high-level explanation of what changes you made.
6. Make every task and code change as simple as possible. Avoid massive or complex changes — every change should impact as little code as possible.
7. Finally, add a review section to todo.md with a summary of changes made.

## Running the App

No build step. Open `index.html` directly in a browser, or serve it with any static file server:

```bash
python -m http.server 8080
# or
npx serve .
```

**Note:** Spotify now blocks `localhost` as a redirect URI. Use `http://127.0.0.1:8080/` instead — both when starting the server and when registering the redirect URI in the Spotify Developer Dashboard.

## Architecture

Single-page app with no framework, no bundler, no backend — three files total:

- **`index.html`** — Static layout with sections toggled via `style.display`
- **`script.js`** — All logic in one `SpotifyPlaylistHelper` class (instantiated at bottom of file)
- **`styles.css`** — Spotify-themed glassmorphism design

### Authentication Flow
Uses Spotify OAuth 2.0 authorization code flow. The user supplies their own `client_id`, `client_secret`, and `redirect_uri`. Credentials are AES-GCM encrypted via the Web Crypto API before being stored in `localStorage`. On page load, `checkUrlParams()` detects the OAuth `?code=` callback and calls `exchangeCodeForToken()`.

### OAuth Scopes
`user-library-read playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public`

Write scopes (`playlist-modify-*`) are needed for Save as Playlist. If a user authenticated before these were added, they'll get a 403 and see a re-auth prompt in the modal.

### Query System
Each query button in the UI has a `data-query` attribute. `handleQueryRun()` dispatches to one of three methods:
- `findLikedSongsNotInPlaylists()` — diffs liked songs against all playlist tracks
- `getAllLikedSongsAnalysis()` — fetches liked songs + renders Chart.js charts
- `browsePlaylistsMode()` — lists playlists, drills into individual playlist tracks

### Data Cache
`this.dataCache` holds enriched liked songs, playlist tracks/map, and user ID across queries to avoid redundant API calls. `ensureLikedSongsCache()` and `ensurePlaylistCache()` are called with `Promise.all()` so both fetch in parallel on first run.

### Filter & Table State
- `this.currentFilters` — `{ genre, artistText, dedupeEnabled, dateFrom, dateTo }`
- `this.selectedTrackIds` — Set of track IDs checked in the table
- `this.currentSort` — `{ column, direction }`
- Filter bar is rendered once in `displayResults()`; only `#track-table-only` is rebuilt on changes via `refreshTable()`

### Results Display
`currentResults` stores the last fetched data. `displayResults()` renders the filter bar + table. Charts (genre doughnut, top artists bar, liked-over-time bar) are rendered into `#genreChart`, `#artistChart`, `#timelineChart` via Chart.js (CDN).

### Track Table Columns
Track | Artists | Genre | Popularity | Playlists (analysis mode only) | Added | Open

All columns except Genre and Open are sortable. "Added" defaults to descending (newest first). Date range filters use `<input type="month">` and compare ISO strings lexicographically.

### Deduplication
`deduplicateTracks()` normalizes title (strips parentheticals) + first artist into a key. For the "Not in Playlists" query it also cross-deduplicates against playlist versions. Preferred duplicate is the one in the most playlists, then highest popularity.

### Save as Playlist
"Save as Playlist" button appears below the filter bar. Opens a modal with two tabs:
- **New Playlist** — creates a private playlist via `POST /v1/users/{id}/playlists`
- **Add to Existing** — fetches user playlists and lets user pick one from a dropdown

If rows are selected (`selectedTrackIds`), only those tracks are saved. Otherwise saves all filtered tracks. `spotifyApiCall(url, options)` supports POST by destructuring `options.headers` to avoid overwriting the `Authorization` header.
