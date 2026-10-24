// Review queue UI: one card per song, approve/decline each suggested playlist.
const state = {
    view: 'pending', vibe: '', q: '', sort: 'score',
    tracks: [], total: 0, focus: 0,
    playlists: [], names: {},
    undo: [],   // stack of [{track_id, vibe_key, status: previous}] batches
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, body) {
    const res = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
}

let toastTimer;
function toast(msg) {
    const el = $('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2500);
}

// ---------- stats + sidebar ----------

async function loadStats() {
    const s = await api('/api/stats');
    state.playlists = s.playlists;
    state.names = Object.fromEntries(s.playlists.map(p => [p.key, p.name]));
    $('#login-link').hidden = s.logged_in;
    $('#summary').textContent = `${s.liked} liked songs · ${s.classified} classified`;
    document.querySelectorAll('#tabs button').forEach(b => {
        b.querySelector('.count').textContent = s.counts[b.dataset.view] || 0;
    });
    $('#all-count').textContent = s.counts[state.view] || 0;
    $('#playlist-list').innerHTML = s.playlists.map(p => `
        <button class="pl-item ${state.vibe === p.key ? 'active' : ''}" data-vibe="${p.key}" title="${esc(p.description)}">
            <span class="name">${esc(p.name)}</span><span class="count">${p.counts[state.view] || 0}</span>
        </button>`).join('');
    document.querySelector('.pl-item[data-vibe=""]').classList.toggle('active', !state.vibe);
    const p = s.playlists.find(p => p.key === state.vibe);
    $('#filter-desc').textContent = p ? `${p.name} (${p.size} songs): ${p.description}` : '';
}

// ---------- queue ----------

async function loadQueue(append = false) {
    const params = new URLSearchParams({ view: state.view, sort: state.sort, offset: append ? state.tracks.length : 0, limit: 20 });
    if (state.vibe) params.set('vibe', state.vibe);
    if (state.q) params.set('q', state.q);
    const data = await api(`/api/queue?${params}`);
    state.tracks = append ? state.tracks.concat(data.tracks) : data.tracks;
    state.total = data.total;
    if (!append) state.focus = 0;
    render();
}

function cardHtml(t, i) {
    const sugs = orderedSuggestions(t);
    const done = state.view === 'pending' && !sugs.some(s => s.status === 'pending');
    const suggested = new Set(t.suggestions.map(s => s.vibe_key).concat(t.in_playlists));
    const addable = state.playlists.filter(p => !suggested.has(p.key));
    return `
    <article class="card ${i === state.focus ? 'focused' : ''} ${done ? 'done' : ''}" data-i="${i}">
        <div>
            <iframe loading="lazy" src="https://open.spotify.com/embed/track/${t.track_id}?theme=0" allow="encrypted-media" title="Play ${esc(t.name)}"></iframe>
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
            ${addable.length && state.view !== 'added' ? `<div class="add-row">
                <select data-add="${i}"><option value="">+ Add to another playlist…</option>
                ${addable.map(p => `<option value="${p.key}">${esc(p.name)}</option>`).join('')}</select>
            </div>` : ''}
        </div>
    </article>`;
}

function orderedSuggestions(t) {
    // The filtered playlist first, then by score
    return [...t.suggestions].sort((a, b) =>
        (b.vibe_key === state.vibe) - (a.vibe_key === state.vibe) || (b.score ?? 101) - (a.score ?? 101));
}

function sugHtml(s, j) {
    const locked = s.status === 'added';
    return `
    <div class="sug ${s.status} ${s.vibe_key === state.vibe ? 'highlight' : ''}" data-vibe="${s.vibe_key}">
        <span class="idx">${j < 9 ? j + 1 : ''}</span>
        <div>
            <span class="sug-name">${esc(state.names[s.vibe_key] || s.vibe_key)}</span>
            ${s.score != null ? `<span class="score">${s.score}</span><span class="bar"><i style="width:${s.score}%"></i></span>` : ''}
            <div class="reason">${esc(s.reason || '')}</div>
        </div>
        ${locked ? '<span class="status-tag">added ✓</span>' : `<div class="actions">
            <button class="ok" data-act="approved" title="Approve">✓</button>
            <button class="no" data-act="declined" title="Decline">✗</button>
        </div>`}
    </div>`;
}

function render() {
    $('#cards').innerHTML = state.tracks.map(cardHtml).join('');
    $('#load-more').hidden = state.tracks.length >= state.total;
    const empty = state.tracks.length === 0;
    $('#empty').hidden = !empty;
    $('#empty').textContent = state.view === 'pending'
        ? 'Nothing pending here. Run the classifier to get suggestions, or pick another playlist.'
        : `No ${state.view} suggestions here yet.`;
}

function rerenderCard(i) {
    const el = document.querySelector(`.card[data-i="${i}"]`);
    if (!el) return;
    // Keep the existing iframe so playback isn't interrupted
    const iframe = el.querySelector('iframe');
    const tmp = document.createElement('div');
    tmp.innerHTML = cardHtml(state.tracks[i], i);
    const fresh = tmp.firstElementChild;
    fresh.querySelector('iframe').replaceWith(iframe);
    el.replaceWith(fresh);
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
    document.querySelectorAll('.card').forEach(c => c.classList.toggle('focused', +c.dataset.i === state.focus));
    document.querySelector(`.card[data-i="${state.focus}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

$('#cards').addEventListener('click', (e) => {
    const card = e.target.closest('.card');
    if (!card) return;
    const i = +card.dataset.i;
    if (i !== state.focus) setFocus(i);
    const btn = e.target.closest('button[data-act]');
    if (btn) toggle(i, btn.closest('.sug').dataset.vibe, btn.dataset.act);
});

$('#cards').addEventListener('change', (e) => {
    const sel = e.target.closest('select[data-add]');
    if (!sel || !sel.value) return;
    decide([{ track_id: state.tracks[+sel.dataset.add].track_id, vibe_key: sel.value, status: 'approved' }]);
});

document.querySelector('.sidebar').addEventListener('click', (e) => {
    const b = e.target.closest('.pl-item');
    if (!b) return;
    state.vibe = b.dataset.vibe;
    loadStats();
    loadQueue();
});

$('#tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-view]');
    if (!b) return;
    state.view = b.dataset.view;
    document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('active', x === b));
    loadStats();
    loadQueue();
});

let searchTimer;
$('#search').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.q = e.target.value.trim(); loadQueue(); }, 250);
});
$('#sort').addEventListener('change', (e) => { state.sort = e.target.value; loadQueue(); });
$('#load-more').addEventListener('click', () => loadQueue(true));
$('#approve-page').addEventListener('click', () => decideRest(state.tracks.map((_, i) => i), 'approved'));
$('#decline-page').addEventListener('click', () => decideRest(state.tracks.map((_, i) => i), 'declined'));

document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = state.tracks[state.focus];
    if (e.key === 'j') setFocus(state.focus + 1);
    else if (e.key === 'k') setFocus(state.focus - 1);
    else if (e.key === 'z') undo();
    else if (e.key === '/') { e.preventDefault(); $('#search').focus(); }
    else if (!t) return;
    else if (e.key === 'a') decideRest([state.focus], 'approved');
    else if (e.key === 'd') decideRest([state.focus], 'declined');
    else if (/^Digit[1-9]$/.test(e.code)) {
        const s = orderedSuggestions(t)[+e.code.slice(5) - 1];
        if (s) toggle(state.focus, s.vibe_key, e.shiftKey ? 'declined' : 'approved');
    }
});

loadStats().then(() => loadQueue()).catch(e => toast(`Could not reach the server: ${e.message}`));
