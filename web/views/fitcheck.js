// Playlist check: songs already in a vibe playlist that may not fit it. Keep, remove, or move each.
import { $, $$, api, esc, toast } from '../lib.js';
import { refreshBadges, startJob } from '../app.js';
import { bindPlayerClicks, control, destroyPlayers, mountPlayers, playerHtml } from './player.js';

const THRESHOLD_KEY = 'fitThreshold';
const COST_PER_SONG = 0.00015;   // from the Spooky test run (72 songs, $0.01)

let root;
const state = { view: 'flagged', vibe: '', q: '', threshold: 50, tracks: [], total: 0, focus: 0,
                stats: null, names: {}, undo: [] };

function loadThreshold() {
    try { return Number(localStorage.getItem(THRESHOLD_KEY)) || 50; } catch { return 50; }
}

export async function mount(el, [vibe]) {
    root = el;
    state.vibe = vibe || '';
    state.threshold = loadThreshold();
    state.undo = [];
    const cfg = await api('/api/stats');
    state.names = Object.fromEntries(cfg.playlists.map(p => [p.key, p.name]));
    root.innerHTML = `
        <header class="page-head">
            <h1>Playlist check</h1>
            <p class="muted">Songs already in your vibe playlists, scored on how well they fit each one. Keep what belongs,
            remove or move what doesn't. Nothing changes in Spotify until you apply it.</p>
        </header>
        <div class="profile-bar" id="check-bar"></div>
        <div class="review-layout">
            <aside class="side-list" aria-label="Filter by playlist">
                <button class="pl-item" data-vibe="">All playlists <span class="count" id="all-count"></span></button>
                <div id="playlist-list"></div>
            </aside>
            <div>
                <div class="toolbar">
                    <div class="toolbar-head">
                        <div class="tabs" id="tabs">
                            ${[['flagged', "Doesn't fit"], ['all', 'All by fit'], ['decided', 'Decided']].map(([v, l]) =>
                                `<button data-view="${v}" class="${v === state.view ? 'active' : ''}">${l} <span class="count"></span></button>`).join('')}
                        </div>
                        <a class="btn" id="to-apply" href="#/push">Apply to Spotify <span class="count" id="apply-count"></span></a>
                    </div>
                    <div class="toolbar-row">
                        <input id="search" type="search" placeholder="Search title or artist  ( / )">
                        <label class="threshold">Flag below <input id="threshold" type="range" min="10" max="90" step="5"
                            value="${state.threshold}"> <strong id="threshold-val">${state.threshold}</strong></label>
                    </div>
                    <p id="filter-desc" class="muted small"></p>
                </div>
                <div id="cards"></div>
                <div class="more">
                    <button class="btn" id="load-more" hidden>Load more</button>
                    <div id="empty" class="empty" hidden></div>
                </div>
            </div>
        </div>
        <footer class="hotkeys">
            <span><kbd>j</kbd>/<kbd>k</kbd> next/prev</span>
            <span><kbd>a</kbd> keep</span>
            <span><kbd>r</kbd> remove</span>
            <span><kbd>v</kbd> move to suggested</span>
            <span><kbd>z</kbd> undo</span>
            <span><kbd>Space</kbd> play · <kbd>←</kbd>/<kbd>→</kbd> ∓15s</span>
        </footer>`;
    bind();
    document.addEventListener('keydown', onKey);
    await load();
}

export function unmount() {
    document.removeEventListener('keydown', onKey);
    destroyPlayers();
}

export function onJobDone(run) {
    if (run?.type === 'fitcheck') load();
}

// ---------- data ----------

async function load(append = false) {
    const p = new URLSearchParams({ view: state.view, threshold: state.threshold, offset: append ? state.tracks.length : 0, limit: 20 });
    if (state.vibe) p.set('vibe', state.vibe);
    if (state.q) p.set('q', state.q);
    const data = await api(`/api/fit?${p}`);
    state.stats = data.stats;
    const start = state.tracks.length;
    state.tracks = append ? state.tracks.concat(data.tracks) : data.tracks;
    state.total = data.total;
    renderChrome();
    if (!append) {
        state.focus = 0;
        destroyPlayers();
        $('#cards', root).innerHTML = state.tracks.map(cardHtml).join('');
    } else {
        $('#cards', root).insertAdjacentHTML('beforeend', data.tracks.map((t, j) => cardHtml(t, start + j)).join(''));
    }
    mountPlayers($('#cards', root));
    $('#load-more', root).hidden = state.tracks.length >= state.total;
    const empty = $('#empty', root);
    empty.hidden = state.tracks.length > 0;
    const pl = state.stats.playlists.find(p => p.key === state.vibe);
    empty.innerHTML = (pl ? pl.checked === 0 : state.stats.totals.checked === 0)
        ? 'Not checked yet. Use the Check button above.'
        : state.view === 'flagged' ? 'Nothing below the threshold here. Everything left looks like it fits.' : 'Nothing here yet.';
}

