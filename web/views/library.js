// Library: all liked songs (or those in no playlist) with filters, charts, and Save as Playlist.
// Ported from the original app's "All Liked Songs Analysis" + "Liked Songs Not in Playlists".
import { $, $$, api, cssVar, esc, fmtDate, pct } from '../lib.js';
import { savePlaylistModal } from './save.js';

const IGNORE_KEY = 'ignoredPlaylists';
const CHARTS_KEY = 'libraryCharts';

export function ignoredPlaylists() {
    try { return JSON.parse(localStorage.getItem(IGNORE_KEY) || '[]'); } catch { return []; }
}
function setIgnored(ids) {
    try { localStorage.setItem(IGNORE_KEY, JSON.stringify(ids)); } catch { /* storage unavailable */ }
}

let root;
let charts = [];
const state = {
    scope: 'liked', genre: '', artist: '', from: '', to: '', dedupe: false,
    sort: { col: 'added', dir: 'desc' },
    data: null, selected: new Set(), playlists: [],
};

export async function mount(el, [scope]) {
    root = el;
    state.scope = scope === 'not_in_playlists' ? 'not_in_playlists' : 'liked';
    state.selected = new Set();
    let showCharts = true;
    try { showCharts = localStorage.getItem(CHARTS_KEY) !== 'off'; } catch { /* default on */ }
    root.innerHTML = `
        <header class="page-head">
            <h1>Library</h1>
            <p class="muted">Your liked songs, with the original analyzer's filters and charts.</p>
        </header>
        <div class="tabs" id="scope-tabs">
            <a href="#/library" data-scope="liked" class="${state.scope === 'liked' ? 'active' : ''}">All liked songs</a>
            <a href="#/library/not_in_playlists" data-scope="not_in_playlists" class="${state.scope === 'not_in_playlists' ? 'active' : ''}">In no playlist</a>
        </div>
        <div id="coverage" class="coverage"></div>

        <div class="filters card-flat">
            <label>Genre / tag <select id="f-genre"><option value="">Any</option></select></label>
            <label>Artist <input id="f-artist" type="search" placeholder="Any artist"></label>
            <label>Liked from <input id="f-from" type="month"></label>
            <label>to <input id="f-to" type="month"></label>
            <label class="check"><input id="f-dedupe" type="checkbox"> Hide duplicates</label>
            <details class="ignore-pop" id="ignore-pop">
                <summary class="btn">Playlists that count…</summary>
                <div class="pop">
                    <p class="muted small">Unticked playlists are ignored when deciding if a song is "in a playlist"
                    (useful for old export playlists).</p>
                    <div id="ignore-list"></div>
                </div>
            </details>
            <button class="btn" id="f-clear">Clear filters</button>
        </div>

        <details class="charts" id="charts" ${showCharts ? 'open' : ''}>
            <summary>Charts</summary>
            <div class="chart-grid">
                <figure><figcaption>Top genres</figcaption><div class="chart-box"><canvas id="c-genres"></canvas></div></figure>
                <figure><figcaption>Top artists</figcaption><div class="chart-box"><canvas id="c-artists"></canvas></div></figure>
                <figure class="wide"><figcaption id="c-timeline-cap">Liked over time</figcaption><div class="chart-box"><canvas id="c-timeline"></canvas></div></figure>
            </div>
        </details>

        <div class="table-bar">
            <span id="count" class="muted"></span>
            <button class="btn btn-primary" id="save">Save as playlist</button>
        </div>
        <div class="table-wrap"><table class="tracks" id="table"></table></div>`;
    bind();
    state.playlists = (await api('/api/playlists')).playlists;
    renderIgnoreList();
    await load();
}

export function unmount() {
    charts.forEach(c => c.destroy());
    charts = [];
}

async function load() {
    const p = new URLSearchParams({ scope: state.scope, dedupe: state.dedupe });
    if (state.genre) p.set('genre', state.genre);
    if (state.artist) p.set('artist', state.artist);
    if (state.from) p.set('date_from', state.from);
    if (state.to) p.set('date_to', state.to);
    const ignore = ignoredPlaylists();
    if (ignore.length) p.set('ignore', ignore.join(','));
    state.data = await api(`/api/library?${p}`);
    // Drop selections that are no longer visible
    const visible = new Set(state.data.tracks.map(t => t.track_id));
    state.selected = new Set([...state.selected].filter(id => visible.has(id)));
    renderGenreOptions();
    renderCoverage();
    renderTable();
    renderCharts();
}

