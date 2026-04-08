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

### Query System
Each query button in the UI has a `data-query` attribute. `handleQueryRun()` dispatches to one of four methods:
- `findLikedSongsNotInPlaylists()` — diffs liked songs against all playlist tracks
- `getAllLikedSongsAnalysis()` — fetches liked songs + renders Chart.js charts
- `getArtistsAnalysis()` — aggregates artist data from liked songs
- `browsePlaylistsMode()` — lists playlists, drills into individual playlist tracks

### Results Display
`currentResults` stores the last fetched data. `displayResults()` re-renders it when the grouping toggle (Artist / Genre / None) changes — no re-fetch needed. Charts are rendered into `#genreChart` and `#artistChart` canvas elements using Chart.js (loaded from CDN).