function renderChrome() {
    const s = state.stats;
    const pl = s.playlists.find(p => p.key === state.vibe);
    const unchecked = pl ? pl.size - pl.checked : s.totals.size - s.totals.checked;
    const scope = pl ? `"${pl.name}"` : 'all vibe playlists';
    $('#check-bar', root).innerHTML = `
        <span class="muted">${pl ? `${pl.checked} of ${pl.size} songs checked` : `${s.totals.checked} of ${s.totals.size} songs checked`}
            · ${s.totals.remove} queued for removal · ${s.totals.removed} removed</span>
        ${unchecked > 0 ? `<button class="btn ${s.totals.checked === 0 ? 'btn-primary' : ''}" id="run-check"
            title="Uses your OpenAI credit">Check ${unchecked} song${unchecked === 1 ? '' : 's'} in ${esc(scope)} (≈ $${Math.max(0.01, unchecked * COST_PER_SONG).toFixed(2)})</button>` : ''}`;
    $('#run-check', root)?.addEventListener('click', async () => {
        if (await startJob('fitcheck', state.vibe ? { vibe: state.vibe } : {})) toast('Checking… results appear here when done');
    });
    const counts = { flagged: pl ? pl.flagged : s.totals.flagged, all: pl ? pl.checked : s.totals.checked,
                     decided: null };
    $$('#tabs button', root).forEach(b => { b.querySelector('.count').textContent = counts[b.dataset.view] ?? ''; });
    $('#all-count', root).textContent = s.totals.flagged || '';
    $('#playlist-list', root).innerHTML = s.playlists.map(p => `
        <button class="pl-item ${state.vibe === p.key ? 'active' : ''}" data-vibe="${p.key}">
            <span class="name">${esc(p.name)}</span>
            <span class="count" title="${p.checked ? `${p.flagged} below ${state.threshold}` : 'not checked yet'}">${p.checked ? p.flagged : '–'}</span>
        </button>`).join('');
    $('.pl-item[data-vibe=""]', root).classList.toggle('active', !state.vibe);
    $('#apply-count', root).textContent = s.totals.remove || '';
    $('#filter-desc', root).textContent = pl ? `${pl.name}: ${pl.size} songs` : '';
}

// ---------- cards ----------

function fitClass(f) {
    return f < 40 ? 'fit-bad' : f < 60 ? 'fit-meh' : 'fit-ok';
}

function cardHtml(t, i) {
    const c = t.check;
    const name = state.names[c.vibe_key] || c.vibe_key;
    const others = t.in_playlists.filter(k => k !== c.vibe_key);
    const moveOptions = Object.entries(state.names).filter(([k]) => k !== c.vibe_key && !t.in_playlists.includes(k));
    const decided = c.status !== 'unreviewed';
    const statusText = { keep: 'Keeping it', remove: c.move_to ? `Will move to ${state.names[c.move_to]}` : 'Will remove',
                         removed: 'Removed from Spotify' }[c.status];
    return `
    <article class="song-card ${i === state.focus ? 'focused' : ''} ${decided && state.view === 'flagged' ? 'done' : ''}" data-i="${i}">
        <div>
            ${playerHtml(t.track_id, t.name)}
            <div class="label">Genres / tags</div>
            <div class="chips">${t.genres.concat(t.tags).slice(0, 10).map(g => `<span class="chip">${esc(g)}</span>`).join('') || '<span class="muted">none found</span>'}</div>
            ${others.length ? `<div class="label">Also in</div>
            <div class="chips">${others.map(k => `<span class="chip in">${esc(state.names[k] || k)}</span>`).join('')}</div>` : ''}
        </div>
        <div>
            <div class="title">${esc(t.name)}</div>
            <div class="sub">${esc(t.artists.join(', '))} · ${esc(t.album)}${t.year ? ` · ${t.year}` : ''}</div>
            <div class="fit-box ${fitClass(c.fit)}">
                <div class="fit-head"><span>In <strong>${esc(name)}</strong></span><span class="fit-score">${c.fit}</span></div>
                <div class="reason">${esc(c.reason || '')}</div>
                ${c.better.length ? `<div class="small">Fits better in: <strong>${c.better.map(k => esc(state.names[k] || k)).join(', ')}</strong></div>` : ''}
            </div>
            ${decided ? `
            <div class="card-foot"><span class="status-tag">${esc(statusText)}</span>
                ${c.status !== 'removed' ? '<button class="btn" data-fit="unreviewed">Undo</button>'
                    : '<a class="small" href="#/push">Put back from Apply to Spotify</a>'}</div>` : `
            <div class="card-foot">
                <button class="btn" data-fit="keep" title="It belongs (a)">Keep</button>
                <button class="btn btn-danger" data-fit="remove" title="Remove from ${esc(name)} (r)">Remove</button>
                ${c.better[0] ? `<button class="btn" data-fit="remove" data-move="${c.better[0]}" title="Remove here, add there (v)">Move to ${esc(state.names[c.better[0]])}</button>` : ''}
                <select data-move-select aria-label="Move to another playlist"><option value="">Move to…</option>
                    ${moveOptions.map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join('')}</select>
            </div>`}
        </div>
    </article>`;
}

