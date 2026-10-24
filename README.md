# Spotify Analyzer

A local app for exploring your Spotify library and sorting your liked songs into your own vibe playlists.
It runs on your computer: a small Python server keeps your data in a local SQLite file and serves the app
at `http://127.0.0.1:8080`.

---

## Features

**Sort liked songs** (the Pipeline page walks you through it)
1. **Sync**: pulls your liked songs, all your playlists, and artist genres (read-only).
2. **Fetch tags + lyrics**: Last.fm mood/style tags and LRCLIB lyrics for every song.
3. **Vibe profiles**: a draft profile of each vibe playlist (distinctive tags, eras, artists, overlaps, typical songs)
   that you edit and mark reviewed on the Profiles page.
4. **Classify**: gpt-4o-mini suggests which vibe playlists each liked song fits, with a score and a reason.
   A test run on ~60 songs (20 already sorted by you) shows how often it agrees with you and what the full run costs.
5. **Review**: go song by song (To review / Reviewed tabs). Approve or decline each suggested playlist, or use
   "Approve the rest / Decline the rest" on a card. Each card has a Spotify player with a seek bar, ±15s and
   jump-to-middle (Space, ←/→, m); full songs if you're logged in to Spotify in that browser, else 30s previews.
6. **Apply to Spotify**: every decision in one place, grouped by playlist: songs to add (approved in Review) and
   songs to remove (from Playlist check). Undo any of them, then one button applies them all. Liked Songs is never
   touched; removed songs can be put back at their old position.
7. **Playlist check**: scores every song already in your vibe playlists (0-100) on how well it fits, with a reason and
   better-fitting playlists. Review the ones under a threshold you choose: Keep, Remove, or Move to another playlist.
   Vibe playlist pages also show each song's fit score.

**Explore**
- **Library**: every liked song with genre/tag, artist and date filters, duplicate hiding, sortable columns,
  charts (top genres, top artists, liked over time), and a coverage bar for songs that are in no playlist.
  Select songs and **save them as a new playlist** or add them to an existing one.
- **Playlists**: browse all your playlists and their songs, and copy a playlist's song list.

---

## Setup

### 1. Create a Spotify Developer App
1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in.
2. Click **Create app**, give it any name and description, and select **Web API**.
3. Under **Redirect URIs**, add `http://127.0.0.1:8080/callback` (not `localhost`; Spotify blocks it).
4. Save, then copy the **Client ID** and **Client Secret**.

### 2. Add your keys
Copy `.env.example` to `.env` and fill it in:

| Key | Needed for |
|---|---|
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | Login and sync |
| `LASTFM_API_KEY` | Mood/style tags ([get a free key](https://www.last.fm/api/account/create)) |
| `OPENAI_API_KEY` | Classifying songs into vibes |

`.env` is gitignored, so your keys never leave your computer.

### 3. Run it
```bash
pip install -r requirements.txt
python server.py
```
Open **http://127.0.0.1:8080**, go to **Account**, and log in with Spotify. Then follow the **Pipeline** page.

Your vibe playlists and what each one is for are defined in `config.py` (`VIBE_PLAYLISTS`).

---

## Command line
Every pipeline step can also be run from a terminal:
```bash
python spotify_client.py login   # log in without the app
python sync.py                   # sync + a text report
python enrich.py                 # tags + lyrics
python enrich.py retry-lyrics    # re-try songs that had no lyrics
python profiles.py               # draft vibe profiles
python classify.py pilot | all   # classifier test run / full run (uses OpenAI credit)
python fitcheck.py [vibe_key]    # score how well songs fit the playlists they're in (uses OpenAI credit)
python push.py                   # apply queued removals and additions to Spotify
python -m pytest                 # tests (no network calls)
```

---

## Privacy
- Everything stays on your computer: `spotify_data.db` (your synced library) and `token.json` (your Spotify login) are both gitignored.
- The app only talks to Spotify, Last.fm, LRCLIB and OpenAI (song titles, artists, tags and short lyric excerpts are sent for classification).
- **Sign out** on the Account page deletes the saved login token.

## Notes
- Spotify only lets apps read songs from playlists you **own or collaborate on**, so followed playlists are listed without their songs.
- Spotify removed popularity and audio features (energy, valence, …) from its API for apps like this one, so they aren't shown.