function renderGenreOptions() {
    const sel = $('#f-genre', root);
    sel.innerHTML = '<option value="">Any</option>' + state.data.genre_options
        .map(g => `<option value="${esc(g.name)}">${esc(g.name)} (${g.count})</option>`).join('');
    sel.value = state.genre;
}

function renderCoverage() {
    const d = state.data;
    const p = pct(d.in_playlists, d.liked_total);
    $('#coverage', root).innerHTML = `
        <div class="coverage-label"><strong>${p}%</strong> of your ${d.liked_total} liked songs are in at least one playlist
        · <a href="#/library/not_in_playlists">${d.liked_total - d.in_playlists} aren't</a></div>
        <div class="coverage-track"><i style="width:${p}%"></i></div>`;
}

function renderIgnoreList() {
    const ignored = new Set(ignoredPlaylists());
    $('#ignore-list', root).innerHTML = state.playlists.filter(p => p.is_owned).map(p => `
        <label class="check"><input type="checkbox" value="${p.playlist_id}" ${ignored.has(p.playlist_id) ? '' : 'checked'}>
        ${esc(p.name)} <span class="muted">(${p.synced_tracks})</span></label>`).join('');
}

// ---------- table ----------

const COLS = [
    { key: 'name', label: 'Track', get: t => t.name.toLowerCase() },
    { key: 'artists', label: 'Artists', get: t => t.artists.join(', ').toLowerCase() },
    { key: 'genres', label: 'Genres / tags' },
    { key: 'playlists', label: 'Playlists', get: t => t.playlists.length },
    { key: 'added', label: 'Liked', get: t => t.added_at || '' },
];

function sortedTracks() {
    const col = COLS.find(c => c.key === state.sort.col);
    const dir = state.sort.dir === 'asc' ? 1 : -1;
    return [...state.data.tracks].sort((a, b) => {
        const x = col.get(a), y = col.get(b);
        return x < y ? -dir : x > y ? dir : 0;
    });
}

function renderTable() {
    const tracks = sortedTracks();
    const names = state.data.playlist_names;
    const allSel = tracks.length > 0 && tracks.every(t => state.selected.has(t.track_id));
    $('#table', root).innerHTML = `
        <thead><tr>
            <th class="col-check"><input type="checkbox" id="sel-all" ${allSel ? 'checked' : ''} aria-label="Select all shown"></th>
            ${COLS.map(c => c.get
                ? `<th class="sortable" data-col="${c.key}" aria-sort="${state.sort.col === c.key ? (state.sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}">
                    ${c.label} <span class="sort-icon">${state.sort.col === c.key ? (state.sort.dir === 'asc' ? '▲' : '▼') : ''}</span></th>`
                : `<th>${c.label}</th>`).join('')}
            <th></th>
        </tr></thead>
        <tbody>${tracks.map(t => `
            <tr class="${state.selected.has(t.track_id) ? 'selected' : ''}">
                <td class="col-check"><input type="checkbox" data-id="${t.track_id}" ${state.selected.has(t.track_id) ? 'checked' : ''} aria-label="Select ${esc(t.name)}"></td>
                <td class="t-name">${esc(t.name)}</td>
                <td>${esc(t.artists.join(', '))}</td>
                <td class="t-genres">${esc((t.genres.length ? t.genres : t.tags).slice(0, 3).join(', ')) || '<span class="muted">—</span>'}</td>
                <td class="num" title="${esc(t.playlists.map(p => names[p]).join('\n'))}">${t.playlists.length || '<span class="muted">0</span>'}</td>
                <td class="nowrap">${fmtDate(t.added_at)}</td>
                <td><a class="open-link" href="https://open.spotify.com/track/${t.track_id}" target="_blank" rel="noopener" aria-label="Open in Spotify">↗</a></td>
            </tr>`).join('')}
        </tbody>`;
    if (!tracks.length) $('#table', root).insertAdjacentHTML('beforeend', '<tbody><tr><td colspan="7" class="empty">No songs match these filters.</td></tr></tbody>');
    updateCount();
}

function updateCount() {
    const n = state.data.tracks.length, s = state.selected.size;
    $('#count', root).textContent = `${n} song${n === 1 ? '' : 's'}${s ? ` · ${s} selected` : ''}`;
    $('#save', root).textContent = s ? `Save ${s} selected as playlist` : `Save all ${n} as playlist`;
    $('#save', root).disabled = n === 0;
}

// ---------- charts ----------

