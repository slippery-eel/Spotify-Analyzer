// Review queue: one card per song, approve/decline each suggested playlist.
import { $, $$, api, esc, toast } from '../lib.js';
import { refreshBadges } from '../app.js';
import { bindPlayerClicks, control, destroyPlayers, mountPlayers, playerHtml } from './player.js';

let root;
const state = {
    view: 'todo', vibe: '', q: '', sort: 'score',
    tracks: [], total: 0, focus: 0,
    playlists: [], names: {},
    undo: [],   // stack of [{track_id, vibe_key, status: previous}] batches
};

export async function mount(el, [vibe]) {
    root = el;
    state.vibe = vibe || '';
    state.undo = [];
    root.innerHTML = `
        <header class="page-head">
            <h1>Review suggestions</h1>
            <p class="muted" id="summary"></p>
        </header>
        <div class="review-layout">
            <aside class="side-list" aria-label="Filter by playlist">
                <button class="pl-item" data-vibe="">All playlists <span class="count" id="all-count"></span></button>
                <div id="playlist-list"></div>
            </aside>
            <div>
                <div class="toolbar">
                    <div class="toolbar-head">
                        <div class="tabs" id="tabs">
                            ${[['todo', 'To review'], ['done', 'Reviewed']].map(([v, label]) =>
                                `<button data-view="${v}" class="${v === state.view ? 'active' : ''}">${label} <span class="count"></span></button>`).join('')}
                        </div>
                        <a class="btn" id="to-push" href="#/push">Add to Spotify <span class="count" id="push-count"></span></a>
                    </div>
                    <div class="toolbar-row">
                        <input id="search" type="search" placeholder="Search title, artist, album  ( / )" value="${esc(state.q)}">
                        <select id="sort">
                            <option value="score">Best fit first</option>
                            <option value="added">Recently liked first</option>
                        </select>
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
            <span><kbd>j</kbd>/<kbd>k</kbd> next/prev song</span>
            <span><kbd>1</kbd>–<kbd>9</kbd> approve suggestion</span>
            <span><kbd>Shift</kbd>+<kbd>1</kbd>–<kbd>9</kbd> decline</span>
            <span><kbd>a</kbd>/<kbd>d</kbd> approve/decline the rest of this song</span>
            <span><kbd>Space</kbd> play/pause · <kbd>←</kbd>/<kbd>→</kbd> ∓15s · <kbd>m</kbd> middle</span>
            <span><kbd>z</kbd> undo</span>
        </footer>`;
    $('#sort', root).value = state.sort;
    bind();
    document.addEventListener('keydown', onKey);
    await loadStats();
    await loadQueue();
}

export function unmount() {
    document.removeEventListener('keydown', onKey);
    destroyPlayers();
}

// ---------- stats + playlist list ----------

async function loadStats() {
    const s = await api('/api/stats');
    state.playlists = s.playlists;
    state.names = Object.fromEntries(s.playlists.map(p => [p.key, p.name]));
    $('#summary', root).textContent = `${s.liked} liked songs · ${s.classified} classified so far`;
    $$('#tabs button', root).forEach(b => { b.querySelector('.count').textContent = s.counts[b.dataset.view] || 0; });
    // Sidebar: undecided suggestions while reviewing, approved-and-waiting on the Reviewed tab
    const perVibe = state.view === 'todo' ? 'pending' : 'approved';
    $('#all-count', root).textContent = s.counts[perVibe] || 0;
    $('#push-count', root).textContent = s.counts.approved || '';
    $('#to-push', root).classList.toggle('btn-primary', s.counts.approved > 0 && !s.counts.todo);
    $('#playlist-list', root).innerHTML = s.playlists.map(p => `
        <button class="pl-item ${state.vibe === p.key ? 'active' : ''}" data-vibe="${p.key}" title="${esc(p.description)}">
            <span class="name">${esc(p.name)}</span><span class="count">${p.counts[perVibe] || 0}</span>
        </button>`).join('');
    $('.pl-item[data-vibe=""]', root).classList.toggle('active', !state.vibe);
    const p = s.playlists.find(p => p.key === state.vibe);
    $('#filter-desc', root).textContent = p ? `${p.name} (${p.size} songs): ${p.description}` : '';
}

// ---------- queue ----------

async function loadQueue(append = false) {
    const params = new URLSearchParams({ view: state.view, sort: state.sort, offset: append ? state.tracks.length : 0, limit: 20 });
    if (state.vibe) params.set('vibe', state.vibe);
    if (state.q) params.set('q', state.q);
    const data = await api(`/api/queue?${params}`);
    const start = state.tracks.length;
    state.tracks = append ? state.tracks.concat(data.tracks) : data.tracks;
    state.total = data.total;
    if (!append) {
        state.focus = 0;
        return render();
    }
    // Append only the new cards so players already on the page keep playing
    $('#cards', root).insertAdjacentHTML('beforeend', data.tracks.map((t, j) => cardHtml(t, start + j)).join(''));
    mountPlayers($('#cards', root));
    $('#load-more', root).hidden = state.tracks.length >= state.total;
}

