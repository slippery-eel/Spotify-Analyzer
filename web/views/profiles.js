// Profiles: review and edit the drafted profile of each vibe playlist.
import { $, api, esc, toast } from '../lib.js';
import { refreshBadges, startJob } from '../app.js';

let root;
let list = [];
let current = null;      // vibe key being shown
let savedText = '';      // last saved text, to detect unsaved edits

export async function mount(el, [key]) {
    root = el;
    root.innerHTML = `
        <header class="page-head">
            <h1>Vibe profiles</h1>
            <p class="muted">Each profile is drafted from the songs already in that playlist. Edit the text so it says what
            really makes a song belong there; the classifier reads your description, this profile, and the example songs.</p>
        </header>
        <div class="profile-bar">
            <span id="progress" class="muted"></span>
            <button class="btn" id="redraft" title="Rebuilds stats and drafts from the current playlist contents. Your edited text is kept.">Re-draft from playlists</button>
        </div>
        <div class="review-layout">
            <aside class="side-list" aria-label="Vibe playlists" id="pl-list"></aside>
            <section id="detail"></section>
        </div>`;
    $('#redraft', root).addEventListener('click', async () => {
        await saveIfDirty();
        if (await startJob('profiles')) toast('Re-drafting… your edits are kept');
    });
    $('#pl-list', root).addEventListener('click', async (e) => {
        const b = e.target.closest('.pl-item');
        if (!b) return;
        await saveIfDirty();
        show(b.dataset.vibe);
    });
    document.addEventListener('keydown', onKey);
    window.addEventListener('beforeunload', onBeforeUnload);
    await load(key);
}

export async function unmount() {
    document.removeEventListener('keydown', onKey);
    window.removeEventListener('beforeunload', onBeforeUnload);
    await saveIfDirty();
}

export function onJobDone(run) {
    if (run?.type === 'profiles') load(current);
}

async function load(key) {
    list = (await api('/api/profiles')).profiles;
    if (!list.some(p => p.profile_text)) {
        $('#pl-list', root).innerHTML = '';
        $('#detail', root).innerHTML = `<div class="empty">No profiles yet.
            <p><button class="btn btn-primary" id="first-draft">Draft profiles</button></p></div>`;
        $('#first-draft', root).addEventListener('click', () => startJob('profiles'));
        return;
    }
    renderList();
    const first = list.find(p => p.profile_text && !p.reviewed_at) || list.find(p => p.profile_text);
    show(key && list.some(p => p.key === key) ? key : first.key);
}

function badge(p) {
    if (!p.profile_text) return '<span class="muted" title="Playlist not found in Spotify">–</span>';
    if (p.reviewed_at) return '<span class="ok" title="Reviewed">✓</span>';
    if (p.is_edited) return '<span class="warn" title="Edited, not reviewed">✎</span>';
    return '<span class="muted" title="Draft, not reviewed">•</span>';
}

function renderList() {
    const reviewed = list.filter(p => p.reviewed_at).length;
    const total = list.filter(p => p.profile_text).length;
    $('#progress', root).textContent = `${reviewed} of ${total} reviewed`;
    $('#pl-list', root).innerHTML = list.map(p => `
        <button class="pl-item ${p.key === current ? 'active' : ''}" data-vibe="${p.key}">
            <span class="name">${esc(p.name)}</span>${badge(p)}
        </button>`).join('');
}

function chips(items, fmt) {
    return items && items.length
        ? `<div class="chips">${items.map(x => `<span class="chip">${esc(fmt(x))}</span>`).join('')}</div>`
        : '<p class="muted small">None</p>';
}

