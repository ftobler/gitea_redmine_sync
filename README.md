# gitea-redmine-sync

Keeps Redmine bare git repositories in sync with Gitea via push webhooks.

When Gitea fires a `push` event the service clones (or fetches) the
corresponding bare repo into the path Redmine expects.  A periodic reconcile
loop re-syncs everything even if a webhook is missed.

## Requirements

- Redmine with the
  [redmine_repository_api](https://github.com/ftobler/redmine_repository_api)
  plugin installed.
- Gitea (any recent version).
- Docker / Docker Compose.

## Quick start

```bash
cp .env.example .env
# edit .env — set REDMINE_URL, REDMINE_API_KEY, GITEA_WEBHOOK_SECRET
docker compose up -d
```

The service listens on port 8000 (proxied through Caddy on 443).

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `REDMINE_URL` | yes | — | Base URL of your Redmine instance |
| `REDMINE_API_KEY` | yes | — | Redmine REST API key (admin) |
| `GITEA_WEBHOOK_SECRET` | no | _(empty)_ | HMAC-SHA256 secret; leave empty to skip signature verification |
| `RECONCILE_INTERVAL` | no | `3600` | Seconds between full re-syncs |
| `CACHE_TTL` | no | `300` | Seconds to cache the Redmine repo list |

## Gitea webhook setup

In each Gitea repository go to **Settings → Webhooks → Add webhook → Gitea**:

| Field | Value |
|---|---|
| Target URL | `https://your-host/hooks/gitea` |
| HTTP method | POST |
| Content type | `application/json` |
| Secret | value of `GITEA_WEBHOOK_SECRET` |
| Trigger | Push events |

## Volumes

The service writes bare repos into the directory specified by Redmine's
`path` field.  Mount the same path in both the Redmine container and this
service so the paths match:

```yaml
volumes:
  - /srv/repos:/repos
```

## Unit tests

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## End-to-end tests

The `e2e/` directory contains a self-contained Docker Compose stack that
starts Redmine (with the plugin), Gitea, the sync service, and a pytest
runner — all on an isolated network.  No persistent state is kept on the host.

```bash
cd e2e
docker compose up -d --build
docker compose logs -f tests   # stream pytest output; Ctrl-C when done
docker compose down -v         # tear down and remove volumes
```

The `tests` container exit code mirrors the pytest exit code.  To read it
after the fact:

```bash
docker inspect e2e-tests-1 --format '{{.State.ExitCode}}'
```

To see logs from other services while tests run (useful for debugging failures):

```bash
docker compose logs -f sync    # sync-service logs
docker compose logs -f redmine # Redmine logs
```

> **Note:** avoid `--abort-on-container-exit` — the one-shot `gitea-init`
> container exits with code 0 as soon as the admin user is created, which
> triggers an early abort before the tests start.

### What the E2E tests cover

| Group | Tests |
|---|---|
| `TestServiceHealth` | all three services respond to HTTP |
| `TestRedmineApi` | `/repositories.json` structure, clone-URL field, type filter, auth |
| `TestWebhookEndpoint` | non-push events, unknown repos, bad payloads |
| `TestFullSyncFlow` | webhook → git clone; push new commit → webhook → git fetch |

### Design note

The Redmine plugin does not expose the upstream Gitea clone URL in its API
response.  The E2E `Dockerfile.redmine` patches the plugin controller to also
emit `url: repo.root_url`, and the bootstrap stores the Gitea clone URL in
the `root_url` database column.  This bridges the gap without touching
production code.
