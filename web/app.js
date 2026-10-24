// App shell: hash router, nav state, and the jobs dock shared by every page.
import { $, $$, api, esc, toast } from './lib.js';
import * as home from './views/home.js';
import * as pipeline from './views/pipeline.js';
import * as review from './views/review.js';
import * as library from './views/library.js';
import * as playlists from './views/playlists.js';
import * as account from './views/account.js';

const ROUTES = { '': home, pipeline, review, library, playlists, account };
let active = null;

async function route() {
    const [name, ...rest] = location.hash.replace(/^#\/?/, '').split('/');
    const view = ROUTES[name] || home;
    if (active?.unmount) active.unmount();
    active = view;
    $$('.nav-link').forEach(a => a.classList.toggle('active', a.dataset.route === (name || 'home')));
    const el = $('#view');
    el.innerHTML = '';
    el.scrollTop = 0;
    window.scrollTo(0, 0);
    try {
        await view.mount(el, rest.map(decodeURIComponent));
    } catch (e) {
        el.innerHTML = `<div class="empty">Couldn't load this page: ${esc(e.message)}</div>`;
    }
    refreshBadges();
}

// ---------- nav badges ----------

export async function refreshBadges() {
    try {
        const o = await api('/api/overview');
        const b = $('#badge-review');
        b.hidden = !o.review.pending;
        b.textContent = o.review.pending;
        $('#dot-account').hidden = o.account.logged_in;
        renderDock(o.job);
    } catch { /* server down: dock + badges just stay as they are */ }
}

// ---------- jobs dock ----------

let pollTimer = null;
let lastJobId = null;

function renderDock(job) {
    const dock = $('#jobs-dock');
    if (!job) {
        dock.hidden = true;
        if (lastJobId) jobFinished(lastJobId);
        lastJobId = null;
        return;
    }
    lastJobId = job.id;
    const pctDone = job.total ? Math.round((job.done * 100) / job.total) : null;
    dock.hidden = false;
    dock.innerHTML = `
        <span class="spinner" aria-hidden="true"></span>
        <strong>${esc(job.label)}</strong>
        <span class="muted">${esc(job.message || '')}${job.total ? ` · ${job.done}/${job.total}` : ''}</span>
        ${pctDone !== null ? `<span class="dock-bar"><i style="width:${pctDone}%"></i></span>` : ''}`;
    schedulePoll(1500);
}

async function jobFinished(id) {
    const { recent } = await api('/api/jobs');
    const run = recent.find(r => r.id === id);
    if (run) toast(run.status === 'success' ? `Done: ${run.summary}` : `Failed: ${run.error || run.status}`, 6000);
    // Let the current page refresh its numbers
    if (active?.onJobDone) active.onJobDone(run);
}

function schedulePoll(ms) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
        try {
            const { current } = await api('/api/jobs');
            renderDock(current);
        } catch { schedulePoll(5000); }
    }, ms);
}

export async function startJob(type) {
    try {
        const job = await api('/api/jobs', { type });
        renderDock(job);
        return job;
    } catch (e) {
        toast(e.message, 5000);
        return null;
    }
}

window.addEventListener('hashchange', route);
route();
