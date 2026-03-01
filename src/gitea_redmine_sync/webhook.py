"""Flask blueprint for Gitea webhook and admin endpoints."""

import hashlib
import hmac
import json
import logging
from typing import Optional

from flask import Blueprint, Response, request

from .cache import RepoCache
from .config import GITEA_WEBHOOK_SECRET
from .jobs import JobQueue

log = logging.getLogger(__name__)

bp = Blueprint("webhook", __name__)

# These are set by create_app() before the blueprint is used.
_cache: RepoCache
_queue: JobQueue


def webhook_init(cache: RepoCache, queue: JobQueue) -> None:
    global _cache, _queue
    _cache = cache
    _queue = queue


def _verify_signature(body: bytes, header: Optional[str]) -> bool:
    if not GITEA_WEBHOOK_SECRET:
        return True
    if not header:
        return False
    expected = "sha256=" + hmac.new(
        GITEA_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)


@bp.post("/hooks/gitea")
def gitea_webhook() -> Response:
    body = request.get_data()

    if not _verify_signature(body, request.headers.get("X-Gitea-Signature")):
        return Response(status=401)

    if request.headers.get("X-Gitea-Event") != "push":
        return Response(status=202)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(status=400)

    clone_url = payload.get("repository", {}).get("clone_url", "").rstrip("/")
    if not clone_url:
        return Response(status=400)

    by_clone_url, _ = _cache.get()
    record = by_clone_url.get(clone_url)

    if record is None:
        by_clone_url, _ = _cache.get(force=True)
        record = by_clone_url.get(clone_url)

    if record is None:
        log.info("Ignoring push for repo not in Redmine: %s", clone_url)
        return Response(status=202)

    _queue.enqueue_sync(record)
    return Response(status=202)


@bp.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "queued": len(_queue.pending)}


@bp.post("/admin/reconcile")
def admin_reconcile() -> Response:
    _queue.enqueue_all_repos(force_cache=True)
    return Response(status=202)
