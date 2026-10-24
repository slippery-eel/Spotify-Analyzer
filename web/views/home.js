// Home: where things stand and what to do next.
import { api, esc } from '../lib.js';
import { ignoredPlaylists } from './library.js';
import { STEPS } from './steps.js';

let root;

export async function mount(el) {
    root = el;
    await render();
}

export function onJobDone() { render(); }

async function render() {
    const o = await api('/api/overview');
    const next = STEPS.find(s => s.key === o.next_step);
    root.innerHTML = `
        <header class="page-head">
            <h1>${o.account.display_name ? `Hi, ${esc(o.account.display_name)}` : 'Welcome'}</h1>
            <p class="muted">Sort your liked songs into your vibe playlists, and explore your library.</p>
        </header>

        ${!o.account.logged_in ? `
        <section class="callout">
            <div><strong>Connect Spotify to get started.</strong>
            <p class="muted">${o.keys.spotify ? 'Your keys are set; just log in.' : 'Add your Spotify keys to .env first (see Account).'}</p></div>
            <a class="btn btn-primary" href="${o.keys.spotify ? '/login' : '#/account'}">${o.keys.spotify ? 'Log in with Spotify' : 'Open Account'}</a>
        </section>` : next ? `
        <section class="callout">
            <div><span class="eyebrow">Next step</span><strong>${esc(next.title)}</strong>
            <p class="muted">${esc(next.what)}</p></div>
            <a class="btn btn-primary" href="${next.href || `#/pipeline/${next.key}`}">${next.soon ? 'See pipeline' : 'Go'}</a>
        </section>` : `
        <section class="callout"><strong>All caught up.</strong></section>`}

        <section class="stat-row">
            <a class="stat" href="#/library"><span class="stat-num">${o.sync.liked}</span><span class="stat-label">liked songs</span></a>
            <a class="stat" href="#/library/not_in_playlists"><span class="stat-num" id="home-unsorted">…</span><span class="stat-label">in no playlist</span></a>
            <a class="stat" href="#/playlists"><span class="stat-num">${o.sync.playlists}</span><span class="stat-label">playlists</span></a>
            <a class="stat" href="#/review"><span class="stat-num">${o.review.todo}</span><span class="stat-label">songs to review</span></a>
            <a class="stat" href="#/check"><span class="stat-num">${o.fit.checked ? o.fit.flagged : '–'}</span><span class="stat-label">${o.fit.checked ? 'songs that may not fit' : 'playlists not checked yet'}</span></a>
            <a class="stat" href="#/push"><span class="stat-num">${o.review.approved + o.fit.remove}</span><span class="stat-label">changes ready to apply</span></a>
        </section>

        <section class="card">
            <h2>Sort liked songs</h2>
            <ol class="step-list">
                ${STEPS.map((s, i) => `
                <li class="step-row ${s.done(o) ? 'done' : ''} ${s.key === o.next_step ? 'next' : ''}">
                    <span class="step-num">${s.done(o) ? '✓' : i + 1}</span>
                    <a href="${s.href || `#/pipeline/${s.key}`}"><strong>${esc(s.title)}</strong></a>
                    <span class="muted step-status">${esc(s.status(o))}</span>
                </li>`).join('')}
            </ol>
        </section>`;
    // "In no playlist" comes from the library endpoint (same rule as the Library page)
    try {
        const ignore = ignoredPlaylists().join(',');
        const lib = await api(`/api/library?scope=not_in_playlists&ignore=${encodeURIComponent(ignore)}`);
        const el = root.querySelector('#home-unsorted');
        if (el) el.textContent = lib.tracks.length;
    } catch { /* leave the placeholder */ }
}
