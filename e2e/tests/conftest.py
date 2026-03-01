"""
Session-scoped bootstrap for E2E tests.

Flow
----
1. Wait for Redmine, Gitea and the sync service to be healthy.
2. Create a Gitea repo (auto-initialised with an initial commit).
3. Seed Redmine:
   - enable REST API + inject admin API key via SQL
   - create a project via the REST API
   - insert a repository row with:
       url      = bare-repo filesystem path  (what sync writes to)
       root_url = Gitea HTTP clone URL       (what sync clones from)
   The Dockerfile.redmine patches the plugin controller to expose root_url
   as the "url" field in /repositories.json, bridging the design gap.
4. Sleep 10 s so the sync service cache (CACHE_TTL=5 s) picks up the new repo.
"""

from __future__ import annotations

import os
import time

import httpx
import pymysql
import pytest

# ── service URLs and credentials (injected by docker-compose) ─────────────────
REDMINE_URL = os.environ["REDMINE_URL"]
REDMINE_API_KEY = os.environ["REDMINE_API_KEY"]

GITEA_URL = os.environ["GITEA_URL"]
GITEA_ADMIN_USER = os.environ["GITEA_ADMIN_USER"]
GITEA_ADMIN_PASS = os.environ["GITEA_ADMIN_PASS"]

SYNC_URL = os.environ["SYNC_URL"]

_DB = dict(
    host=os.environ["DB_HOST"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    db=os.environ["DB_NAME"],
    connect_timeout=10,
)

# ── well-known test constants ─────────────────────────────────────────────────
GITEA_REPO = "testrepo"
GITEA_CLONE_URL = f"{GITEA_URL}/{GITEA_ADMIN_USER}/{GITEA_REPO}.git"

REDMINE_PROJECT_NAME = "E2E Project"
REDMINE_PROJECT_ID = "e2e-project"

# Where the sync service will clone the bare repo (matches the Redmine DB row).
REPO_FS_PATH = f"/repos/{REDMINE_PROJECT_ID}/{GITEA_REPO}.git"


# ── internal helpers ──────────────────────────────────────────────────────────

def _wait(url: str, label: str, timeout: int = 150, interval: int = 3) -> None:
    """Poll *url* until it returns a non-5xx status or *timeout* seconds pass."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code < 500:
                print(f"[wait] {label} ready ({r.status_code})")
                return
        except Exception as exc:
            last_exc = exc
        time.sleep(interval)
    raise RuntimeError(f"{label} not ready after {timeout}s ({url}): {last_exc}")


def _sql(query: str) -> None:
    conn = pymysql.connect(**_DB)
    with conn:
        with conn.cursor() as cur:
            cur.execute(query)
        conn.commit()


def _sql_val(query: str):
    conn = pymysql.connect(**_DB)
    with conn:
        with conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
    return row[0] if row else None


def _bootstrap_redmine() -> None:
    # Allow admin to use the API without a password change.
    _sql("UPDATE users SET must_change_passwd = 0 WHERE login = 'admin'")

    # Enable REST API.
    _sql(
        "INSERT INTO settings (name, value, updated_on) "
        "VALUES ('rest_api_enabled', '1', NOW()) "
        "ON DUPLICATE KEY UPDATE value = '1'"
    )

    # Insert admin API key (idempotent).
    if not _sql_val(
        f"SELECT COUNT(*) FROM tokens "
        f"WHERE user_id = 1 AND action = 'api' AND value = '{REDMINE_API_KEY}'"
    ):
        _sql(
            f"INSERT INTO tokens (user_id, action, value, created_on, updated_on) "
            f"VALUES (1, 'api', '{REDMINE_API_KEY}', NOW(), NOW())"
        )

    # Create Redmine project via REST API (422 = already exists, that's fine).
    with httpx.Client() as client:
        r = client.post(
            f"{REDMINE_URL}/projects.json",
            headers={
                "X-Redmine-API-Key": REDMINE_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "project": {
                    "name": REDMINE_PROJECT_NAME,
                    "identifier": REDMINE_PROJECT_ID,
                    "is_public": True,
                }
            },
        )
        if r.status_code not in (201, 422):
            raise RuntimeError(f"create redmine project: {r.status_code} {r.text}")

    project_id = _sql_val(
        f"SELECT id FROM projects WHERE identifier = '{REDMINE_PROJECT_ID}'"
    )
    assert project_id, "Redmine project not found after creation"

    # Insert repository row (idempotent).
    # url      → bare repo fs path (written by the sync service)
    # root_url → Gitea clone URL   (the plugin controller exposes this as "url"
    #            in the JSON response after our Dockerfile.redmine patch)
    if not _sql_val(
        f"SELECT COUNT(*) FROM repositories WHERE project_id = {project_id}"
    ):
        _sql(
            f"INSERT INTO repositories "
            f"(project_id, url, root_url, type, identifier, is_default, created_on) "
            f"VALUES ({project_id}, '{REPO_FS_PATH}', '{GITEA_CLONE_URL}', "
            f"'Repository::Git', 'main', 1, NOW())"
        )
    print("[bootstrap] Redmine seeded")


def _bootstrap_gitea() -> str:
    """Create the test repo (if absent) and return a fresh API token string.

    The admin user is created by the gitea-init container before this runs.
    """
    with httpx.Client(auth=(GITEA_ADMIN_USER, GITEA_ADMIN_PASS)) as client:
        # Rotate the test token so we always capture its plaintext value.
        client.delete(
            f"{GITEA_URL}/api/v1/users/{GITEA_ADMIN_USER}/tokens/e2e-token"
        )
        # Gitea 1.21+ requires explicit scopes on token creation.
        r = client.post(
            f"{GITEA_URL}/api/v1/users/{GITEA_ADMIN_USER}/tokens",
            json={"name": "e2e-token", "scopes": ["write:repository", "write:user", "read:user"]},
        )
        r.raise_for_status()
        token: str = r.json()["sha1"]

        # Create repo with an initial commit so git clone works immediately.
        r = client.post(
            f"{GITEA_URL}/api/v1/user/repos",
            json={
                "name": GITEA_REPO,
                "private": False,
                "auto_init": True,
                "default_branch": "main",
            },
        )
        if r.status_code not in (201, 409):   # 409 = already exists
            raise RuntimeError(f"create gitea repo: {r.status_code} {r.text}")

    print("[bootstrap] Gitea seeded")
    return token


# ── session fixture ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def bootstrap() -> dict:
    """Wait for all services, seed data, and let the sync cache warm up."""
    _wait(f"{REDMINE_URL}/", "Redmine")
    _wait(f"{GITEA_URL}/api/healthz", "Gitea")
    _wait(f"{SYNC_URL}/", "Sync")

    token = _bootstrap_gitea()
    _bootstrap_redmine()

    # The sync service cache TTL is 5 s.  Sleep 2× so the next fetch picks up
    # the repository we just inserted into Redmine.
    print("[bootstrap] waiting 12 s for sync-service cache to refresh…")
    time.sleep(12)

    return {
        "gitea_token": token,
        "clone_url": GITEA_CLONE_URL,
        "repo_fs_path": REPO_FS_PATH,
    }


@pytest.fixture(scope="session")
def gitea_token(bootstrap) -> str:
    return bootstrap["gitea_token"]
