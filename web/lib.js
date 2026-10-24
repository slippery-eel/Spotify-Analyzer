// Shared helpers for all views.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export async function api(path, body) {
    const opts = body !== undefined
        ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
        : {};
    const res = await fetch(path, opts);
    if (!res.ok) {
        let msg = `${res.status}`;
        try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
        throw new Error(msg);
    }
    return res.json();
}

let toastTimer;
export function toast(msg, ms = 2800) {
    const el = $('#toast');
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, ms);
}

export function timeAgo(iso) {
    if (!iso) return 'never';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return `${Math.floor(s / 86400)} d ago`;
}

export function fmtDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export const pct = (n, total) => total ? Math.round((n * 100) / total) : 0;

// Simple modal: returns the dialog element; caller wires its buttons.
export function openModal(html) {
    const root = $('#modal-root');
    root.innerHTML = `<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true">${html}</div></div>`;
    root.hidden = false;
    const close = () => { root.hidden = true; root.innerHTML = ''; };
    root.querySelector('.modal-backdrop').addEventListener('click', (e) => { if (e.target.classList.contains('modal-backdrop')) close(); });
    return { el: root.querySelector('.modal'), close };
}

// Theme-aware colors for Chart.js, read from CSS tokens.
export function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
