"""Redmine repository list cache with TTL and thread safety."""

import logging
import threading
from time import time
import requests

from .config import CACHE_TTL, REDMINE_API_KEY, REDMINE_URL

log = logging.getLogger(__name__)

RepoRecord = dict[str, str]


class RepoCache:
    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._by_clone_url: dict[str, RepoRecord] = {}
        self._by_path: dict[str, RepoRecord] = {}
        self._ts: float = 0.0

    def _fetch_and_parse(self) -> tuple[dict[str, RepoRecord], dict[str, RepoRecord]]:
        url = f"{REDMINE_URL}/repositories.json"
        r = requests.get(url, headers={"X-Redmine-API-Key": REDMINE_API_KEY}, timeout=30)
        r.raise_for_status()

        by_clone_url: dict[str, RepoRecord] = {}
        by_path: dict[str, RepoRecord] = {}
        for project in r.json().get("projects", []):
            for repo in project.get("repositories", []):
                clone_url = repo.get("url", "").rstrip("/")
                fs_path = repo.get("root_url", "").rstrip("/")
                if not clone_url or not fs_path:
                    continue
                record: RepoRecord = {
                    "clone_url": clone_url,
                    "fs_path": fs_path,
                    "project": project.get("identifier", ""),
                }
                by_clone_url[clone_url] = record
                by_path[fs_path] = record

        log.info("Redmine returned %d repo(s)", len(by_path))
        return by_clone_url, by_path

    def get(self, force: bool = False) -> tuple[dict[str, RepoRecord], dict[str, RepoRecord]]:
        with self._lock:
            age = time() - self._ts
            if force or not self._by_clone_url or age > CACHE_TTL:
                log.info("Fetching Redmine repo list (age=%.0fs)", age)
                self._by_clone_url, self._by_path = self._fetch_and_parse()
                self._ts = time()
            return dict(self._by_clone_url), dict(self._by_path)

    def invalidate(self) -> None:
        with self._lock:
            self._ts = 0.0
