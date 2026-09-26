from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from exceptions import APIConnectionError
from services.hpc_link_client import HpcLinkClient, _service_tokens


def test_service_login_is_cached_and_renewed_without_following_redirects(monkeypatch):
    _service_tokens.clear()
    monkeypatch.setenv("HPC_LINK_BASE_URL", "https://hpc.example.org")
    monkeypatch.setenv("HPC_LINK_USERNAME", "webhdp")
    monkeypatch.setenv("HPC_LINK_PASSWORD", "private-password")
    response = Mock(status_code=200)
    response.json.return_value = {"access_token": "a.b.c", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    post = Mock(return_value=response)
    monkeypatch.setattr("services.hpc_link_client.requests.post", post)
    client = HpcLinkClient(base_url="https://hpc.example.org")
    assert client._headers()["Authorization"] == "Bearer a.b.c"
    assert client._headers()["Authorization"] == "Bearer a.b.c"
    assert post.call_count == 1
    assert post.call_args.kwargs["allow_redirects"] is False
    _service_tokens[(client.base_url, "webhdp")] = ("expired", 0)
    assert client._headers()["Authorization"] == "Bearer a.b.c"
    assert post.call_count == 2
    other = HpcLinkClient(base_url="https://different.example.org")
    assert "Authorization" not in other._headers()
    assert post.call_count == 2
    _service_tokens.clear()


def test_service_login_failure_does_not_expose_password(monkeypatch):
    _service_tokens.clear()
    monkeypatch.setenv("HPC_LINK_BASE_URL", "https://hpc.example.org")
    monkeypatch.setenv("HPC_LINK_USERNAME", "webhdp")
    monkeypatch.setenv("HPC_LINK_PASSWORD", "private-password")
    monkeypatch.setattr("services.hpc_link_client.requests.post", Mock(return_value=Mock(status_code=401)))
    with pytest.raises(APIConnectionError, match="service account authentication failed") as error:
        HpcLinkClient(base_url="https://hpc.example.org")._headers()
    assert "private-password" not in str(error.value)


def test_staging_cannot_publish_even_with_missing_database(monkeypatch, tmp_path):
    from services.hdpc_zenodo_service import publish_record
    monkeypatch.setenv("ZENODO_PUBLISH_ENABLED", "false")
    http = Mock()
    result = publish_record(str(tmp_path / "missing.hdpc"), 1, http=http)
    assert result["success"] is False
    assert "disabled" in result["error"]
    http.post.assert_not_called()
