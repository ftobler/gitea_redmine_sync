"""Application factory and entry point."""

import logging
import threading
import time

from flask import Flask
from waitress import serve

from .cache import RepoCache
from .config import RECONCILE_INTERVAL
from .webhook import bp, webhook_init
from .worker import JobQueue, worker_thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def create_app(cache: RepoCache, queue: JobQueue) -> Flask:
    app = Flask(__name__)
    webhook_init(cache, queue)
    app.register_blueprint(bp)
    app.extensions["cache"] = cache
    app.extensions["queue"] = queue
    return app


def reconcile_loop_thread(queue) -> None:
    while True:
        time.sleep(RECONCILE_INTERVAL)
        queue.enqueue_all_repos()


def main() -> None:
    cache = RepoCache()
    queue = JobQueue(cache)
    app = create_app(cache, queue)

    threading.Thread(target=worker_thread, args=(queue, cache), daemon=True, name="sync-worker").start()
    threading.Thread(target=reconcile_loop_thread, args=(queue,), daemon=True, name="reconcile").start()

    log.info("Startup: enqueueing all repos for initial sync")
    queue.enqueue_all_repos(force_cache=True)

    serve(app, host="0.0.0.0", port=8000, threads=4)


if __name__ == "__main__":
    main()
