"""Tests for JobQueue."""

from unittest.mock import MagicMock

from gitea_redmine_sync.worker import JobQueue


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


def test_enqueue_sync_adds_to_queue(sample_record):
    jobs, _ = _make_jobs()
    jobs.enqueue_sync(sample_record)
    assert jobs.size == 1


def test_enqueue_cleanup_adds_to_queue():
    jobs, _ = _make_jobs()
    jobs.enqueue_cleanup()
    assert jobs.size == 1


def test_enqueue_all_repos_adds_one_per_repo_plus_cleanup():
    jobs, _ = _make_jobs()
    jobs.enqueue_all_repos()
    assert jobs.size == 3  # 2 repos + 1 cleanup


def test_enqueue_all_repos_handles_cache_error():
    cache = MagicMock()
    cache.get.side_effect = RuntimeError("network error")
    jobs = JobQueue(cache)
    jobs.enqueue_all_repos()  # must not raise
    assert jobs.size == 0
