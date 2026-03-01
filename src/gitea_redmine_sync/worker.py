"""Job queue and background worker thread."""

import logging
import queue

from .cache import RepoCache, RepoRecord
from .git_ops import run_cleanup, sync_repo

log = logging.getLogger(__name__)


# job type
JobTuple = tuple[str, RepoRecord | None]


class JobQueue:
    def __init__(self, cache: RepoCache) -> None:
        self._cache = cache
        self._queue: queue.Queue[JobTuple] = queue.Queue()

    def enqueue_sync(self, record: RepoRecord) -> None:
        self._queue.put(("sync", record))

    def enqueue_cleanup(self) -> None:
        self._queue.put(("cleanup", None))

    def enqueue_all_repos(self, force_cache: bool = False) -> None:
        """Fetch Redmine repo list and enqueue a sync job per repo, then a cleanup."""
        try:
            _, by_path = self._cache.get(force=force_cache)
        except Exception as exc:
            log.error("Failed to fetch Redmine repo list for bulk enqueue: %s", exc)
            return

        for record in by_path.values():
            self.enqueue_sync(record)
        self.enqueue_cleanup()
        log.info("Enqueued %d sync job(s) + cleanup", len(by_path))

    def get(self) -> JobTuple:
        return self._queue.get()

    @property
    def size(self) -> int:
        return self._queue.qsize()


def worker_thread(jobs: JobQueue, cache: RepoCache) -> None:
    log.info("Worker started")
    while True:
        job_type, payload = jobs.get()
        try:
            if job_type == "sync" and payload is not None:
                sync_repo(payload)
            elif job_type == "cleanup":
                run_cleanup(cache)
        except Exception as exc:
            log.error("Job [%s] failed: %s", job_type, exc)
