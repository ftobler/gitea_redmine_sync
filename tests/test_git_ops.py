"""Tests for git_ops: sync_repo and run_cleanup."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from gitea_redmine_sync.git_ops import _git_command, run_cleanup, sync_repo


# ---------------------------------------------------------------------------
# _git helper
# ---------------------------------------------------------------------------

def test_git_returns_stdout():
    with patch("gitea_redmine_sync.git_ops.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="abc\n", stderr="")
        assert _git_command("status") == "abc"


def test_git_raises_on_nonzero_exit():
    with patch("gitea_redmine_sync.git_ops.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fatal: not a repo")
        with pytest.raises(RuntimeError, match="failed"):
            _git_command("fetch")


# ---------------------------------------------------------------------------
# sync_repo
# ---------------------------------------------------------------------------

def test_sync_repo_clones_when_missing(tmp_path, sample_record):
    sample_record["fs_path"] = str(tmp_path / "repo.git")
    with patch("gitea_redmine_sync.git_ops._git") as mock_git:
        sync_repo(sample_record)
        mock_git.assert_called_once_with("clone", "--bare", sample_record["clone_url"], sample_record["fs_path"])


def test_sync_repo_fetches_when_exists(tmp_path, sample_record):
    repo_path = tmp_path / "repo.git"
    repo_path.mkdir()
    (repo_path / "HEAD").touch()
    sample_record["fs_path"] = str(repo_path)

    with patch("gitea_redmine_sync.git_ops._git") as mock_git:
        sync_repo(sample_record)
        mock_git.assert_called_once_with("fetch", "--all", "--prune", cwd=str(repo_path))


# ---------------------------------------------------------------------------
# run_cleanup
# ---------------------------------------------------------------------------

def test_run_cleanup_removes_stale_repo(tmp_path):
    # Create a bare repo structure on disk that is NOT in Redmine
    stale = tmp_path / "stale.git"
    stale.mkdir()
    (stale / "HEAD").touch()
    (stale / "objects").mkdir()

    cache = MagicMock()
    cache.get.return_value = ({}, {})  # no known repos

    with patch("gitea_redmine_sync.git_ops.shutil.rmtree") as mock_rm:
        # run_cleanup only scans parent dirs of known repos, so inject one
        cache.get.return_value = (
            {},
            {str(tmp_path / "other.git"): {"clone_url": "x", "fs_path": str(tmp_path / "other.git"), "project": "p"}},
        )
        run_cleanup(cache)
        mock_rm.assert_called_once_with(stale, ignore_errors=True)


def test_run_cleanup_keeps_known_repo(tmp_path):
    known = tmp_path / "known.git"
    known.mkdir()
    (known / "HEAD").touch()
    (known / "objects").mkdir()

    cache = MagicMock()
    cache.get.return_value = (
        {},
        {str(known): {"clone_url": "x", "fs_path": str(known), "project": "p"}},
    )

    with patch("gitea_redmine_sync.git_ops.shutil.rmtree") as mock_rm:
        run_cleanup(cache)
        mock_rm.assert_not_called()