function orderedSuggestions(t) {
    // The filtered playlist first, then by score
    return [...t.suggestions].sort((a, b) =>
        (b.vibe_key === state.vibe) - (a.vibe_key === state.vibe) || (b.score ?? 101) - (a.score ?? 101));
}

function cardHtml(t, i) {
    const sugs = orderedSuggestions(t);
    const pendingN = sugs.filter(s => s.status === 'pending').length;
    const approvedN = sugs.filter(s => s.status === 'approved').length;
    const done = state.view === 'todo' && !pendingN;
    const suggested = new Set(t.suggestions.map(s => s.vibe_key).concat(t.in_playlists));
    const addable = state.playlists.filter(p => !suggested.has(p.key));
    return `
    <article class="song-card ${i === state.focus ? 'focused' : ''} ${done ? 'done' : ''}" data-i="${i}">
        <div>
            ${playerHtml(t.track_id, t.name)}
            <div class="label">Genres / tags</div>
            <div class="chips">${t.genres.concat(t.tags).slice(0, 12).map(g => `<span class="chip">${esc(g)}</span>`).join('') || '<span class="muted">none found</span>'}</div>
            ${t.in_playlists.length ? `<div class="label">Already in</div>
            <div class="chips">${t.in_playlists.map(k => `<span class="chip in">${esc(state.names[k] || k)}</span>`).join('')}</div>` : ''}
        </div>
        <div>
            <div class="title">${esc(t.name)}</div>
            <div class="sub">${esc(t.artists.join(', '))} · ${esc(t.album)}${t.year ? ` · ${t.year}` : ''}</div>
            ${t.vibe_summary ? `<div class="summary">${esc(t.vibe_summary)}</div>` : ''}
            <div class="label">Suggested playlists</div>
            <div class="sugs">${sugs.map((s, j) => sugHtml(s, j)).join('')}</div>
            ${addable.length ? `<div class="add-row">
                <select data-add="${i}" aria-label="Add to another playlist"><option value="">+ Add to another playlist…</option>
                ${addable.map(p => `<option value="${p.key}">${esc(p.name)}</option>`).join('')}</select>
            </div>` : ''}
            <div class="card-foot">
                ${pendingN ? `<button class="btn" data-rest="approved">Approve the rest (${pendingN})</button>
                <button class="btn" data-rest="declined">Decline the rest</button>`
                : '<span class="muted small">All decided</span>'}
                ${approvedN ? `<a class="small" href="#/push">${approvedN} approved → Add to Spotify</a>` : ''}
            </div>
        </div>
    </article>`;
}

function sugHtml(s, j) {
    const locked = s.status === 'added';
    return `
    <div class="sug ${s.status} ${s.vibe_key === state.vibe ? 'highlight' : ''}" data-vibe="${s.vibe_key}">
        <span class="idx">${j < 9 ? j + 1 : ''}</span>
        <div>
            <span class="sug-name">${esc(state.names[s.vibe_key] || s.vibe_key)}</span>
            ${s.status === 'approved' ? '<span class="pill pill-ok">will add</span>' : ''}
            ${s.score != null ? `<span class="score">${s.score}</span><span class="bar"><i style="width:${s.score}%"></i></span>` : ''}
            <div class="reason">${esc(s.reason || '')}</div>
        </div>
        ${locked ? '<span class="status-tag">✓ In playlist</span>' : `<div class="actions">
            <button class="ok" data-act="approved" title="Approve" aria-label="Approve">✓</button>
            <button class="no" data-act="declined" title="Decline" aria-label="Decline">✗</button>
        </div>`}
    </div>`;
}

function render() {
    destroyPlayers();
    $('#cards', root).innerHTML = state.tracks.map(cardHtml).join('');
    mountPlayers($('#cards', root));
    $('#load-more', root).hidden = state.tracks.length >= state.total;
    const empty = $('#empty', root);
    empty.hidden = state.tracks.length > 0;
    empty.innerHTML = state.view === 'todo'
        ? 'Nothing left to review here. New suggestions appear after the <a href="#/pipeline/classify">Classify</a> step runs.'
        : 'No reviewed songs here yet.';
}

