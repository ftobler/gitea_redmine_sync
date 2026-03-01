"""Git operations: clone/fetch bare repos and cleanup stale ones."""

import logging
import shutil
import subprocess
from pathlib import Path

from .cache import RepoCache, RepoRecord

log = logging.getLogger(__name__)


def _git_command(*args: str, cwd: str | None = None) -> str:
    cmd = ["git", *args]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def sync_repo(record: RepoRecord) -> None:
    clone_url = record["clone_url"]
    fs_path = record["fs_path"]
    path = Path(fs_path)

    if path.exists() and (path / "HEAD").exists():
        log.info("[sync] fetch %s", fs_path)
        _git_command(
            "fetch", "origin",
            "+refs/heads/*:refs/heads/*",
            "+refs/tags/*:refs/tags/*",
            "--prune",
            cwd=fs_path,
        )
    else:
        log.info("[sync] clone %s -> %s", clone_url, fs_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _git_command("clone", "--bare", clone_url, fs_path)


def run_cleanup(cache: RepoCache) -> None:
    """Delete bare repos on disk that are no longer defined in Redmine."""
    _, by_path = cache.get()
    scan_roots = {str(Path(p).parent) for p in by_path}

    for root in scan_roots:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for child in root_path.iterdir():
            is_bare = (
                child.is_dir()
                and (child / "HEAD").exists()
                and (child / "objects").exists()
            )
            if is_bare and str(child) not in by_path:
                log.warning("[cleanup] deleting stale repo: %s", child)
                shutil.rmtree(child, ignore_errors=True)
