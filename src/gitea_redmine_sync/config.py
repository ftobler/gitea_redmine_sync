"""Runtime configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()


REDMINE_URL: str = os.environ["REDMINE_URL"].rstrip("/")

REDMINE_API_KEY: str = os.environ["REDMINE_API_KEY"]

GITEA_WEBHOOK_SECRET: str = os.environ.get("GITEA_WEBHOOK_SECRET", "")

RECONCILE_INTERVAL: int = int(os.environ.get("RECONCILE_INTERVAL", "3600"))

CACHE_TTL: int = int(os.environ.get("CACHE_TTL", "300"))

