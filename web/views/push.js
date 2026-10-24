// Apply to Spotify: everything you decided, in one place. Removals (from Playlist check) and
// additions (approved in Review), grouped by playlist, applied with one confirmed button.
import { $, api, esc, fmtDate, openModal, toast } from '../lib.js';
import { refreshBadges, startJob } from '../app.js';

let root;
let data = null;

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

const count = (groups) => groups.reduce((n, g) => n + g.songs.length, 0);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

async function render() {
    const [d, o] = await Promise.all([api('/api/apply'), api('/api/overview')]);
    data = d;
    const nAdd = count(d.adds), nRemove = count(d.removes);
    const playlists = new Set(d.adds.concat(d.removes).map(g => g.key)).size;
    const running = o.job?.type === 'push';
    const songRow = (s, gKey, kind) => `
        <li><div><strong>${esc(s.name)}</strong> <span class="muted">${esc(s.artists.join(', '))}</span>
            <div class="muted small">${kind === 'remove'
                ? `fit ${s.fit} · ${esc(s.reason || '')}${s.move_to ? ` · <strong>moving to ${esc(s.move_to)}</strong>` : ''}`
                : `${s.score != null ? `${s.score} · ` : ''}${esc(s.reason || '')}`}</div></div>
            <button class="btn" data-undo="${kind}" data-track="${s.track_id}" data-vibe="${gKey}">Undo</button></li>`;
    root.innerHTML = `
        <header class="page-head">
            <h1>Apply to Spotify</h1>
            <p class="muted">Everything you decided, waiting to be sent to Spotify. Removals only take a song out of that
            one playlist; Liked Songs is never touched. Songs already in a playlist are skipped.</p>
        </header>
        ${nAdd + nRemove ? `
        <section class="callout">
            <div><strong>${nRemove ? `−${plural(nRemove, 'song')}` : ''}${nRemove && nAdd ? ' · ' : ''}${nAdd ? `+${plural(nAdd, 'song')}` : ''}
                across ${plural(playlists, 'playlist')}</strong>
            <p class="muted">${o.review.todo ? `${o.review.todo} songs still to review in <a href="#/review">Review</a>` : ''}${o.review.todo && o.fit.flagged ? ' · ' : ''}${o.fit.flagged ? `${o.fit.flagged} flagged in <a href="#/check">Playlist check</a>` : ''}${!o.review.todo && !o.fit.flagged ? 'Ready when you are.' : '. You can apply these now and the rest later.'}</p></div>
            <button class="btn btn-primary" id="apply" ${o.job || !o.account.logged_in ? 'disabled' : ''}>${running ? 'Applying…' : 'Apply to Spotify'}</button>
        </section>
        ${!o.account.logged_in ? '<p class="warn">Log in on the Account page first.</p>' : ''}` : `
        <div class="empty">Nothing waiting. Approve suggestions in <a href="#/review">Review</a>, or remove songs in
            <a href="#/check">Playlist check</a>, and they'll collect here.</div>`}

        ${nRemove ? `<h2 class="section-title">Remove <span class="count">${nRemove}</span></h2>
        ${d.removes.map(g => `
        <section class="card push-group remove-group">
            <h2>${esc(g.name)} <span class="count">−${g.songs.length}</span></h2>
            <ul class="push-list">${g.songs.map(s => songRow(s, g.key, 'remove')).join('')}</ul>
        </section>`).join('')}` : ''}

        ${nAdd ? `<h2 class="section-title">Add <span class="count">${nAdd}</span></h2>
        ${d.adds.map(g => `
        <section class="card push-group">
            <h2>${esc(g.name)} <span class="count">+${g.songs.length}</span></h2>
            ${!g.playlist_id ? '<p class="warn small">This playlist wasn\'t found in Spotify; check its name in config.py and Sync.</p>' : ''}
            <ul class="push-list">${g.songs.map(s => songRow(s, g.key, 'add')).join('')}</ul>
        </section>`).join('')}` : ''}

        ${d.recent_removed.length ? `
        <h2 class="section-title">Recently removed</h2>
        <div class="table-wrap"><table class="tracks compact">
            <thead><tr><th>Song</th><th>From</th><th>Removed</th><th></th></tr></thead>
            <tbody>${d.recent_removed.map(r => `<tr><td><strong>${esc(r.name)}</strong> <span class="muted">${esc(r.artists.join(', '))}</span></td>
                <td>${esc(r.playlist)}</td><td class="nowrap">${fmtDate(r.removed_at)}</td>
                <td><button class="btn" data-restore="${r.track_id}" data-vibe="${r.vibe_key}" title="Add it back at its old position">Put back</button></td></tr>`).join('')}</tbody>
        </table></div>` : ''}
        ${d.recent_added.length ? `
        <h2 class="section-title">Recently added</h2>
        <div class="table-wrap"><table class="tracks compact">
            <thead><tr><th>Song</th><th>Playlist</th><th>Added</th></tr></thead>
            <tbody>${d.recent_added.map(r => `<tr><td><strong>${esc(r.name)}</strong> <span class="muted">${esc(r.artists.join(', '))}</span></td>
                <td>${esc(r.playlist)}</td><td class="nowrap">${fmtDate(r.added_at)}</td></tr>`).join('')}</tbody>
        </table></div>` : ''}`;
}

async function onClick(e) {
    const undo = e.target.closest('button[data-undo]');
    if (undo) {
        undo.disabled = true;
        const item = { track_id: undo.dataset.track, vibe_key: undo.dataset.vibe };
        if (undo.dataset.undo === 'add') await api('/api/decide', { items: [{ ...item, status: 'pending' }] });
        else await api('/api/fit/decide', { items: [{ ...item, status: 'unreviewed' }] });
        toast(undo.dataset.undo === 'add' ? 'Moved back to Review' : 'Moved back to Playlist check');
        refreshBadges();
        return render();
    }
    const restore = e.target.closest('button[data-restore]');
    if (restore) {
        restore.disabled = true;
        try {
            await api('/api/apply/restore', { track_id: restore.dataset.restore, vibe_key: restore.dataset.vibe });
            toast('Put back in the playlist');
        } catch (err) {
            toast(`Couldn't put it back: ${err.message}`, 5000);
        }
        return render();
    }
    if (e.target.closest('#apply')) confirmApply();
}

function confirmApply() {
    const rows = {};
    for (const g of data.removes) rows[g.name] = { ...(rows[g.name] || {}), minus: g.songs.length };
    for (const g of data.adds) rows[g.name] = { ...(rows[g.name] || {}), plus: g.songs.length };
    const { el, close } = openModal(`
        <h2>Apply these changes to Spotify?</h2>
        <ul class="push-confirm">${Object.entries(rows).map(([name, r]) => `<li><span>${esc(name)}</span>
            <strong>${r.minus ? `<span class="minus">−${r.minus}</span>` : ''} ${r.plus ? `+${r.plus}` : ''}</strong></li>`).join('')}</ul>
        <p class="muted small">This changes your Spotify playlists. Removed songs can be put back from this page.
            Liked Songs isn't touched.</p>
        <div class="modal-actions"><button class="btn" id="c-no">Cancel</button>
        <button class="btn btn-primary" id="c-yes">Apply to Spotify</button></div>`);
    $('#c-no', el).addEventListener('click', close);
    $('#c-yes', el).addEventListener('click', async () => {
        close();
        if (await startJob('push')) render();
    });
}
