// Account: Spotify login state and which .env keys are set (never their values).
import { api, esc, toast } from '../lib.js';
import { refreshBadges } from '../app.js';

let root;

export async function mount(el) {
    root = el;
    await render();
}

async function render() {
    const o = await api('/api/overview');
    const key = (ok, name, use) => `
        <li><span class="${ok ? 'ok' : 'warn'}">${ok ? '✓' : '✗'}</span> <code>${name}</code> <span class="muted">${use}</span></li>`;
    root.innerHTML = `
        <header class="page-head"><h1>Account</h1></header>
        <section class="card">
            <h2>Spotify</h2>
            ${o.account.logged_in
                ? `<p>Logged in${o.account.display_name ? ` as <strong>${esc(o.account.display_name)}</strong>` : ''}.</p>
                   <p class="muted">Signing out deletes the saved login token on this computer. Your synced data stays.</p>
                   <div class="step-actions"><button class="btn" id="logout">Sign out</button>
                   <a class="btn" href="/login" title="Use this if Spotify refuses changes (e.g. after new permissions were added)">Log in again</a></div>`
                : `<p>Not logged in.</p>
                   <div class="step-actions"><a class="btn btn-primary" href="/login" ${o.keys.spotify ? '' : 'aria-disabled="true"'}>Log in with Spotify</a></div>`}
        </section>
        <section class="card">
            <h2>Keys in .env</h2>
            <ul class="key-list">
                ${key(o.keys.spotify, 'SPOTIFY_CLIENT_ID / SECRET', 'Login and sync')}
                ${key(o.keys.lastfm, 'LASTFM_API_KEY', 'Mood and style tags')}
                ${key(o.keys.openai, 'OPENAI_API_KEY', 'Classifying songs into vibes (coming next)')}
            </ul>
            <p class="muted small">Keys live only in the <code>.env</code> file in the project folder, which is never committed.
            Restart the server after editing it. The Spotify app also needs <code>http://127.0.0.1:8080/callback</code> as a redirect URI.</p>
        </section>`;
    root.querySelector('#logout')?.addEventListener('click', async () => {
        await api('/api/logout', {});
        toast('Signed out');
        render();
        refreshBadges();
    });
}