function rerenderCard(i) {
    const el = $(`.song-card[data-i="${i}"]`, root);
    if (!el) return;
    // Update everything except the player: moving or replacing its iframe would reload it and stop playback
    const tmp = document.createElement('div');
    tmp.innerHTML = cardHtml(state.tracks[i], i);
    const fresh = tmp.firstElementChild;
    el.className = fresh.className;
    el.children[1].replaceWith(fresh.children[1]);
    const left = el.children[0];
    [...left.children].filter(c => !c.classList.contains('player')).forEach(c => c.remove());
    [...fresh.children[0].children].filter(c => !c.classList.contains('player')).forEach(c => left.appendChild(c));
}

// ---------- decisions ----------

async function decide(items, { recordUndo = true } = {}) {
    if (!items.length) return;
    let res;
    try {
        res = await api('/api/decide', { items });
    } catch (e) {
        toast(`Failed: ${e.message}`);
        return;
    }
    if (recordUndo && res.changed.length) {
        state.undo.push(res.changed.map(c => ({ track_id: c.track_id, vibe_key: c.vibe_key, status: c.previous ?? 'removed' })));
    }
    for (const c of res.changed) applyLocal(c.track_id, c.vibe_key, c.status);
    if (res.skipped.length) toast(`Skipped ${res.skipped.length}: ${res.skipped[0].reason}`);
    loadStats();
    refreshBadges();
}

function applyLocal(trackId, vibe, status) {
    const i = state.tracks.findIndex(t => t.track_id === trackId);
    if (i < 0) return;
    const t = state.tracks[i];
    const s = t.suggestions.find(s => s.vibe_key === vibe);
    if (status === 'removed') t.suggestions = t.suggestions.filter(s => s.vibe_key !== vibe);
    else if (s) s.status = status;
    else t.suggestions.push({ vibe_key: vibe, score: null, reason: 'Added manually', status });
    rerenderCard(i);
}

function toggle(i, vibe, act) {
    const s = state.tracks[i].suggestions.find(s => s.vibe_key === vibe);
    if (!s || s.status === 'added') return;
    // Clicking the active state again resets to pending (or removes a manual row)
    let status = s.status === act ? 'pending' : act;
    if (status === 'pending' && s.reason === 'Added manually') status = 'removed';
    decide([{ track_id: state.tracks[i].track_id, vibe_key: vibe, status }]);
}

function decideRest(indexes, status) {
    const items = [];
    for (const i of indexes) {
        const t = state.tracks[i];
        for (const s of t.suggestions) if (s.status === 'pending') items.push({ track_id: t.track_id, vibe_key: s.vibe_key, status });
    }
    decide(items);
}

async function undo() {
    const batch = state.undo.pop();
    if (!batch) return toast('Nothing to undo');
    await decide(batch, { recordUndo: false });
    toast(`Undid ${batch.length} change${batch.length > 1 ? 's' : ''}`);
}

// ---------- focus + events ----------

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
        const btn = e.target.closest('button[data-act]');
        if (btn) toggle(i, btn.closest('.sug').dataset.vibe, btn.dataset.act);
        const rest = e.target.closest('button[data-rest]');
        if (rest) decideRest([i], rest.dataset.rest);
    });
    $('#cards', root).addEventListener('change', (e) => {
        const sel = e.target.closest('select[data-add]');
        if (!sel || !sel.value) return;
        decide([{ track_id: state.tracks[+sel.dataset.add].track_id, vibe_key: sel.value, status: 'approved' }]);
    });
    $('.side-list', root).addEventListener('click', (e) => {
        const b = e.target.closest('.pl-item');
        if (!b) return;
        state.vibe = b.dataset.vibe;
        history.replaceState(null, '', state.vibe ? `#/review/${state.vibe}` : '#/review');
        loadStats();
        loadQueue();
    });
    $('#tabs', root).addEventListener('click', (e) => {
        const b = e.target.closest('button[data-view]');
        if (!b) return;
        state.view = b.dataset.view;
        $$('#tabs button', root).forEach(x => x.classList.toggle('active', x === b));
        loadStats();
        loadQueue();
    });
    let searchTimer;
    $('#search', root).addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { state.q = e.target.value.trim(); loadQueue(); }, 250);
    });
    $('#sort', root).addEventListener('change', (e) => { state.sort = e.target.value; loadQueue(); });
    $('#load-more', root).addEventListener('click', () => loadQueue(true));
}

function onKey(e) {
    if (e.target.matches('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
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
    else if (e.key === 'm') control(t.track_id, 'mid');
    else if (e.key === 'a') decideRest([state.focus], 'approved');
    else if (e.key === 'd') decideRest([state.focus], 'declined');
    else if (/^Digit[1-9]$/.test(e.code)) {
        const s = orderedSuggestions(t)[+e.code.slice(5) - 1];
        if (s) toggle(state.focus, s.vibe_key, e.shiftKey ? 'declined' : 'approved');
    }
}
