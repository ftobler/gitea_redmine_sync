"""
End-to-end tests for gitea-redmine-sync.

Test order matters for the sync tests:
  test_initial_sync_via_webhook  →  test_sync_fetches_new_commit

Both depend on the session-scoped `bootstrap` fixture (autouse) having seeded
Redmine and Gitea before any test runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from conftest import (
    GITEA_ADMIN_PASS,
    GITEA_ADMIN_USER,
    GITEA_CLONE_URL,
    GITEA_REPO,
    GITEA_URL,
    REDMINE_API_KEY,
    REDMINE_PROJECT_ID,
    REDMINE_URL,
    REPO_FS_PATH,
    SYNC_URL,
)


# ── git helpers ───────────────────────────────────────────────────────────────

def _git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _authed_clone_url() -> str:
    """Inject basic-auth credentials into the Gitea clone URL for push."""
    return GITEA_CLONE_URL.replace(
        "http://", f"http://{GITEA_ADMIN_USER}:{GITEA_ADMIN_PASS}@"
    )


def _push_commit() -> str:
    """Clone the Gitea repo, add a file, push, and return the new commit SHA."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _git("clone", _authed_clone_url(), tmpdir)
        _git("config", "user.email", "e2e@test.local", cwd=tmpdir)
        _git("config", "user.name", "E2E Test", cwd=tmpdir)
        Path(tmpdir, "e2e-marker.txt").write_text(f"timestamp={time.time()}\n")
        _git("add", "e2e-marker.txt", cwd=tmpdir)
        _git("commit", "-m", "e2e: add marker file", cwd=tmpdir)
        _git("push", "origin", "main", cwd=tmpdir)
        return _git("rev-parse", "HEAD", cwd=tmpdir).stdout.strip()


