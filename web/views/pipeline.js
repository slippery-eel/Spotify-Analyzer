// Pipeline: the sort-liked-songs workflow as a stepper with Run buttons.
import { api, esc, timeAgo } from '../lib.js';
import { startJob } from '../app.js';
import { STEPS } from './steps.js';

let root;
let focusKey;

export async function mount(el, [key]) {
    root = el;
    focusKey = key;
    await render();
    if (focusKey) root.querySelector(`[data-step="${focusKey}"]`)?.scrollIntoView({ block: 'center' });
}

export function onJobDone() { render(); }

async function render() {
    const o = await api('/api/overview');
    const busy = !!o.job;
    root.innerHTML = `
        <header class="page-head">
            <h1>Sort liked songs</h1>
            <p class="muted">Each step builds on the one before. Re-run any step whenever your library changes.</p>
        </header>
        <ol class="stepper">
        ${STEPS.map((s, i) => {
            const last = s.job ? o.last_jobs[s.job] : null;
            const running = o.job && (o.job.type === s.job || o.job.type === s.extra?.job);
            const loginNeeded = s.job && !o.account.logged_in;
            const keyNeeded = s.key === 'enrich' && !o.keys.lastfm;
            return `
            <li class="step ${s.done(o) ? 'done' : ''} ${s.key === o.next_step ? 'next' : ''} ${s.key === focusKey ? 'focused' : ''}" data-step="${s.key}">
                <span class="step-num">${s.done(o) ? '✓' : i + 1}</span>
                <div class="step-body">
                    <h2>${esc(s.title)} ${s.soon ? '<span class="pill">coming next</span>' : ''}</h2>
                    <p>${esc(s.what)}</p>
                    <p class="muted">${esc(s.status(o))}</p>
                    ${last ? `<p class="muted small">Last run ${timeAgo(last.finished_at)}: ${esc(last.summary || '')}</p>` : ''}
                    ${loginNeeded ? '<p class="warn small">Log in on the Account page first.</p>' : ''}
                    ${keyNeeded ? '<p class="warn small">Add LASTFM_API_KEY to .env first.</p>' : ''}
                    <div class="step-actions">
                        ${s.job ? `<button class="btn ${s.key === o.next_step ? 'btn-primary' : ''}" data-job="${s.job}"
                            ${busy || loginNeeded || keyNeeded ? 'disabled' : ''}>${running ? 'Running…' : s.runLabel ? s.runLabel(o) : s.done(o) ? 'Run again' : 'Run'}</button>` : ''}
                        ${s.extra && s.extra.show(o) ? `<button class="btn" data-job="${s.extra.job}" ${busy || loginNeeded ? 'disabled' : ''}
                            title="${esc(s.extra.hint(o))}">${esc(s.extra.label)}</button>` : ''}
                        ${s.href && !(s.key === 'profiles' && !o.profiles) ? `<a class="btn ${s.key === o.next_step ? 'btn-primary' : ''}" href="${s.href}">Open</a>` : ''}
                    </div>
                </div>
            </li>`;
        }).join('')}
        </ol>`;
    root.querySelectorAll('button[data-job]').forEach(b => b.addEventListener('click', async () => {
        b.disabled = true;
        if (await startJob(b.dataset.job)) render();
        else b.disabled = false;
    }));
}
