# Todo: Liked Songs → Vibe Playlists, in one app

Python backend + SQLite + one local web app (`python server.py` → http://127.0.0.1:8080).
Each liked song is matched to the 20 vibe playlists; I approve/decline; approved songs get added
(add-only, songs stay liked). The original analyzer's tools (Library, Playlists, Save as Playlist)
live in the same app.

## Prerequisites (me)
- [x] Free Last.fm API key
- [x] Add `http://127.0.0.1:8080/callback` as a redirect URI in the Spotify Developer Dashboard
- [x] Spotify + Last.fm keys in `.env`
- [ ] OpenAI key in `.env` (needed for classification)
- [x] Log in once

## Pipeline steps
- [x] 0. todo.md, .gitignore, .env.example, requirements.txt
- [x] 1. spotify_client.py + storage.py + sync.py; sync report
- [x] 2. enrich.py (Last.fm tags + LRCLIB lyrics); coverage report
- [x] 3. profiles.py + Profiles page: drafts built, I review/edit each one in the app ⏸
- [ ] 4. classify.py pilot (~60 songs) + accuracy check + full-run cost estimate ⏸
- [x] 5. Review UI
- [ ] 6. push.py + push step (first real write triggered by me) ⏸
- [ ] 7. Docs: review section below

## Merge into one app
- [x] Storage migration (all playlists, meta, job_runs), all-playlists sync, progress callbacks, jobs.py
- [x] App shell: nav, Home, Account, jobs dock; Review moved in
- [x] Library: filters, dedupe, coverage + ignore list, charts, Save as Playlist
- [x] Playlists: all playlists, songs, copy list
- [x] Pipeline stepper wired to Sync / Enrich / Retry lyrics jobs
- [x] Retire old index.html / script.js / styles.css; update README + CLAUDE.md
- [ ] First real Save as Playlist, triggered by me

## Review
(filled in at the end)
