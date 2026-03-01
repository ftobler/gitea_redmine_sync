"""Tests for worker_thread — runs the actual worker in a thread and verifies dispatch."""

import threading
from unittest.mock import MagicMock, patch

from gitea_redmine_sync.worker import JobQueue, worker_thread

TIMEOUT = 2  # seconds to wait for a job to be processed


def _start_worker(jobs, cache):
    t = threading.Thread(target=worker_thread, args=(jobs, cache), daemon=True)
    t.start()
    return t


def _make_event_side_effect(event):
    """Return a side_effect function that sets event when called."""
    def side_effect(*args, **kwargs):
        event.set()
    return side_effect


# ---------------------------------------------------------------------------
# sync job dispatch
# ---------------------------------------------------------------------------

def test_worker_calls_sync_repo_for_sync_job(sample_record):
    cache = MagicMock()
    jobs = JobQueue(cache)
    done = threading.Event()

    with patch("gitea_redmine_sync.worker.sync_repo", side_effect=_make_event_side_effect(done)) as mock_sync:
        _start_worker(jobs, cache)
        jobs.enqueue_sync(sample_record)
        assert done.wait(TIMEOUT), "worker did not process sync job in time"
        mock_sync.assert_called_once_with(sample_record)


# ---------------------------------------------------------------------------
# cleanup job dispatch
# ---------------------------------------------------------------------------

def test_worker_calls_run_cleanup_for_cleanup_job():
    cache = MagicMock()
    jobs = JobQueue(cache)
    done = threading.Event()

    with patch("gitea_redmine_sync.worker.run_cleanup", side_effect=_make_event_side_effect(done)) as mock_cleanup:
        _start_worker(jobs, cache)
        jobs.enqueue_cleanup()
        assert done.wait(TIMEOUT), "worker did not process cleanup job in time"
        mock_cleanup.assert_called_once_with(cache)


# ---------------------------------------------------------------------------
# error resilience
# ---------------------------------------------------------------------------

def test_worker_continues_after_sync_exception(sample_record):
    """An exception in sync_repo must not crash the worker loop."""
    cache = MagicMock()
    jobs = JobQueue(cache)
    second_job_done = threading.Event()
    call_count = [0]

    def sync_side_effect(record):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("transient git failure")
        second_job_done.set()

    with patch("gitea_redmine_sync.worker.sync_repo", side_effect=sync_side_effect):
        _start_worker(jobs, cache)
        jobs.enqueue_sync(sample_record)
        jobs.enqueue_sync(sample_record)
        assert second_job_done.wait(TIMEOUT), "worker stopped after exception"
        assert call_count[0] == 2


def test_worker_continues_after_cleanup_exception(sample_record):
    """An exception in run_cleanup must not crash the worker loop."""
    cache = MagicMock()
    jobs = JobQueue(cache)
    sync_done = threading.Event()
    call_count = [0]

    def cleanup_side_effect(c):
        call_count[0] += 1
        raise RuntimeError("cleanup failed")

    with patch("gitea_redmine_sync.worker.run_cleanup", side_effect=cleanup_side_effect):
        with patch("gitea_redmine_sync.worker.sync_repo", side_effect=_make_event_side_effect(sync_done)):
            _start_worker(jobs, cache)
            jobs.enqueue_cleanup()
            jobs.enqueue_sync(sample_record)
            assert sync_done.wait(TIMEOUT), "worker stopped after cleanup exception"
            assert call_count[0] == 1


# ---------------------------------------------------------------------------
# ordering
# ---------------------------------------------------------------------------

def test_worker_processes_jobs_in_fifo_order(sample_record):
    cache = MagicMock()
    jobs = JobQueue(cache)
    processed = []
    all_done = threading.Event()

    record_a = {**sample_record, "fs_path": "/repos/a.git"}
    record_b = {**sample_record, "fs_path": "/repos/b.git"}

    def sync_side_effect(record):
        processed.append(record["fs_path"])
        if len(processed) == 2:
            all_done.set()

    with patch("gitea_redmine_sync.worker.sync_repo", side_effect=sync_side_effect):
        _start_worker(jobs, cache)
        jobs.enqueue_sync(record_a)
        jobs.enqueue_sync(record_b)
        assert all_done.wait(TIMEOUT), "worker did not process both jobs in time"
        assert processed == ["/repos/a.git", "/repos/b.git"]
