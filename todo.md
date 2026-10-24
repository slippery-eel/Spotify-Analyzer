# Todo: Liked Songs → Vibe Playlists review workflow

Full plan: Python backend + SQLite + local review page. Each liked song is matched to the
20 vibe playlists, I approve/decline, approved songs get added (add-only, songs stay liked).
Data: Spotify artist genres, Last.fm tags, LRCLIB lyrics, gpt-4o-mini classifier.

## Prerequisites (me)
- [ ] Free Last.fm API key
- [ ] Add `http://127.0.0.1:8080/callback` as a redirect URI in the Spotify Developer Dashboard
- [ ] Copy `.env.example` to `.env` and fill in the four keys
- [ ] Log in once in the browser

## Steps
- [x] 0. todo.md, .gitignore, .env.example, requirements.txt
- [ ] 1. spotify_client.py + storage.py + sync.py; run sync, report counts + sample songs ⏸
- [ ] 2. enrich.py (Last.fm tags + LRCLIB lyrics); report coverage
- [ ] 3. profiles.py; draft vibe profile per playlist, I review ⏸
- [ ] 4. classify.py pilot (~60 songs) + accuracy check + full-run cost estimate ⏸
- [ ] 5. server.py + review UI
- [ ] 6. push.py + push button (first real write triggered by me) ⏸
- [ ] 7. Update CLAUDE.md / README.md; review section below

## Review
(filled in at the end)
