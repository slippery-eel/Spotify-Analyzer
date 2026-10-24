// The sort-liked-songs pipeline steps, shared by Home and Pipeline.
import { api, esc, pct, timeAgo } from '../lib.js';

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
        key: 'enrich', title: 'Fetch tags + lyrics', job: 'enrich', needsKey: 'lastfm',
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
        key: 'profiles', title: 'Vibe profiles', job: 'profiles', href: '#/profiles', showOpen: (o) => o.profiles > 0,
        runLabel: (o) => o.profiles ? 'Re-draft (keeps your edits)' : 'Draft profiles',
        what: 'Drafts a profile of each vibe playlist from the songs already in it. You check and edit each one; the classifier reads them.',
        status: (o) => o.profiles
            ? `${o.profiles_reviewed}/${o.profiles} reviewed · ${o.profiles_edited} edited`
            : 'Not drafted yet',
        done: (o) => o.profiles > 0 && o.profiles_reviewed >= o.sync.vibe_matched,
    },
    {
        key: 'classify', title: 'Classify liked songs', job: 'classify_pilot', needsKey: 'openai',
        what: 'Suggests which vibe playlists each liked song fits, with a score and a reason (gpt-4o-mini). '
            + 'Start with a test run on ~60 songs: 20 of them are already in your playlists, so you can see how often it agrees with you.',
        runLabel: (o) => o.pilot ? 'Re-run test' : 'Run test (~60 songs)',
        status: (o) => {
            if (!o.pilot) return o.profiles_reviewed < o.sync.vibe_matched
                ? `Not run yet. Tip: review your profiles first (${o.profiles_reviewed}/${o.sync.vibe_matched} done); they shape the results.`
                : 'Not run yet';
            return `${o.classified} of ${o.sync.liked} liked songs classified · ${o.unclassified} to go`;
        },
        done: (o) => o.sync.liked > 0 && o.unclassified === 0,
        extra: {
            job: 'classify_all', show: (o) => !!o.pilot && o.unclassified > 0, primary: (o) => !o.review.pending,
            label: (o) => `Classify all ${o.unclassified} remaining (≈ $${estimate(o)})`,
            hint: 'Classifies every liked song not classified yet. Uses your OpenAI credit.',
            confirm: (o) => ({
                title: 'Classify all remaining songs?',
                body: `This sends ${o.unclassified} songs to OpenAI in batches of 20. Estimated cost: about <strong>$${estimate(o)}</strong>,
                    based on the test run. Suggestions land in Review as pending; nothing changes in Spotify.`,
                ok: 'Start',
            }),
        },
        detail: renderPilot,
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

function estimate(o) {
    const p = o.pilot;
    if (!p || !p.classified) return '?';
    return ((p.cost / p.classified) * o.unclassified).toFixed(2);
}

// Pilot report under the Classify step: agreement with your own playlists, cost, and misses.
async function renderPilot(el, o) {
    if (!o.pilot) return;
    const { report: r, names } = await api('/api/classify/pilot');
    const h = r.holdout;
    const nm = (k) => esc(names[k] || k);
    el.innerHTML = `
        <div class="pilot">
            <div class="pilot-stats">
                <div><span class="stat-num">${h.songs_with_a_hit ?? '–'}%</span><span class="muted small">of test songs: it picked at least one playlist they're really in</span></div>
                <div><span class="stat-num">${h.recall ?? '–'}%</span><span class="muted small">of their real playlist placements found</span></div>
                <div><span class="stat-num">$${r.cost.toFixed(3)}</span><span class="muted small">test cost (${r.classified} songs)</span></div>
            </div>
            <p class="small muted">Test run ${timeAgo(r.at)}: ${r.suggested} of ${r.unsorted} unsorted songs got suggestions.
                ${h.precision != null ? `${h.precision}% of its picks for test songs matched where you put them; the rest may still be good ideas you haven't made yet.` : ''}
                ${r.failed_batches ? `<span class="warn">${r.failed_batches} batch(es) failed.</span>` : ''}</p>
            ${h.misses.length ? `<details><summary class="small">Test songs where it missed a playlist (${h.misses.length})</summary>
                <table class="tracks compact"><thead><tr><th>Song</th><th>You put it in</th><th>It picked</th></tr></thead><tbody>
                ${h.misses.map(m => `<tr><td><strong>${esc(m.name)}</strong> <span class="muted">${esc(m.artist)}</span>
                    ${m.vibe ? `<div class="muted small">“${esc(m.vibe)}”</div>` : ''}</td>
                    <td>${m.actual.map(nm).join(', ')}</td><td>${m.picked.map(nm).join(', ') || '<span class="muted">nothing</span>'}</td></tr>`).join('')}
                </tbody></table></details>` : ''}
            <p class="step-actions"><a class="btn ${o.review.pending ? 'btn-primary' : ''}" href="#/review">Review suggestions for ${o.review.pending} songs</a></p>
        </div>`;
}