def _bare_head_sha(fs_path: str) -> str | None:
    """Return HEAD SHA of a bare repo, or None if it doesn't exist / fails."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=fs_path,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, OSError):
        return None


# ── webhook helper ────────────────────────────────────────────────────────────

def _post_push_webhook(clone_url: str = GITEA_CLONE_URL) -> httpx.Response:
    payload = json.dumps({"repository": {"clone_url": clone_url}})
    return httpx.post(
        f"{SYNC_URL}/hooks/gitea",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Gitea-Event": "push",
        },
        timeout=10,
    )


# ── tests ─────────────────────────────────────────────────────────────────────

class TestServiceHealth:
    def test_sync_static_page(self):
        """Sync service serves its info page."""
        r = httpx.get(f"{SYNC_URL}/", timeout=10)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Gitea" in r.text

    def test_gitea_healthz(self):
        r = httpx.get(f"{GITEA_URL}/api/healthz", timeout=10)
        assert r.status_code == 200

    def test_redmine_responds(self):
        r = httpx.get(f"{REDMINE_URL}/", timeout=10)
        assert r.status_code == 200


class TestRedmineApi:
    def test_repositories_json_structure(self, bootstrap):
        """GET /repositories.json returns the bootstrapped project and repo."""
        r = httpx.get(
            f"{REDMINE_URL}/repositories.json",
            headers={"X-Redmine-API-Key": REDMINE_API_KEY},
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert "projects" in data

        projects_by_name = {p["name"]: p for p in data["projects"]}
        assert "E2E Project" in projects_by_name, (
            f"bootstrapped project missing; got {list(projects_by_name)}"
        )
        repos = projects_by_name["E2E Project"]["repositories"]
        assert repos, "project has no repositories"

        repo = repos[0]
        assert repo["path"] == REPO_FS_PATH, (
            f"unexpected path: {repo['path']!r}"
        )

    def test_repositories_json_exposes_clone_url(self, bootstrap):
        """
        The patched controller must emit url=<Gitea clone URL> so the sync
        service can build its by_clone_url index (bridging the design gap).
        """
        r = httpx.get(
            f"{REDMINE_URL}/repositories.json",
            headers={"X-Redmine-API-Key": REDMINE_API_KEY},
            timeout=10,
        )
        data = r.json()
        projects_by_name = {p["name"]: p for p in data["projects"]}
        repo = projects_by_name["E2E Project"]["repositories"][0]
        assert repo.get("url") == GITEA_CLONE_URL, (
            f"url field missing or wrong: {repo.get('url')!r}. "
            "Check Dockerfile.redmine sed patch."
        )

    def test_type_filter(self, bootstrap):
        """?type=git returns only Git repos."""
        r = httpx.get(
            f"{REDMINE_URL}/repositories.json?type=git",
            headers={"X-Redmine-API-Key": REDMINE_API_KEY},
            timeout=10,
        )
        assert r.status_code == 200
        for project in r.json()["projects"]:
            for repo in project["repositories"]:
                assert "Git" in repo["type"], repo["type"]

    def test_requires_api_key(self):
        """Requests without an API key are rejected."""
        r = httpx.get(f"{REDMINE_URL}/repositories.json", timeout=10)
        assert r.status_code in (401, 403)


class TestWebhookEndpoint:
    def test_non_push_event_is_ignored(self):
        """Events other than 'push' return 202 without triggering a sync."""
        r = httpx.post(
            f"{SYNC_URL}/hooks/gitea",
            content=json.dumps({"action": "opened"}),
            headers={
                "Content-Type": "application/json",
                "X-Gitea-Event": "issues",
            },
            timeout=10,
        )
        assert r.status_code == 202

    def test_unknown_repo_returns_202(self):
        """Push for a repo not in Redmine is accepted (202) but not queued."""
        r = _post_push_webhook("http://gitea:3000/nobody/does-not-exist.git")
        assert r.status_code == 202

    def test_missing_clone_url_returns_400(self):
        """Malformed payload (no clone_url) returns 400."""
        r = httpx.post(
            f"{SYNC_URL}/hooks/gitea",
            content=json.dumps({"repository": {}}),
            headers={
                "Content-Type": "application/json",
                "X-Gitea-Event": "push",
            },
            timeout=10,
        )
        assert r.status_code == 400

    def test_invalid_json_returns_400(self):
        r = httpx.post(
            f"{SYNC_URL}/hooks/gitea",
            content=b"not json",
            headers={
                "Content-Type": "application/json",
                "X-Gitea-Event": "push",
            },
            timeout=10,
        )
        assert r.status_code == 400


class TestFullSyncFlow:
    """
    These tests verify the complete webhook → worker → git clone/fetch pipeline.

    The sync service must have the repo in its cache (populated after bootstrap
    + 12 s sleep) for the webhook lookup to succeed.
    """

    def test_initial_sync_via_webhook(self, bootstrap):
        """
        POST a push webhook for the known repo → sync worker clones it →
        bare repo appears at the expected filesystem path.
        """
        r = _post_push_webhook()
        assert r.status_code == 202, f"unexpected status: {r.status_code}"

        # Poll for up to 30 s for the worker to finish the git clone.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if _bare_head_sha(REPO_FS_PATH) is not None:
                break
            time.sleep(1)

        sha = _bare_head_sha(REPO_FS_PATH)
        assert sha is not None, (
            f"bare repo not found at {REPO_FS_PATH} after 30 s. "
            "Check sync-service logs for git errors."
        )
        print(f"[sync] bare repo cloned, HEAD={sha}")

    def test_sync_fetches_new_commit(self, bootstrap):
        """
        Push a new commit to Gitea, trigger the webhook, and verify the bare
        repo's HEAD advances to the new commit.
        """
        # Ensure the initial clone has happened (run tests in order).
        initial_sha = _bare_head_sha(REPO_FS_PATH)
        assert initial_sha is not None, (
            "bare repo missing — run the full test suite (test_initial_sync_via_webhook first)"
        )

        new_sha = _push_commit()
        print(f"[test] pushed new commit: {new_sha}")

        r = _post_push_webhook()
        assert r.status_code == 202

        # Poll for the worker to fetch the new commit.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if _bare_head_sha(REPO_FS_PATH) == new_sha:
                break
            time.sleep(1)

        current_sha = _bare_head_sha(REPO_FS_PATH)
        assert current_sha == new_sha, (
            f"bare repo HEAD is {current_sha!r}, expected {new_sha!r} after fetch. "
            "The sync worker may not have processed the job yet."
        )
        print(f"[sync] bare repo updated to HEAD={current_sha}")
