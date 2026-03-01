"""Job queue with deduplication for sync and cleanup operations."""

import logging
import queue
import threading

from .cache import RepoCache, RepoRecord

log = logging.getLogger(__name__)

_CLEANUP_KEY = "__cleanup__"

JobTuple = tuple[str, RepoRecord | None]


class JobQueue:
    def __init__(self, cache: RepoCache) -> None:
        self._cache = cache
        self._q: queue.Queue[JobTuple] = queue.Queue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def enqueue_sync(self, record: RepoRecord) -> bool:
        """Enqueue a sync job. Returns False if already pending (duplicate dropped)."""
        key = record["clone_url"]
        with self._lock:
            if key in self._pending:
                log.debug("Dedup: %s already queued", key)
                return False
            self._pending.add(key)
        self._q.put(("sync", record))
        return True

    def enqueue_cleanup(self) -> None:
        with self._lock:
            if _CLEANUP_KEY in self._pending:
                log.debug("Dedup: cleanup already queued")
                return
            self._pending.add(_CLEANUP_KEY)
        self._q.put(("cleanup", None))

    def enqueue_all_repos(self, force_cache: bool = False) -> None:
        """Fetch Redmine repo list and enqueue a sync job per repo, then a cleanup."""
        try:
            _, by_path = self._cache.get(force=force_cache)
        except Exception as exc:
            log.error("Failed to fetch Redmine repo list for bulk enqueue: %s", exc)
            return

        enqueued = sum(1 for record in by_path.values() if self.enqueue_sync(record))
        self.enqueue_cleanup()
        log.info("Enqueued %d sync job(s) + cleanup", enqueued)

    def get(self) -> JobTuple:
        return self._q.get()

    def task_done(self, key: str) -> None:
        with self._lock:
            self._pending.discard(key)
        self._q.task_done()

    @property
    def pending(self) -> set[str]:
        with self._lock:
            return set(self._pending)
