"""Background job runner for the app: one job at a time in a thread, history in job_runs.

Only one job runs at once so two writers never fight over the SQLite file (the
"database is locked" error seen when two syncs overlapped). Each job is a function
taking a progress(msg, done=None, total=None) callback and returning a summary string.
"""
import threading
import time
from datetime import datetime, timezone

import storage

_lock = threading.Lock()
_current = None          # dict for the running job, read by the API for live progress
_REGISTRY = {}           # job_type -> (label, fn)
PROGRESS_WRITE_INTERVAL = 2.0  # seconds between job_runs progress writes


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class JobBusy(Exception):
    pass


def register(job_type, label, fn):
    _REGISTRY[job_type] = (label, fn)


def job_types():
    return {k: label for k, (label, _) in _REGISTRY.items()}


def current():
    return dict(_current) if _current else None


def start(job_type, **params):
    """Start a job in the background. Raises JobBusy if one is already running."""
    global _current
    if job_type not in _REGISTRY:
        raise KeyError(job_type)
    with _lock:
        if _current:
            raise JobBusy(f"'{_current['label']}' is still running")
        label, fn = _REGISTRY[job_type]
        conn = storage.get_connection()
        cur = conn.execute('INSERT INTO job_runs (job_type, started_at, status, message) VALUES (?, ?, ?, ?)',
                           (job_type, _now(), 'running', 'Starting'))
        conn.commit()
        conn.close()
        _current = {'id': cur.lastrowid, 'type': job_type, 'label': label, 'status': 'running',
                    'message': 'Starting', 'done': None, 'total': None, 'started_at': _now()}
        job = dict(_current)
    threading.Thread(target=_run, args=(job, fn, params), daemon=True).start()
    return job


def _run(job, fn, params):
    global _current
    last_write = [0.0]

    def progress(msg, done=None, total=None):
        _current.update(message=msg, done=done, total=total)
        if time.time() - last_write[0] >= PROGRESS_WRITE_INTERVAL:
            last_write[0] = time.time()
            _update(job['id'], 'UPDATE job_runs SET message = ?, done = ?, total = ? WHERE id = ?',
                    (msg, done, total, job['id']))

    try:
        summary = fn(progress, **params)
        _update(job['id'], 'UPDATE job_runs SET status = ?, finished_at = ?, summary = ?, message = NULL WHERE id = ?',
                ('success', _now(), summary, job['id']))
    except Exception as e:  # report any failure in the UI instead of dying silently
        _update(job['id'], 'UPDATE job_runs SET status = ?, finished_at = ?, error = ? WHERE id = ?',
                ('error', _now(), f'{type(e).__name__}: {e}', job['id']))
    finally:
        with _lock:
            _current = None


def _update(job_id, sql, args):
    conn = storage.get_connection()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def recent(limit=20):
    conn = storage.get_connection()
    try:
        rows = conn.execute('SELECT id, job_type, started_at, finished_at, status, done, total, message, summary, error '
                            'FROM job_runs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    finally:
        conn.close()
    keys = ('id', 'type', 'started_at', 'finished_at', 'status', 'done', 'total', 'message', 'summary', 'error')
    return [dict(zip(keys, r)) for r in rows]


def last_success(job_type):
    conn = storage.get_connection()
    try:
        row = conn.execute("SELECT finished_at, summary FROM job_runs WHERE job_type = ? AND status = 'success' "
                           'ORDER BY id DESC LIMIT 1', (job_type,)).fetchone()
    finally:
        conn.close()
    return {'finished_at': row[0], 'summary': row[1]} if row else None


def mark_interrupted():
    """On server start: any 'running' row is left over from a previous process."""
    _update(None, "UPDATE job_runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'", (_now(),))
