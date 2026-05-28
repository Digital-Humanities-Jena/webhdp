import io
import zipfile

import pytest

from exceptions import SecurityError, ValidationError
from security import safe_extract_zip, sanitize_upload_filename


def test_sanitize_upload_filename_rejects_disallowed_extension():
    with pytest.raises(ValidationError):
        sanitize_upload_filename("../../shell.php", allowed_extensions={".glb"})


def test_sanitize_upload_filename_strips_path_components():
    assert sanitize_upload_filename("../../model.glb", allowed_extensions={".glb"}) == "model.glb"


def test_safe_extract_zip_rejects_traversal(tmp_path):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("../escape.txt", "owned")
    archive_buffer.seek(0)

    with zipfile.ZipFile(archive_buffer) as archive:
        with pytest.raises(SecurityError):
            safe_extract_zip(archive, tmp_path)

    assert not (tmp_path.parent / "escape.txt").exists()


def test_safe_extract_zip_allows_normal_members(tmp_path):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("nested/model.obj", "o cube")
    archive_buffer.seek(0)

    with zipfile.ZipFile(archive_buffer) as archive:
        safe_extract_zip(archive, tmp_path)

    assert (tmp_path / "nested" / "model.obj").read_text() == "o cube"
