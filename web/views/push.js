// Add to Spotify: everything you approved, grouped by playlist, added with one button.
import { $, api, esc, fmtDate, openModal, toast } from '../lib.js';
import { refreshBadges, startJob } from '../app.js';

let root;

export async function mount(el) {
    root = el;
    root.addEventListener('click', onClick);
    await render();
}

export function unmount() {
    root?.removeEventListener('click', onClick);
}

export function onJobDone(run) {
    if (run?.type === 'push') render();
}

let groups = [];

async function render() {
    const [{ groups: g, recent }, o] = await Promise.all([api('/api/push'), api('/api/overview')]);
    groups = g;
    const songs = groups.reduce((n, x) => n + x.songs.length, 0);
    const running = o.job?.type === 'push';
    root.innerHTML = `
        <header class="page-head">
            <h1>Add to Spotify</h1>
            <p class="muted">Everything you approved in Review, grouped by playlist. Adding is add-only: nothing is removed
            from any playlist or from Liked Songs. Songs already in a playlist are skipped.</p>
        </header>
        ${songs ? `
        <section class="callout">
            <div><strong>${songs} song${songs === 1 ? '' : 's'} → ${groups.length} playlist${groups.length === 1 ? '' : 's'}</strong>
            <p class="muted">${o.review.todo ? `${o.review.todo} songs still have undecided suggestions in <a href="#/review">Review</a>; you can add these now and the rest later.` : 'Ready when you are.'}</p></div>
            <button class="btn btn-primary" id="push" ${o.job || !o.account.logged_in ? 'disabled' : ''}>
                ${running ? 'Adding…' : `Add ${songs} song${songs === 1 ? '' : 's'} to ${groups.length} playlist${groups.length === 1 ? '' : 's'}`}</button>
        </section>
        ${!o.account.logged_in ? '<p class="warn">Log in on the Account page first.</p>' : ''}
        ${groups.map(gr => `
        <section class="card push-group">
            <h2>${esc(gr.name)} <span class="count">${gr.songs.length}</span></h2>
            ${!gr.playlist_id ? '<p class="warn small">This playlist wasn\'t found in Spotify; check its name in config.py and Sync.</p>' : ''}
            <ul class="push-list">${gr.songs.map(s => `
                <li><div><strong>${esc(s.name)}</strong> <span class="muted">${esc(s.artists.join(', '))}</span>
                    <div class="muted small">${s.score != null ? `${s.score} · ` : ''}${esc(s.reason || '')}</div></div>
                    <button class="btn" data-undo="${s.track_id}" data-vibe="${gr.key}" title="Move back to Review as undecided">Undo approval</button></li>`).join('')}
            </ul>
        </section>`).join('')}` : `
        <div class="empty">Nothing approved and waiting. Approve suggestions in <a href="#/review">Review</a> and they'll collect here.</div>`}
        ${recent.length ? `
        <h2 class="section-title">Recently added</h2>
        <div class="table-wrap"><table class="tracks compact">
            <thead><tr><th>Song</th><th>Playlist</th><th>Added</th></tr></thead>
            <tbody>${recent.map(r => `<tr><td><strong>${esc(r.name)}</strong> <span class="muted">${esc(r.artists.join(', '))}</span></td>
                <td>${esc(r.playlist)}</td><td class="nowrap">${fmtDate(r.added_at)}</td></tr>`).join('')}</tbody>
        </table></div>` : ''}`;
}

async function onClick(e) {
    const undo = e.target.closest('button[data-undo]');
    if (undo) {
        undo.disabled = true;
        await api('/api/decide', { items: [{ track_id: undo.dataset.undo, vibe_key: undo.dataset.vibe, status: 'pending' }] });
        toast('Moved back to Review');
        refreshBadges();
        render();
        return;
    }
    if (e.target.closest('#push')) confirmPush();
}

function confirmPush() {
    const songs = groups.reduce((n, x) => n + x.songs.length, 0);
    const { el, close } = openModal(`
        <h2>Add ${songs} songs to Spotify?</h2>
        <ul class="push-confirm">${groups.map(g => `<li><span>${esc(g.name)}</span><strong>+${g.songs.length}</strong></li>`).join('')}</ul>
        <p class="muted small">This changes your Spotify playlists. It only adds songs; nothing is removed, and Liked Songs isn't touched.</p>
        <div class="modal-actions"><button class="btn" id="c-no">Cancel</button>
        <button class="btn btn-primary" id="c-yes">Add to Spotify</button></div>`);
    $('#c-no', el).addEventListener('click', close);
    $('#c-yes', el).addEventListener('click', async () => {
        close();
        if (await startJob('push')) render();
    });
}
