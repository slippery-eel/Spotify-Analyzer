// Playlists: every playlist you have, and the songs in each. Replaces the old Playlist Browser.
import { $, api, esc, fmtDate, openModal, toast } from '../lib.js';

let root;

export async function mount(el, [playlistId]) {
    root = el;
    const { playlists } = await api('/api/playlists');
    if (playlistId) return renderDetail(playlists, playlistId);
    renderList(playlists);
}

function cover(p) {
    return p.image_url
        ? `<img class="cover" src="${esc(p.image_url)}" alt="" loading="lazy">`
        : '<div class="cover cover-blank" aria-hidden="true">♪</div>';
}

function renderList(playlists) {
    const vibes = playlists.filter(p => p.vibe_key);
    const others = playlists.filter(p => !p.vibe_key);
    const card = p => `
        <a class="pl-card" href="#/playlists/${p.playlist_id}">
            ${cover(p)}
            <div class="pl-card-body">
                <strong>${esc(p.name)}</strong>
                <span class="muted small">${p.is_owned ? `${p.synced_tracks} songs · ${p.liked_tracks} liked` : `${p.track_total ?? '?'} songs · followed`}</span>
                ${p.description ? `<span class="small pl-desc">${esc(p.description)}</span>` : ''}
            </div>
        </a>`;
    root.innerHTML = `
        <header class="page-head">
            <h1>Playlists</h1>
            <p class="muted">${playlists.length} playlists. Vibe playlists are the ones liked songs get sorted into.</p>
        </header>
        <h2 class="section-title">Vibe playlists <span class="muted">(${vibes.length})</span></h2>
        <div class="pl-grid">${vibes.map(card).join('')}</div>
        <h2 class="section-title">Other playlists <span class="muted">(${others.length})</span></h2>
        <div class="pl-grid">${others.map(card).join('') || '<p class="muted">None</p>'}</div>`;
}

async function renderDetail(playlists, id) {
    const p = playlists.find(x => x.playlist_id === id);
    if (!p) {
        root.innerHTML = '<div class="empty">Playlist not found. <a href="#/playlists">Back to playlists</a></div>';
        return;
    }
    const data = p.is_owned ? await api(`/api/playlists/${encodeURIComponent(id)}/tracks`) : { tracks: [], playlist_names: {} };
    const names = data.playlist_names;
    root.innerHTML = `
        <a class="back" href="#/playlists">← All playlists</a>
        <header class="pl-head">
            ${cover(p)}
            <div>
                <h1>${esc(p.name)}</h1>
                <p class="muted">${p.is_owned ? `${data.tracks.length} songs · ${p.liked_tracks} liked` : 'Followed playlist'}</p>
                ${p.description ? `<p class="pl-desc">${esc(p.description)}</p>` : ''}
                <div class="step-actions">
                    <a class="btn" href="https://open.spotify.com/playlist/${p.playlist_id}" target="_blank" rel="noopener">Open in Spotify ↗</a>
                    ${data.tracks.length ? '<button class="btn" id="copy">Copy song list</button>' : ''}
                    ${p.vibe_key ? `<a class="btn" href="#/review/${p.vibe_key}">Review suggestions for this playlist</a>` : ''}
                </div>
            </div>
        </header>
        ${!p.is_owned ? `<div class="empty">Spotify only lets apps read the songs of playlists you own or collaborate on,
            so this followed playlist's songs can't be shown here.</div>` : `
        <div class="table-wrap"><table class="tracks">
            <thead><tr><th>#</th><th>Track</th><th>Artists</th><th>Genres / tags</th><th>Liked</th><th>Also in</th><th>Added</th><th></th></tr></thead>
            <tbody>${data.tracks.map((t, i) => {
                const others = t.playlists.filter(x => x !== id);
                return `<tr>
                    <td class="num muted">${i + 1}</td>
                    <td class="t-name">${esc(t.name)}</td>
                    <td>${esc(t.artists.join(', '))}</td>
                    <td class="t-genres">${esc((t.genres.length ? t.genres : t.tags).slice(0, 3).join(', ')) || '<span class="muted">—</span>'}</td>
                    <td>${t.liked ? '♥' : '<span class="muted">—</span>'}</td>
                    <td class="num" title="${esc(others.map(x => names[x]).join('\n'))}">${others.length || '<span class="muted">0</span>'}</td>
                    <td class="nowrap">${fmtDate(t.added_at)}</td>
                    <td><a class="open-link" href="https://open.spotify.com/track/${t.track_id}" target="_blank" rel="noopener" aria-label="Open in Spotify">↗</a></td>
                </tr>`;
            }).join('')}</tbody>
        </table></div>`}`;
    $('#copy', root)?.addEventListener('click', () => copyList(p.name, data.tracks));
}

async function copyList(name, tracks) {
    // Same format as the original app's copyPlaylistToClipboard()
    const text = `${name}\n\n` + tracks.map((t, i) => `${i + 1}. ${t.name} - ${t.artists.join(', ')}`).join('\n');
    try {
        await navigator.clipboard.writeText(text);
        toast(`Copied ${tracks.length} songs`);
    } catch {
        const { el } = openModal(`<h2>Copy song list</h2><p class="muted small">Your browser blocked clipboard access; copy it from here.</p>
            <textarea class="copy-area" readonly>${esc(text)}</textarea>`);
        el.querySelector('textarea').select();
    }
}
