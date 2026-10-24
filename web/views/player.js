// Song players for review cards, using Spotify's iFrame API so the page can seek within a song:
// a clickable progress bar, -15s / +15s / jump-to-middle buttons, and only one song playing at a time.
// Full songs play when you're logged in to Spotify in this browser; otherwise Spotify gives 30s previews.
// If the API script can't load, cards fall back to the plain embed (play/pause only).
import { esc } from '../lib.js';

const API_URL = 'https://open.spotify.com/embed/iframe-api/v1';
const SKIP = 15;  // seconds
const players = new Map();  // track_id -> { controller, el, pos, dur, paused, started }
let apiPromise = null;
let active = null;          // track_id currently playing

function loadApi() {
    if (!apiPromise) {
        apiPromise = new Promise((resolve, reject) => {
            window.onSpotifyIframeApiReady = resolve;
            const s = document.createElement('script');
            s.src = API_URL;
            s.async = true;
            s.onerror = () => reject(new Error('Spotify player API unavailable'));
            document.head.appendChild(s);
            setTimeout(() => reject(new Error('Spotify player API timed out')), 10000);
        });
    }
    return apiPromise;
}

const fmt = (ms) => {
    const s = Math.max(0, Math.round((ms || 0) / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

export function playerHtml(trackId, name) {
    return `
        <div class="player" data-track="${trackId}">
            <div class="player-embed"><div></div></div>
            <div class="player-controls">
                <button class="pc" data-pc="back" title="Back ${SKIP}s (←)" aria-label="Back ${SKIP} seconds">−${SKIP}</button>
                <button class="pc pc-play" data-pc="toggle" title="Play / pause (Space)" aria-label="Play or pause ${esc(name)}">▶</button>
                <button class="pc" data-pc="fwd" title="Forward ${SKIP}s (→)" aria-label="Forward ${SKIP} seconds">+${SKIP}</button>
                <button class="pc" data-pc="mid" title="Jump to the middle (m)" aria-label="Jump to the middle">½</button>
                <div class="pc-bar" role="slider" aria-label="Seek" tabindex="-1"><i></i></div>
                <span class="pc-time muted">0:00</span>
            </div>
        </div>`;
}

// Create controllers for any players in `root` that don't have one yet.
export async function mountPlayers(root) {
    const pending = [...root.querySelectorAll('.player')].filter(el => !players.has(el.dataset.track));
    if (!pending.length) return;
    let api;
    try {
        api = await loadApi();
    } catch {
        pending.forEach(fallback);
        return;
    }
    for (const el of pending) {
        const id = el.dataset.track;
        if (players.has(id) || !el.isConnected) continue;
        const p = { controller: null, el, pos: 0, dur: 0, paused: true, started: false };
        players.set(id, p);
        api.createController(el.querySelector('.player-embed > div'),
            { uri: `spotify:track:${id}`, width: '100%', height: 80 },
            (controller) => {
                p.controller = controller;
                controller.addListener('playback_update', (e) => update(id, e.data));
            });
    }
}

function fallback(el) {
    // Plain embed without seeking, as before
    el.querySelector('.player-embed').innerHTML = `<iframe loading="lazy" src="https://open.spotify.com/embed/track/${el.dataset.track}?theme=0"
        allow="encrypted-media" title="Spotify player"></iframe>`;
    el.querySelector('.player-controls').hidden = true;
}

function update(id, d) {
    const p = players.get(id);
    if (!p) return;
    p.pos = d.position;
    p.dur = d.duration;
    // At the end the embed stops accepting seeks; treat it as stopped so the next action restarts it
    const ended = d.duration > 0 && d.position >= d.duration - 400;
    p.paused = d.isPaused || ended;
    if (ended) p.started = false;
    if (!p.paused) {
        p.started = true;
        if (active && active !== id) players.get(active)?.controller?.pause();  // one song at a time
        active = id;
    }
    const el = p.el;
    el.querySelector('.pc-bar i').style.width = `${d.duration ? (d.position * 100) / d.duration : 0}%`;
    el.querySelector('.pc-time').textContent = `${fmt(d.position)} / ${fmt(d.duration)}`;
    el.querySelector('.pc-play').textContent = p.paused ? '▶' : '❚❚';
}

function seek(id, seconds) {
    const p = players.get(id);
    if (!p?.controller) return;
    const max = p.dur ? p.dur / 1000 - 1 : Infinity;
    const target = Math.max(1, Math.min(seconds, max));  // the embed ignores seeks under ~1s
    if (!p.started) {
        // Seeking only works once the track has started; start it, then jump
        p.controller.play();
        setTimeout(() => p.controller.seek(target), 700);
    } else {
        p.controller.seek(target);
        // Seeking while paused doesn't stick in the embed; seeking means "play from here" anyway
        if (p.paused) p.controller.resume();
    }
}

// action: 'toggle' | 'back' | 'fwd' | 'mid'
export function control(id, action) {
    const p = players.get(id);
    if (!p?.controller) return;
    const now = p.pos / 1000;
    if (action === 'toggle') {
        if (!p.started && p.pos > 0) seek(id, 0);   // finished: play again from the start
        else p.controller.togglePlay();
    }
    else if (action === 'back') seek(id, now - SKIP);
    else if (action === 'fwd') seek(id, now + SKIP);
    else if (action === 'mid') seek(id, p.dur ? p.dur / 2000 : 60);
}

// Click handling for controls inside `root` (call once per page mount).
export function bindPlayerClicks(root) {
    root.addEventListener('click', (e) => {
        const player = e.target.closest('.player');
        if (!player) return;
        const id = player.dataset.track;
        const btn = e.target.closest('[data-pc]');
        if (btn) return control(id, btn.dataset.pc);
        const bar = e.target.closest('.pc-bar');
        const p = players.get(id);
        if (bar && p) {
            const r = bar.getBoundingClientRect();
            const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
            seek(id, frac * ((p.dur || 30000) / 1000));
        }
    });
}

export function destroyPlayers() {
    for (const p of players.values()) {
        try { p.controller?.destroy(); } catch { /* already gone */ }
    }
    players.clear();
    active = null;
}
