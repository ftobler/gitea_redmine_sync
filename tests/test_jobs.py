"""Tests for JobQueue."""

from unittest.mock import MagicMock, patch

import pytest

from gitea_redmine_sync.jobs import JobQueue


def _make_jobs():
    cache = MagicMock()
    cache.get.return_value = (
        {},
        {
            "/repos/a.git": {"clone_url": "http://gitea.test/a.git", "fs_path": "/repos/a.git", "project": "a"},
            "/repos/b.git": {"clone_url": "http://gitea.test/b.git", "fs_path": "/repos/b.git", "project": "b"},
        },
    )
    return JobQueue(cache), cache


def test_enqueue_sync_returns_true_first_time(sample_record):
    jobs, _ = _make_jobs()
    assert jobs.enqueue_sync(sample_record) is True


def test_enqueue_sync_deduplicates(sample_record):
    jobs, _ = _make_jobs()
    jobs.enqueue_sync(sample_record)
    assert jobs.enqueue_sync(sample_record) is False


def test_task_done_allows_reenqueue(sample_record):
    jobs, _ = _make_jobs()
    jobs.enqueue_sync(sample_record)
    jobs.task_done(sample_record["clone_url"])
    assert jobs.enqueue_sync(sample_record) is True


def test_enqueue_cleanup_deduplicates():
    jobs, _ = _make_jobs()
    jobs.enqueue_cleanup()
    jobs.enqueue_cleanup()
    pending = jobs.pending
    assert "__cleanup__" in pending
    assert sum(1 for k in pending if k == "__cleanup__") == 1


def test_enqueue_all_repos_enqueues_per_repo_and_cleanup():
    jobs, cache = _make_jobs()
    jobs.enqueue_all_repos()
    pending = jobs.pending
    assert "http://gitea.test/a.git" in pending
    assert "http://gitea.test/b.git" in pending
    assert "__cleanup__" in pending


def test_enqueue_all_repos_handles_cache_error():
    cache = MagicMock()
    cache.get.side_effect = RuntimeError("network error")
    jobs = JobQueue(cache)
    jobs.enqueue_all_repos()  # must not raise
    assert len(jobs.pending) == 0


def test_pending_returns_copy(sample_record):
    jobs, _ = _make_jobs()
    jobs.enqueue_sync(sample_record)
    p1 = jobs.pending
    p2 = jobs.pending
    assert p1 == p2
    assert p1 is not p2