function show(key) {
    current = key;
    history.replaceState(null, '', `#/profiles/${key}`);
    const p = list.find(x => x.key === key);
    renderList();
    const s = p.stats;
    savedText = p.profile_text || '';
    $('#detail', root).innerHTML = !s ? `<div class="empty">"${esc(p.name)}" wasn't found among your Spotify playlists,
        so there's nothing to draft from. Check its name in config.py and run Sync again.</div>` : `
        <div class="profile-head">
            <h2>${esc(p.name)}</h2>
            <span class="muted">${s.size} songs · ${p.reviewed_at ? 'reviewed' : p.is_edited ? 'edited, not reviewed' : 'draft, not reviewed'}</span>
        </div>

        <div class="card">
            <div class="label">Your description</div>
            <p>${esc(p.description)}</p>
            ${p.rule ? `<p class="small"><strong>Hard rule:</strong> ${esc(p.rule)}</p>` : ''}
            <p class="muted small">Change this in <code>config.py</code>. Use the profile below for everything else.</p>
        </div>

        <div class="card">
            <label class="label" for="profile-text">Profile: what the classifier reads</label>
            <textarea id="profile-text" class="profile-text" rows="9" spellcheck="true">${esc(p.profile_text)}</textarea>
            <p class="muted small">Tip: add what genre tags can't capture, such as mood, energy, when you'd play it, and what doesn't belong.
            <kbd>Ctrl</kbd>+<kbd>Enter</kbd> marks it reviewed and moves on.</p>
            <div class="step-actions">
                <button class="btn btn-primary" id="approve">${p.reviewed_at ? 'Save & next' : 'Mark reviewed & next'}</button>
                <button class="btn" id="save" disabled>Save</button>
                ${p.is_edited ? '<button class="btn" id="reset" title="Replace your text with the latest auto draft">Reset to draft</button>' : ''}
                ${p.reviewed_at ? '<button class="btn" id="unreview">Mark not reviewed</button>' : ''}
            </div>
        </div>

        <div class="profile-stats">
            <div class="card">
                <div class="label">Stands out for <span class="muted">(much more common here than in your library)</span></div>
                ${chips(s.distinctive, ([l, lift]) => `${l} ×${lift}`)}
                <div class="label">Most common</div>
                ${chips(s.common, ([l, pct]) => `${l} ${pct}%`)}
                <div class="label">Eras</div>
                ${chips(s.decades, ([d, pct]) => `${d} ${pct}%`)}
                <div class="label">Instrumental</div>
                <p class="small">${s.instrumental_pct == null ? 'Unknown (no lyrics data)' : `${s.instrumental_pct}% of songs with lyrics data`}</p>
                <div class="label">Frequent artists</div>
                ${chips(s.artists, ([a, n]) => `${a} (${n})`)}
                <div class="label">Shares songs with</div>
                ${chips(s.overlaps, ([n, pct]) => `${n}: ${pct}%`)}
            </div>
            <div class="card">
                <div class="label">Example songs <span class="muted">(most typical of this playlist)</span></div>
                <ol class="examples">${s.examples.map(e => `
                    <li><a href="https://open.spotify.com/track/${e.track_id}" target="_blank" rel="noopener">${esc(e.name)}</a>
                    <span class="muted">${esc(e.artist)}</span></li>`).join('')}</ol>
                ${p.playlist_id ? `<a class="small" href="#/playlists/${encodeURIComponent(p.playlist_id)}">See all songs in this playlist</a>` : ''}
            </div>
        </div>`;
    if (!s) return;
    const ta = $('#profile-text', root);
    ta.addEventListener('input', () => { $('#save', root).disabled = ta.value.trim() === savedText.trim(); });
    $('#save', root).addEventListener('click', () => save({}));
    $('#approve', root).addEventListener('click', approveAndNext);
    $('#reset', root)?.addEventListener('click', () => save({ reset: true }));
    $('#unreview', root)?.addEventListener('click', () => save({ reviewed: false }));
}

// rerender=false when the caller shows another profile right after
async function save({ reset = false, reviewed, rerender = true }) {
    const ta = $('#profile-text', root);
    const body = { reset };
    if (reviewed !== undefined) body.reviewed = reviewed;
    if (!reset && ta) body.profile_text = ta.value;
    try {
        const updated = await api(`/api/profiles/${current}`, body);
        list = list.map(p => p.key === current ? updated : p);
        savedText = updated.profile_text || '';
        refreshBadges();
        return updated;
    } catch (e) {
        toast(`Couldn't save: ${e.message}`, 5000);
        return null;
    } finally {
        if (rerender) show(current);
    }
}

async function saveIfDirty() {
    const ta = root && $('#profile-text', root);
    if (ta && current && ta.value.trim() !== savedText.trim()) {
        await api(`/api/profiles/${current}`, { profile_text: ta.value });
        toast('Saved your profile edits');
    }
}

async function approveAndNext() {
    const updated = await save({ reviewed: true, rerender: false });
    if (!updated) return;
    const order = list.filter(p => p.stats);
    const i = order.findIndex(p => p.key === current);
    const next = order.slice(i + 1).concat(order.slice(0, i)).find(p => !p.reviewed_at);
    if (next) show(next.key);
    else { show(current); toast('All profiles reviewed. Classification is the next step.', 5000); }
}

function onKey(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && $('#profile-text', root)) {
        e.preventDefault();
        approveAndNext();
    }
}

function onBeforeUnload(e) {
    const ta = root && $('#profile-text', root);
    if (ta && ta.value.trim() !== savedText.trim()) { e.preventDefault(); e.returnValue = ''; }
}

