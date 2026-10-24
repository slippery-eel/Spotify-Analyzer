// Save as Playlist modal (new private playlist, or add to one you own). Used by Library and Playlists.
import { $, api, esc, openModal, toast } from '../lib.js';

export function savePlaylistModal(trackIds, defaultName, playlists, onSaved) {
    const owned = playlists.filter(p => p.is_owned);
    const { el, close } = openModal(`
        <h2>Save as playlist</h2>
        <p class="muted">${trackIds.length} song${trackIds.length === 1 ? '' : 's'} · this changes your Spotify account.</p>
        <div class="tabs" role="tablist">
            <button class="active" data-mode="new" role="tab">New playlist</button>
            <button data-mode="existing" role="tab">Add to existing</button>
        </div>
        <label class="field" data-pane="new">Name
            <input id="pl-name" type="text" value="${esc(defaultName)}"></label>
        <label class="field" data-pane="existing" hidden>Playlist
            <select id="pl-existing">${owned.map(p => `<option value="${p.playlist_id}">${esc(p.name)}</option>`).join('')}</select></label>
        <p class="muted small" data-pane="new">Created as a private playlist.</p>
        <p class="muted small" data-pane="existing" hidden>Songs already in it are skipped.</p>
        <p id="pl-status" class="small"></p>
        <div class="modal-actions">
            <button class="btn" id="pl-cancel">Cancel</button>
            <button class="btn btn-primary" id="pl-confirm">Create playlist</button>
        </div>`);
    let mode = 'new';
    el.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => {
        mode = b.dataset.mode;
        el.querySelectorAll('[data-mode]').forEach(x => x.classList.toggle('active', x === b));
        el.querySelectorAll('[data-pane]').forEach(p => { p.hidden = p.dataset.pane !== mode; });
        $('#pl-confirm', el).textContent = mode === 'new' ? 'Create playlist' : 'Add songs';
    }));
    $('#pl-cancel', el).addEventListener('click', close);
    $('#pl-name', el).focus();
    $('#pl-confirm', el).addEventListener('click', async () => {
        const btn = $('#pl-confirm', el);
        const status = $('#pl-status', el);
        btn.disabled = true;
        status.textContent = 'Saving to Spotify…';
        try {
            const body = mode === 'new'
                ? { track_ids: trackIds, name: $('#pl-name', el).value }
                : { track_ids: trackIds, playlist_id: $('#pl-existing', el).value };
            const res = await api('/api/save-playlist', body);
            close();
            toast(`Added ${res.added} song${res.added === 1 ? '' : 's'} to "${res.name}"${res.skipped ? ` (${res.skipped} already there)` : ''}`, 5000);
            onSaved?.(res);
        } catch (e) {
            status.textContent = e.message;
            status.className = 'small warn';
            btn.disabled = false;
        }
    });
}
