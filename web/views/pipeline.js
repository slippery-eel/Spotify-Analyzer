// Pipeline: the sort-liked-songs workflow as a stepper with Run buttons.
import { api, esc, openModal, timeAgo } from '../lib.js';
import { startJob } from '../app.js';
import { STEPS } from './steps.js';

let root;
let focusKey;

const KEY_NAMES = { lastfm: 'LASTFM_API_KEY', openai: 'OPENAI_API_KEY' };

export async function mount(el, [key]) {
    root = el;
    focusKey = key;
    await render();
    if (focusKey) root.querySelector(`[data-step="${focusKey}"]`)?.scrollIntoView({ block: 'center' });
}

export function onJobDone() { render(); }

const val = (x, o) => (typeof x === 'function' ? x(o) : x);

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
            const last = s.job ? o.last_jobs[s.job] || (s.extra && o.last_jobs[s.extra.job]) : null;
            const running = o.job && (o.job.type === s.job || o.job.type === s.extra?.job);
            const loginNeeded = s.job && !o.account.logged_in;
            const keyNeeded = s.needsKey && !o.keys[s.needsKey];
            const blocked = busy || loginNeeded || keyNeeded;
            const showOpen = s.href && (s.showOpen ? s.showOpen(o) : true);
            return `
            <li class="step ${s.done(o) ? 'done' : ''} ${s.key === o.next_step ? 'next' : ''} ${s.key === focusKey ? 'focused' : ''}" data-step="${s.key}">
                <span class="step-num">${s.done(o) ? '✓' : i + 1}</span>
                <div class="step-body">
                    <h2>${esc(s.title)} ${s.soon ? '<span class="pill">coming next</span>' : ''}</h2>
                    <p>${esc(s.what)}</p>
                    <p class="muted">${esc(s.status(o))}</p>
                    ${last ? `<p class="muted small">Last run ${timeAgo(last.finished_at)}: ${esc(last.summary || '')}</p>` : ''}
                    ${loginNeeded ? '<p class="warn small">Log in on the Account page first.</p>' : ''}
                    ${keyNeeded ? `<p class="warn small">Add ${KEY_NAMES[s.needsKey]} to .env and restart the server first.</p>` : ''}
                    ${s.detail ? `<div class="step-detail" data-detail="${s.key}"></div>` : ''}
                    <div class="step-actions">
                        ${s.job ? `<button class="btn ${s.key === o.next_step ? 'btn-primary' : ''}" data-job="${s.job}"
                            ${blocked ? 'disabled' : ''}>${running && o.job.type === s.job ? 'Running…' : s.runLabel ? s.runLabel(o) : s.done(o) ? 'Run again' : 'Run'}</button>` : ''}
                        ${s.extra && s.extra.show(o) ? `<button class="btn ${s.extra.primary?.(o) ? 'btn-primary' : ''}" data-job="${s.extra.job}"
                            data-step="${s.key}" ${blocked ? 'disabled' : ''} title="${esc(val(s.extra.hint, o) || '')}">${esc(val(s.extra.label, o))}</button>` : ''}
                        ${showOpen ? `<a class="btn ${s.key === o.next_step && !s.job ? 'btn-primary' : ''}" href="${s.href}">${esc(s.openLabel || 'Open')}</a>` : ''}
                    </div>
                </div>
            </li>`;
        }).join('')}
        </ol>`;
    root.querySelectorAll('button[data-job]').forEach(b => b.addEventListener('click', async () => {
        const step = STEPS.find(s => s.extra?.job === b.dataset.job && b.dataset.step === s.key);
        if (step?.extra.confirm && !(await confirmRun(step.extra.confirm(o)))) return;
        b.disabled = true;
        if (await startJob(b.dataset.job)) render();
        else b.disabled = false;
    }));
    for (const s of STEPS.filter(s => s.detail)) {
        const el = root.querySelector(`[data-detail="${s.key}"]`);
        if (el) s.detail(el, o);
    }
}

function confirmRun({ title, body, ok }) {
    return new Promise(resolve => {
        const { el, close } = openModal(`<h2>${esc(title)}</h2><p>${body}</p>
            <div class="modal-actions"><button class="btn" id="c-no">Cancel</button>
            <button class="btn btn-primary" id="c-yes">${esc(ok)}</button></div>`);
        el.querySelector('#c-no').addEventListener('click', () => { close(); resolve(false); });
        el.querySelector('#c-yes').addEventListener('click', () => { close(); resolve(true); });
    });
}
