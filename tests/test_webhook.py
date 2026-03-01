"""Tests for Flask webhook endpoints."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch


from gitea_redmine_sync import webhook


SAMPLE_RECORD = {
    "clone_url": "http://gitea.test/owner/repo.git",
    "fs_path": "/repos/owner/repo.git",
    "project": "owner",
}

PUSH_PAYLOAD = {
    "repository": {"clone_url": "http://gitea.test/owner/repo.git"},
}


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health_returns_ok(client, app):
    queue: MagicMock = MagicMock()
    queue.size = 0
    app.extensions["queue"] = queue
    webhook._queue = queue

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True


# ---------------------------------------------------------------------------
# /hooks/gitea — signature verification
# ---------------------------------------------------------------------------

def test_webhook_rejects_invalid_signature(client):
    with patch.object(webhook, "GITEA_WEBHOOK_SECRET", "mysecret"):
        webhook.GITEA_WEBHOOK_SECRET  # noqa: B018 (just reference)
        wh_secret_orig = webhook.GITEA_WEBHOOK_SECRET

        body = json.dumps(PUSH_PAYLOAD).encode()
        resp = client.post(
            "/hooks/gitea",
            data=body,
            content_type="application/json",
            headers={"X-Gitea-Event": "push", "X-Gitea-Signature": "sha256=bad"},
        )
        assert resp.status_code == 401


def test_webhook_accepts_non_push_event(client):
    with patch("gitea_redmine_sync.webhook.GITEA_WEBHOOK_SECRET", ""):
        resp = client.post(
            "/hooks/gitea",
            data=b"{}",
            content_type="application/json",
            headers={"X-Gitea-Event": "create"},
        )
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# /hooks/gitea — push event
# ---------------------------------------------------------------------------

def test_webhook_enqueues_known_repo(client):
    body = json.dumps(PUSH_PAYLOAD).encode()

    mock_cache = MagicMock()
    mock_cache.get.return_value = (
        {"http://gitea.test/owner/repo.git": SAMPLE_RECORD},
        {},
    )
    mock_queue = MagicMock()

    webhook._cache = mock_cache
    webhook._queue = mock_queue

    with patch("gitea_redmine_sync.webhook.GITEA_WEBHOOK_SECRET", ""):
        resp = client.post(
            "/hooks/gitea",
            data=body,
            content_type="application/json",
            headers={"X-Gitea-Event": "push"},
        )

    assert resp.status_code == 202
    mock_queue.enqueue_sync.assert_called_once_with(SAMPLE_RECORD)


def test_webhook_ignores_unknown_repo(client):
    body = json.dumps(PUSH_PAYLOAD).encode()

    mock_cache = MagicMock()
    mock_cache.get.return_value = ({}, {})
    mock_jobs = MagicMock()

    webhook._cache = mock_cache
    webhook._queue = mock_jobs

    with patch("gitea_redmine_sync.webhook.GITEA_WEBHOOK_SECRET", ""):
        resp = client.post(
            "/hooks/gitea",
            data=body,
            content_type="application/json",
            headers={"X-Gitea-Event": "push"},
        )

    assert resp.status_code == 202
    mock_jobs.enqueue_sync.assert_not_called()


def test_webhook_returns_400_on_bad_json(client):
    with patch("gitea_redmine_sync.webhook.GITEA_WEBHOOK_SECRET", ""):
        resp = client.post(
            "/hooks/gitea",
            data=b"not-json",
            content_type="application/json",
            headers={"X-Gitea-Event": "push"},
        )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /admin/reconcile
# ---------------------------------------------------------------------------

def test_admin_reconcile_triggers_enqueue(client):
    mock_jobs = MagicMock()
    webhook._queue = mock_jobs

    resp = client.post("/admin/reconcile")
    assert resp.status_code == 202
    mock_jobs.enqueue_all_repos.assert_called_once_with(force_cache=True)
