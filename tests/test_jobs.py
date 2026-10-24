import threading

import pytest

import config
import jobs
import storage


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DB_FILE', str(tmp_path / 'j.db'))
    storage.init_db()
    monkeypatch.setattr(jobs, '_current', None)


def _wait_idle():
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=5)


def test_job_runs_and_records_success():
    jobs.register('demo', 'Demo', lambda progress, n=3: (progress('step', 1, n), f'did {n}')[1])
    jobs.start('demo', n=5)
    _wait_idle()
    run = jobs.recent()[0]
    assert run['status'] == 'success' and run['summary'] == 'did 5' and jobs.current() is None


def test_second_job_is_rejected_while_one_runs():
    gate = threading.Event()
    jobs.register('slow', 'Slow', lambda progress: (gate.wait(5), 'ok')[1])
    jobs.start('slow')
    with pytest.raises(jobs.JobBusy):
        jobs.start('slow')
    gate.set()
    _wait_idle()


def test_failure_is_recorded_not_raised():
    def boom(progress):
        raise ValueError('nope')
    jobs.register('boom', 'Boom', boom)
    jobs.start('boom')
    _wait_idle()
    run = jobs.recent()[0]
    assert run['status'] == 'error' and 'nope' in run['error']


def test_mark_interrupted():
    conn = storage.get_connection()
    conn.execute("INSERT INTO job_runs (job_type, started_at, status) VALUES ('x', 'now', 'running')")
    conn.commit(); conn.close()
    jobs.mark_interrupted()
    assert jobs.recent()[0]['status'] == 'interrupted'


def test_migration_rebuilds_old_playlists_table(tmp_path, monkeypatch):
    import sqlite3
    path = str(tmp_path / 'old.db')
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE tracks (track_id TEXT PRIMARY KEY, name TEXT NOT NULL, artists_json TEXT NOT NULL,
        album TEXT, release_date TEXT, duration_ms INTEGER, uri TEXT NOT NULL);
        CREATE TABLE playlists (playlist_id TEXT PRIMARY KEY, vibe_key TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
        snapshot_id TEXT, synced_at TEXT);
        CREATE TABLE playlist_items (playlist_id TEXT NOT NULL REFERENCES playlists(playlist_id),
        track_id TEXT NOT NULL REFERENCES tracks(track_id), added_at TEXT, PRIMARY KEY (playlist_id, track_id));
        INSERT INTO tracks VALUES ('t', 'n', '[]', NULL, NULL, 1, 'u');
        INSERT INTO playlists VALUES ('p', 'cozy', 'mega cozy playlist', 's', 'now');
        INSERT INTO playlist_items VALUES ('p', 't', 'now');""")
    c.commit(); c.close()
    monkeypatch.setattr(config, 'DB_FILE', path)
    storage.init_db()
    c = storage.get_connection()
    assert c.execute('SELECT vibe_key, is_owned FROM playlists').fetchone() == ('cozy', 1)
    c.execute("INSERT INTO playlists (playlist_id, name) VALUES ('p2', 'other')")  # vibe_key may be NULL now
    assert c.execute('SELECT COUNT(*) FROM playlist_items').fetchone()[0] == 1
    assert c.execute('PRAGMA foreign_key_check').fetchall() == []


def test_progress_does_not_deadlock_with_open_write_transaction():
    """Regression: a job holding a write transaction must be able to report progress."""
    def writer(progress):
        conn = storage.get_connection()
        conn.execute("INSERT INTO meta VALUES ('k', 'v')")   # open write transaction
        progress('working', 1, 2)
        conn.commit(); conn.close()
        return 'ok'
    jobs.register('writer', 'Writer', writer)
    jobs.start('writer')
    _wait_idle()
    assert jobs.recent()[0]['status'] == 'success'
