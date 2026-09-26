import asyncio
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.services.apps_gateway import HpcApplicationGatewayService


def gateway():
    service = HpcApplicationGatewayService()
    service._webhdp_sessions = {"owned": SimpleNamespace(owner_username="webhdp", remote_output_dir="/apps/session/outputs")}
    return service


@pytest.mark.parametrize("path,user", [
    ("/apps/session/outputs/image.png", "other"),
    ("/apps/session/inputs/private.json", "webhdp"),
    ("/apps/session/outputs/../../secrets", "webhdp"),
])
def test_artifact_access_is_scoped_to_owner_and_output_directory(path, user):
    with pytest.raises(HTTPException) as error:
        asyncio.run(gateway().download_webhdp_artifact("owned", path, SimpleNamespace(username=user, is_admin=False)))
    assert error.value.status_code in {400, 403}


def test_artifact_download_checks_real_path_and_streams(monkeypatch):
    service = gateway()
    sftp = MagicMock()
    sftp.__aenter__ = AsyncMock(return_value=sftp)
    sftp.__aexit__ = AsyncMock(return_value=False)
    sftp.realpath = AsyncMock(return_value="/apps/session/outputs/image.png")
    sftp.stat = AsyncMock(return_value=SimpleNamespace(size=3, permissions=stat.S_IFREG | 0o600))
    handle = MagicMock()
    handle.__aenter__ = AsyncMock(return_value=handle)
    handle.__aexit__ = AsyncMock(return_value=False)
    handle.read = AsyncMock(side_effect=[b"png", b""])
    sftp.open.return_value = handle
    monkeypatch.setattr("app.services.apps_gateway.ssh_manager.open_sftp", AsyncMock(return_value=sftp))

    async def run():
        response = await service.download_webhdp_artifact("owned", "/apps/session/outputs/image.png", SimpleNamespace(username="webhdp", is_admin=False))
        assert response.headers["content-length"] == "3"
        assert b"".join([chunk async for chunk in response.body_iterator]) == b"png"
        sftp.realpath.return_value = "/private/secret"
        with pytest.raises(HTTPException) as error:
            await service.download_webhdp_artifact("owned", "/apps/session/outputs/link", SimpleNamespace(username="webhdp", is_admin=False))
        assert error.value.status_code == 403

    asyncio.run(run())


def test_stream_upload_is_atomic_preserves_directories_and_cleans_incomplete_data(monkeypatch):
    service = gateway()
    service._webhdp_sessions['owned'].remote_input_dir = '/apps/session/inputs'
    sftp = MagicMock()
    sftp.__aenter__ = AsyncMock(return_value=sftp)
    sftp.__aexit__ = AsyncMock(return_value=False)
    sftp.lstat = AsyncMock(return_value=SimpleNamespace(permissions=stat.S_IFDIR | 0o700))
    sftp.posix_rename = AsyncMock()
    sftp.remove = AsyncMock()
    handle = MagicMock()
    handle.__aenter__ = AsyncMock(return_value=handle)
    handle.__aexit__ = AsyncMock(return_value=False)
    handle.write = AsyncMock()
    sftp.open.return_value = handle
    monkeypatch.setattr('app.services.apps_gateway.ssh_manager.open_sftp', AsyncMock(return_value=sftp))
    actor = SimpleNamespace(username='webhdp', is_admin=False)
    async def chunks():
        yield b'ab'
        yield b'cd'
    async def run():
        result = await service.stream_webhdp_file('owned', 'nested/buffer.bin', chunks(), actor, expected_size='4')
        assert result['remote_path'] == '/apps/session/inputs/nested/buffer.bin'
        assert result['size_bytes'] == 4
        assert handle.write.await_count == 2
        assert sftp.posix_rename.await_count == 1
        with pytest.raises(HTTPException):
            await service.stream_webhdp_file('owned', '../private', chunks(), actor)
        with pytest.raises(HTTPException):
            await service.stream_webhdp_file('owned', 'nested/incomplete.bin', chunks(), actor, expected_size='9')
        assert sftp.remove.await_count == 1
        assert sftp.posix_rename.await_count == 1
        sftp.lstat.return_value.permissions = stat.S_IFLNK | 0o777
        with pytest.raises(HTTPException):
            await service.stream_webhdp_file('owned', 'link/private', chunks(), actor)
    asyncio.run(run())
