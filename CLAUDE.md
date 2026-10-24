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

```bash
pip install -r requirements.txt
python server.py          # http://127.0.0.1:8080
python -m pytest          # stub-based tests, no network
```

Keys live in `.env` (see `.env.example`): Spotify client ID/secret, Last.fm key, OpenAI key.
Spotify blocks `localhost`, so the redirect URI is `http://127.0.0.1:8080/callback`, and the server must run on port 8080.
`SPOTIFY_DB=<path>` + `PORT=<n>` run the app against a copy of the DB (used for UI testing with demo data).

## Architecture

One local app: a FastAPI server over a SQLite file, serving a plain-JS single-page UI (no framework, no bundler).
The original static analyzer (`index.html`/`script.js`/`styles.css`) was retired; its features were ported to Library/Playlists.

### Backend (repo root)
- **`config.py`**: `.env` loading, paths, and `VIBE_PLAYLISTS` (key, exact Spotify name, my description, optional hard `rule`).
- **`spotify_client.py`**: OAuth code flow, `token.json` save/refresh, `get`/`post`/`paginate` with 401 refresh and 429 Retry-After.
  Only post-Feb-2026 endpoints: `/me/tracks`, `/me/playlists` (GET/POST), `/playlists/{id}/items` (GET/POST), `/artists/{id}`.
- **`storage.py`**: schema + `init_db()` (also migrates the old vibe-only `playlists` table) and `get_meta`/`set_meta`.
  No WAL: the DB lives in OneDrive.
- **`sync.py`**: liked songs, every playlist (songs only for owned/collaborative ones; Spotify forbids others), artist genres.
  `snapshot_id` skip makes re-syncs fast. `run(progress)` for the app, `main()` for the CLI report.
- **`enrich.py`**: Last.fm tags (track → cleaned title → artist fallback) and LRCLIB lyrics; misses cached, server errors not.
- **`profiles.py`**: drafts a profile per vibe playlist from its songs: distinctive labels (from 2+ artists, ranked by
  share above the library baseline; place tags skipped), common labels, eras, instrumental share, artists, overlaps, and
  8 typical example songs (one per artist). `profile_text` is what the classifier reads; edits (`is_edited`) survive re-drafts.
- **`classify.py`**: gpt-4o-mini, batches of 20, strict JSON schema (playlist enum). Prompt = system rules + every vibe's
  size/breadth, description, hard rule, profile text, 8 typical + 8 range example songs (static, so OpenAI caches it);
  per song: genres, tags, lyric excerpt or instrumental flag, and `artist_history` (where the owner put the artist's other
  songs, excluding this song's versions). Scores >= 60 become pending suggestions; covered vibes (incl. other versions) are
  skipped; re-classifying replaces only undecided rows. Pilot = 40 unsorted + 20 holdout songs (never prompt examples);
  report (recall/precision/misses/cost estimate) lives in `meta.pilot_report`. Pilot recall went 30% -> 60% once base rates,
  range examples and artist history were added.
- **`fitcheck.py`**: rates songs already in each vibe playlist (0-100 + reason + better playlists) using classify.py's
  `playlist_block`/`song_entries`/`call_model` with its own instruction and schema; batches of 25 from one playlist.
  Results in `fit_checks` (status `unreviewed|keep|remove|removed`, `move_to`, `position` for put back); re-checks keep decisions.
- **`jobs.py`**: one background job at a time (thread), history in `job_runs`. Progress is in-memory only: a job holds an
  open write transaction, so writing progress to the DB from the same thread would deadlock on SQLite's lock.
- **`library.py`**: Library/Playlists queries, dedupe (`sync.normalize_for_dedup`, same key as the old app), analytics, Save as Playlist.
- **`review.py`**: review queue (`todo` = songs with a pending suggestion, `done` = all decided), decisions, push queue
  (approved rows grouped by playlist), recently added, and the fit-check queue/decisions/remove queue (a move also
  writes an approved suggestion with reason "Moved from X"). `added` rows are locked; manual approvals create rows undo can remove.
- **`push.py`**: applies decisions: removals first (`DELETE /playlists/{id}/items`, `{"items":[{"uri"}]}`), recording each
  song's position and writing a declined suggestion so it's never re-suggested; then additions (`POST .../items`).
  Batches of 100, each marked as it succeeds, so a failed run can be re-run. `restore()` puts a removed song back at its
  old position. Never touches Liked Songs.
- **`server.py`**: `/login`, `/callback`, and the JSON API (`/api/overview`, `/api/jobs`, `/api/library`, `/api/playlists`,
  `/api/save-playlist`, `/api/profiles[/vibe]`, `/api/classify/pilot`, `/api/fit` (+`/decide`), `/api/apply` (+`/restore`), `/api/stats`, `/api/queue`, `/api/decide`, `/api/logout`).

### Frontend (`web/`)
- **`index.html`** + **`app.js`**: shell, hash router (`#/`, `#/pipeline[/step]`, `#/profiles[/vibe]`, `#/review[/vibe]`, `#/check[/vibe]`, `#/push`, `#/library[/not_in_playlists]`,
  `#/playlists[/id]`, `#/account`), nav badges, and the jobs dock (polls `/api/jobs` while a job runs).
- **`views/*.js`**: one ES module per page exporting `mount(el, params)` and optional `unmount()` / `onJobDone()`.
  `steps.js` defines the pipeline steps shared by Home and Pipeline; `save.js` is the Save as Playlist modal.
  `player.js` wraps Spotify's iFrame API for review cards (seek bar, ±15s, middle, one song at a time). Quirks: seeks
  under ~1s and seeks after the end are ignored by the embed, seeking while paused needs a resume, and audio needs a real
  click first. Card updates must never move the player node (moving an iframe reloads it).
- **`app.css`**: tokens on `:root` with light/dark themes; Chart.js 4.4.1 from cdnjs for Library charts.

### Data notes
- Spotify removed popularity and audio features for this app, so neither is used.
- Only ~half of artists have Spotify genres; Last.fm tags fill the gap (mostly artist-level).
- Library's "Playlists that count…" ignore list is stored per browser in `localStorage` (`ignoredPlaylists`).
