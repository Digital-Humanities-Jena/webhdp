import io
from types import SimpleNamespace
from unittest.mock import Mock

import dropbox
import pytest
from dropbox.exceptions import AuthError

from services.cloud_upload_service import CloudUploadService


@pytest.fixture()
def client(monkeypatch):
    for key in ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN"):
        monkeypatch.setenv(key, "test-credential")
    client = Mock()
    client.files_upload.return_value = SimpleNamespace(id="id:test")
    monkeypatch.setattr(dropbox, "Dropbox", Mock(return_value=client))
    return client


def test_availability_authenticates_before_reporting_connected(client):
    assert CloudUploadService.check_dropbox_available() == (True, "Connected")
    client.users_get_current_account.assert_called_once()


def test_availability_rejects_revoked_credentials(client):
    client.users_get_current_account.side_effect = AuthError(
        "test-request", dropbox.auth.AuthError.invalid_access_token
    )
    available, message = CloudUploadService.check_dropbox_available()
    assert not available
    assert "Authentication failed" in message


@pytest.mark.parametrize("streaming", [False, True])
def test_uploads_do_not_create_shared_links(client, tmp_path, streaming):
    payload = b"private model data"
    remote_path = "/uploads/model.glb"
    if streaming:
        result = CloudUploadService.stream_upload_to_dropbox(
            io.BytesIO(payload), remote_path, len(payload)
        )
    else:
        local_path = tmp_path / "model.glb"
        local_path.write_bytes(payload)
        result = CloudUploadService.upload_to_dropbox(str(local_path), remote_path)
    assert result["success"]
    assert result["file_id"] == "id:test"
    assert result["remote_url"] == "dropbox:///uploads/model.glb"
    assert client.files_upload.call_args.args == (payload, remote_path)
    client.sharing_create_shared_link_with_settings.assert_not_called()


def test_download_link_is_requested_only_when_needed(client):
    client.files_get_temporary_link.return_value = SimpleNamespace(
        link="https://dl.dropbox.test/temporary"
    )
    assert (
        CloudUploadService.get_file_download_url("/uploads/model.glb", "dropbox")
        == "https://dl.dropbox.test/temporary"
    )
    client.files_get_temporary_link.assert_called_once_with("/uploads/model.glb")
    client.sharing_create_shared_link_with_settings.assert_not_called()
