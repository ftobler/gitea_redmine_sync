"""Tests for RepoCache."""

from unittest.mock import MagicMock, patch

from gitea_redmine_sync.cache import RepoCache


# Matches the actual GET /repositories.json response from redmine_repository_api.
# Fields per the API docs:
#   project: id (int), name (str)
#   repo:    id (int), name (str), type (str), path (str)
# NOTE: "url" (Gitea clone URL) is NOT a documented API field — its absence
#       means the by_clone_url index cannot currently be populated from real
#       API data. Needs clarification.
REDMINE_RESPONSE = {
    "projects": [
        {
            "id": 1,
            "name": "My Project",
            "repositories": [
                {
                    "id": 1,
                    "name": "Main repository",
                    "type": "Repository::Git",
                    "path": "/repos/owner/repo.git",
                }
            ],
        }
    ]
}


def _mock_get(response_json: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.json.return_value = response_json
    mock_response.raise_for_status = MagicMock()
    return mock_response


@patch("gitea_redmine_sync.cache.requests.get")
def test_get_populates_by_path_index(mock_get):
    mock_get.return_value = _mock_get(REDMINE_RESPONSE)
    c = RepoCache()
    _, by_path = c.get()
    assert "/repos/owner/repo.git" in by_path


@patch("gitea_redmine_sync.cache.requests.get")
def test_record_contains_project_name(mock_get):
    mock_get.return_value = _mock_get(REDMINE_RESPONSE)
    c = RepoCache()
    _, by_path = c.get()
    assert by_path["/repos/owner/repo.git"]["project"] == "My Project"


@patch("gitea_redmine_sync.cache.requests.get")
def test_get_uses_cached_result_within_ttl(mock_get):
    mock_get.return_value = _mock_get(REDMINE_RESPONSE)
    c = RepoCache()
    c.get()
    c.get()
    assert mock_get.call_count == 1


@patch("gitea_redmine_sync.cache.requests.get")
def test_get_force_bypasses_cache(mock_get):
    mock_get.return_value = _mock_get(REDMINE_RESPONSE)
    c = RepoCache()
    c.get()
    c.get(force=True)
    assert mock_get.call_count == 2


@patch("gitea_redmine_sync.cache.requests.get")
def test_invalidate_causes_refetch(mock_get):
    mock_get.return_value = _mock_get(REDMINE_RESPONSE)
    c = RepoCache()
    c.get()
    c.invalidate()
    c.get()
    assert mock_get.call_count == 2


@patch("gitea_redmine_sync.cache.requests.get")
def test_skips_repos_with_missing_path(mock_get):
    response = {
        "projects": [
            {
                "id": 2,
                "name": "Empty Project",
                "repositories": [
                    {"id": 1, "name": "repo", "type": "Repository::Git", "path": ""},
                ],
            }
        ]
    }
    mock_get.return_value = _mock_get(response)
    c = RepoCache()
    by_url, by_path = c.get()
    assert len(by_path) == 0
