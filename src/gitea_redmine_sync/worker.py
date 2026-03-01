"""Background worker thread that processes the job queue."""

import logging

from .cache import RepoCache
from .git_ops import run_cleanup, sync_repo
from .jobs import JobQueue

log = logging.getLogger(__name__)


def worker_thread(jobs: JobQueue, cache: RepoCache) -> None:
    log.info("Worker started")
    while True:
        job_type, payload = jobs.get()
        key = payload["clone_url"] if payload is not None else "__cleanup__"
        try:
            if job_type == "sync" and payload is not None:
                sync_repo(payload)
            elif job_type == "cleanup":
                run_cleanup(cache)
        except Exception as exc:
            log.error("Job [%s] %s failed: %s", job_type, key, exc)
        finally:
            jobs.task_done(key)