function rerenderCard(i) {
    const el = $(`.song-card[data-i="${i}"]`, root);
    if (!el) return;
    // Keep the player element: replacing it would reload the iframe and stop the song
    const tmp = document.createElement('div');
    tmp.innerHTML = cardHtml(state.tracks[i], i);
    const fresh = tmp.firstElementChild;
    el.className = fresh.className;
    el.children[1].replaceWith(fresh.children[1]);
}

// ---------- decisions ----------

async function decide(items, { recordUndo = true } = {}) {
    let res;
    try {
        res = await api('/api/fit/decide', { items });
    } catch (e) {
        return toast(`Failed: ${e.message}`);
    }
    if (recordUndo && res.changed.length) {
        state.undo.push(res.changed.map(c => ({ track_id: c.track_id, vibe_key: c.vibe_key, status: c.previous,
                                                 move_to: c.previous_move_to })));
    }
    for (const c of res.changed) {
        const i = state.tracks.findIndex(t => t.track_id === c.track_id && t.check.vibe_key === c.vibe_key);
        if (i < 0) continue;
        Object.assign(state.tracks[i].check, { status: c.status, move_to: c.status === 'remove' ? c.move_to || null : null });
        rerenderCard(i);
    }
    if (res.skipped.length) toast(`Skipped: ${res.skipped[0].reason}`);
    const data = await api(`/api/fit?view=${state.view}&threshold=${state.threshold}&limit=1`);
    state.stats = data.stats;
    renderChrome();
    refreshBadges();
}

function decideCard(i, status, moveTo) {
    const t = state.tracks[i];
    if (!t || t.check.status === 'removed') return;
    decide([{ track_id: t.track_id, vibe_key: t.check.vibe_key, status, move_to: moveTo || null }]);
}

async function undo() {
    const batch = state.undo.pop();
    if (!batch) return toast('Nothing to undo');
    await decide(batch, { recordUndo: false });
    toast('Undone');
}

// ---------- events ----------

function setFocus(i) {
    if (!state.tracks.length) return;
    state.focus = Math.max(0, Math.min(i, state.tracks.length - 1));
    $$('.song-card', root).forEach(c => c.classList.toggle('focused', +c.dataset.i === state.focus));
    $(`.song-card[data-i="${state.focus}"]`, root)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function bind() {
    bindPlayerClicks($('#cards', root));
    $('#cards', root).addEventListener('click', (e) => {
        const card = e.target.closest('.song-card');
        if (!card) return;
        const i = +card.dataset.i;
        if (i !== state.focus) setFocus(i);
        const btn = e.target.closest('button[data-fit]');
        if (btn) decideCard(i, btn.dataset.fit, btn.dataset.move);
    });
    $('#cards', root).addEventListener('change', (e) => {
        const sel = e.target.closest('select[data-move-select]');
        if (sel?.value) decideCard(+sel.closest('.song-card').dataset.i, 'remove', sel.value);
    });
    $('.side-list', root).addEventListener('click', (e) => {
        const b = e.target.closest('.pl-item');
        if (!b) return;
        state.vibe = b.dataset.vibe;
        history.replaceState(null, '', state.vibe ? `#/check/${state.vibe}` : '#/check');
        load();
    });
    $('#tabs', root).addEventListener('click', (e) => {
        const b = e.target.closest('button[data-view]');
        if (!b) return;
        state.view = b.dataset.view;
        $$('#tabs button', root).forEach(x => x.classList.toggle('active', x === b));
        load();
    });
    let searchTimer, thTimer;
    $('#search', root).addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { state.q = e.target.value.trim(); load(); }, 250);
    });
    $('#threshold', root).addEventListener('input', (e) => {
        state.threshold = +e.target.value;
        $('#threshold-val', root).textContent = state.threshold;
        try { localStorage.setItem(THRESHOLD_KEY, state.threshold); } catch { /* per-browser convenience only */ }
        clearTimeout(thTimer);
        thTimer = setTimeout(load, 250);
    });
    $('#load-more', root).addEventListener('click', () => load(true));
}

function onKey(e) {
    if (e.target.matches?.('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (!$('#modal-root').hidden) return;
    const t = state.tracks[state.focus];
    if (e.key === 'j') setFocus(state.focus + 1);
    else if (e.key === 'k') setFocus(state.focus - 1);
    else if (e.key === 'z') undo();
    else if (e.key === '/') { e.preventDefault(); $('#search', root).focus(); }
    else if (!t) return;
    else if (e.key === ' ') { e.preventDefault(); control(t.track_id, 'toggle'); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); control(t.track_id, 'back'); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); control(t.track_id, 'fwd'); }
    else if (e.key === 'a') decideCard(state.focus, 'keep');
    else if (e.key === 'r') decideCard(state.focus, 'remove');
    else if (e.key === 'v' && t.check.better[0]) decideCard(state.focus, 'remove', t.check.better[0]);
}