function renderCharts() {
    if (!window.Chart || !$('#charts', root).open) return;
    charts.forEach(c => c.destroy());
    charts = [];
    const a = state.data.analytics;
    const text = cssVar('--muted'), grid = cssVar('--border'), green = cssVar('--green');
    const palette = ['#1db954', '#4c9aff', '#f5a623', '#e5534b', '#b37feb', '#2ec4b6', '#ff7eb6', '#c2d94c', '#8d99ae', '#ffb86b'];
    Chart.defaults.color = text;
    Chart.defaults.borderColor = grid;
    charts.push(new Chart($('#c-genres', root), {
        type: 'doughnut',
        data: { labels: a.genres.map(g => g[0]), datasets: [{ data: a.genres.map(g => g[1]), backgroundColor: palette, borderWidth: 0 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 10 } } } },
    }));
    charts.push(new Chart($('#c-artists', root), {
        type: 'bar',
        data: { labels: a.artists.map(x => x[0]), datasets: [{ data: a.artists.map(x => x[1]), backgroundColor: green, borderRadius: 3 }] },
        options: { indexAxis: 'y', maintainAspectRatio: false, plugins: { legend: { display: false } },
                   scales: { x: { ticks: { precision: 0 } } } },
    }));
    $('#c-timeline-cap', root).textContent = `Liked per ${a.timeline_unit}`;
    charts.push(new Chart($('#c-timeline', root), {
        type: 'bar',
        data: { labels: a.timeline.map(x => x[0]), datasets: [{ data: a.timeline.map(x => x[1]), backgroundColor: green, borderRadius: 3 }] },
        options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { ticks: { precision: 0 } } } },
    }));
}

// ---------- events ----------

function bind() {
    let t;
    const reload = (delay = 0) => { clearTimeout(t); t = setTimeout(load, delay); };
    $('#f-genre', root).addEventListener('change', e => { state.genre = e.target.value; reload(); });
    $('#f-artist', root).addEventListener('input', e => { state.artist = e.target.value.trim(); reload(300); });
    $('#f-from', root).addEventListener('change', e => { state.from = e.target.value; reload(); });
    $('#f-to', root).addEventListener('change', e => { state.to = e.target.value; reload(); });
    $('#f-dedupe', root).addEventListener('change', e => { state.dedupe = e.target.checked; reload(); });
    $('#f-clear', root).addEventListener('click', () => {
        Object.assign(state, { genre: '', artist: '', from: '', to: '', dedupe: false });
        $('#f-artist', root).value = ''; $('#f-from', root).value = ''; $('#f-to', root).value = '';
        $('#f-dedupe', root).checked = false;
        reload();
    });
    $('#ignore-list', root).addEventListener('change', () => {
        setIgnored($$('#ignore-list input', root).filter(i => !i.checked).map(i => i.value));
        reload();
    });
    $('#charts', root).addEventListener('toggle', e => {
        try { localStorage.setItem(CHARTS_KEY, e.target.open ? 'on' : 'off'); } catch { /* ignore */ }
        if (e.target.open && state.data) renderCharts();
    });
    $('#table', root).addEventListener('click', e => {
        const th = e.target.closest('th.sortable');
        if (th) {
            const col = th.dataset.col;
            state.sort = state.sort.col === col
                ? { col, dir: state.sort.dir === 'asc' ? 'desc' : 'asc' }
                : { col, dir: col === 'added' || col === 'playlists' ? 'desc' : 'asc' };
            renderTable();
        }
    });
    $('#table', root).addEventListener('change', e => {
        if (e.target.id === 'sel-all') {
            const ids = state.data.tracks.map(t => t.track_id);
            if (e.target.checked) ids.forEach(id => state.selected.add(id)); else state.selected.clear();
            renderTable();
            return;
        }
        const id = e.target.dataset.id;
        if (!id) return;
        if (e.target.checked) state.selected.add(id); else state.selected.delete(id);
        e.target.closest('tr').classList.toggle('selected', e.target.checked);
        $('#sel-all', root).checked = state.data.tracks.every(t => state.selected.has(t.track_id));
        updateCount();
    });
    $('#save', root).addEventListener('click', () => {
        const ids = state.selected.size ? [...state.selected] : sortedTracks().map(t => t.track_id);
        const label = state.scope === 'not_in_playlists' ? 'Liked songs not in playlists' : 'Liked songs';
        savePlaylistModal(ids, label, state.playlists, async () => {
            state.playlists = (await api('/api/playlists')).playlists;
            renderIgnoreList();
            load();
        });
    });
}
