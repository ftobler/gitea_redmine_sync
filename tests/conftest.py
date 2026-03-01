"""Shared fixtures for pytest."""

import os
import pytest

# Set required env vars before any module-level imports touch them.
os.environ.setdefault("REDMINE_URL", "http://redmine.test")
os.environ.setdefault("REDMINE_API_KEY", "test-key")
os.environ.setdefault("GITEA_WEBHOOK_SECRET", "")

from gitea_redmine_sync.app import create_app  # noqa: E402
from gitea_redmine_sync.cache import RepoCache  # noqa: E402
from gitea_redmine_sync.jobs import JobQueue    # noqa: E402


@pytest.fixture()
def app():
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def cache():
    return RepoCache()


@pytest.fixture()
def jobs(cache):
    return JobQueue(cache)


@pytest.fixture()
def sample_record():
    return {
        "clone_url": "http://gitea.test/owner/repo.git",
        "fs_path": "/repos/owner/repo.git",
        "project": "owner",
    }
