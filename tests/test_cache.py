"""Tests for RepoCache."""

from unittest.mock import MagicMock, patch

from gitea_redmine_sync.cache import RepoCache


REDMINE_RESPONSE = {
    "projects": [
        {
            "identifier": "myproject",
            "repositories": [
                {
                    "url": "http://gitea.test/owner/repo.git",
                    "root_url": "/repos/owner/repo.git",
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
def test_get_populates_both_indexes(mock_get):
    mock_get.return_value = _mock_get(REDMINE_RESPONSE)
    c = RepoCache()
    by_url, by_path = c.get()

    assert "http://gitea.test/owner/repo.git" in by_url
    assert "/repos/owner/repo.git" in by_path


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
def test_skips_repos_with_missing_url_or_path(mock_get):
    response = {
        "projects": [
            {
                "identifier": "p",
                "repositories": [
                    {"url": "", "root_url": "/some/path"},
                    {"url": "http://gitea.test/repo.git", "root_url": ""},
                ],
            }
        ]
    }
    mock_get.return_value = _mock_get(response)
    c = RepoCache()
    by_url, by_path = c.get()
    assert len(by_url) == 0
    assert len(by_path) == 0
