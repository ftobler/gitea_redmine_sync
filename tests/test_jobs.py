"""Tests for JobQueue — verifies both queue size and the content of enqueued jobs."""

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


def test_enqueue_sync_produces_sync_tuple(sample_record):
    jobs, _ = _make_jobs()
    jobs.enqueue_sync(sample_record)
    job_type, payload = jobs.get()
    assert job_type == "sync"
    assert payload == sample_record


def test_enqueue_cleanup_produces_cleanup_tuple():
    jobs, _ = _make_jobs()
    jobs.enqueue_cleanup()
    job_type, payload = jobs.get()
    assert job_type == "cleanup"
    assert payload is None


def test_enqueue_all_repos_produces_sync_per_repo_then_cleanup():
    jobs, _ = _make_jobs()
    jobs.enqueue_all_repos()

    seen_paths = set()
    for _ in range(2):
        job_type, payload = jobs.get()
        assert job_type == "sync"
        assert payload is not None
        seen_paths.add(payload["fs_path"])

    assert seen_paths == {"/repos/a.git", "/repos/b.git"}

    job_type, payload = jobs.get()
    assert job_type == "cleanup"
    assert payload is None

    assert jobs.size == 0


def test_enqueue_all_repos_handles_cache_error():
    cache = MagicMock()
    cache.get.side_effect = RuntimeError("network error")
    jobs = JobQueue(cache)
    jobs.enqueue_all_repos()  # must not raise
    assert jobs.size == 0


def test_jobs_are_fifo(sample_record):
    jobs, _ = _make_jobs()
    record_a = {**sample_record, "fs_path": "/repos/a.git"}
    record_b = {**sample_record, "fs_path": "/repos/b.git"}
    jobs.enqueue_sync(record_a)
    jobs.enqueue_sync(record_b)
    _, first = jobs.get()
    _, second = jobs.get()
    assert first["fs_path"] == "/repos/a.git"
    assert second["fs_path"] == "/repos/b.git"
