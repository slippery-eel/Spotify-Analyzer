// The sort-liked-songs pipeline steps, shared by Home and Pipeline.
import { pct, timeAgo } from '../lib.js';

export const STEPS = [
    {
        key: 'sync', title: 'Sync from Spotify', job: 'sync',
        what: 'Pulls your liked songs, every playlist, and artist genres. Read-only: nothing in Spotify changes.',
        status: (o) => o.sync.last_sync_at
            ? `${o.sync.liked} liked songs · ${o.sync.playlists} playlists · ${o.sync.vibe_matched}/${o.sync.vibe_total} vibe playlists found · synced ${timeAgo(o.sync.last_sync_at)}`
            : 'Not synced yet',
        done: (o) => !!o.sync.last_sync_at,
    },
    {
        key: 'enrich', title: 'Fetch tags + lyrics', job: 'enrich',
        what: 'Adds Last.fm mood/style tags and LRCLIB lyrics to every song, so vibes can be judged beyond genre.',
        status: (o) => {
            const c = o.enrich;
            if (!c.tracks) return 'Sync first';
            const tagged = c.tags_track + c.tags_artist;
            let s = `Tags for ${pct(tagged, c.tracks)}% · lyrics for ${pct(c.lyrics_found, c.tracks)}% (+${c.instrumental} instrumental)`;
            if (c.tags_pending || c.lyrics_pending) s += ` · ${Math.max(c.tags_pending, c.lyrics_pending)} songs still to fetch`;
            return s;
        },
        done: (o) => o.enrich.tracks > 0 && !o.enrich.tags_pending && !o.enrich.lyrics_pending,
        extra: { job: 'retry_lyrics', label: 'Retry missing lyrics', show: (o) => o.enrich.lyrics_missing > 0,
                 hint: (o) => `${o.enrich.lyrics_missing} songs had no lyrics found; LRCLIB is sometimes overloaded, so a retry can find more.` },
    },
    {
        key: 'profiles', title: 'Vibe profiles', soon: true,
        what: 'Drafts a profile for each vibe playlist from the songs already in it, for you to check and edit.',
        status: (o) => o.profiles ? `${o.profiles} profiles` : 'Coming next',
        done: (o) => o.profiles > 0,
    },
    {
        key: 'classify', title: 'Classify liked songs', soon: true,
        what: 'Suggests which vibe playlists each liked song fits, with a score and a reason. Starts with a small test run.',
        status: (o) => o.classified ? `${o.classified} songs classified` : 'Coming after profiles',
        done: (o) => o.classified > 0,
    },
    {
        key: 'review', title: 'Review suggestions', href: '#/review',
        what: 'Approve or decline each suggestion song by song.',
        status: (o) => `${o.review.pending} pending · ${o.review.approved} approved · ${o.review.declined} declined`,
        done: (o) => o.classified > 0 && !o.review.pending,
    },
    {
        key: 'push', title: 'Add approved songs to Spotify', soon: true,
        what: 'Adds approved songs to their playlists. Add-only: nothing is removed from Liked Songs.',
        status: (o) => `${o.review.approved} approved · ${o.review.added} added`,
        done: (o) => o.review.added > 0 && !o.review.approved,
    },
];
