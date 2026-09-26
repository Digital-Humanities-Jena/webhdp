import json
import os
import sqlite3

from services.hdpc_local_service import add_local_source_files, create_local_record_with_metadata
from services.hdpc_zenodo_service import (
    append_community_to_record,
    create_api_draft,
    create_new_version_with_files,
    discard_draft,
    remove_community_from_record,
    upload_files_for_deposition,
)


class _DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _DummyZenodoHttp:
    def __init__(self, *, emulate_newversion_contract=True):
        self.emulate_newversion_contract = emulate_newversion_contract
        self.post_calls = []
        self.put_calls = []
        self.get_calls = []
        self.delete_calls = []
        self.draft_metadata = {"title": "Draft title", "version": "0.0.1"}
        self.draft_files = [
            {
                "filename": "inherited.txt",
                "key": "inherited.txt",
                "checksum": "md5:inherited",
                "filesize": 10,
                "links": {"self": "https://sandbox.zenodo.org/api/files/bucket-1/inherited.txt"},
            }
        ]

    def _draft_payload(self):
        return {
            "id": 9001,
            "doi": "10.5072/zenodo.9001",
            "conceptrecid": "7001",
            "links": {
                "self": "https://sandbox.zenodo.org/api/deposit/depositions/9001",
                "latest_draft": "https://sandbox.zenodo.org/api/deposit/depositions/9001",
                "discard": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/discard",
                "publish": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/publish",
                "edit": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/edit",
                "bucket": "https://sandbox.zenodo.org/api/files/bucket-1",
                "html": "https://sandbox.zenodo.org/deposit/9001",
            },
            "metadata": dict(self.draft_metadata),
            "files": [dict(item) for item in self.draft_files],
        }

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if url.endswith("/actions/discard"):
            return _DummyResponse(204, {})
        if url.endswith("/actions/edit"):
            self.draft_metadata = {"title": "Draft title", "communities": [{"identifier": "alpha"}]}
            return _DummyResponse(201, self._draft_payload())
        if url.endswith("/actions/newversion"):
            if self.emulate_newversion_contract:
                return _DummyResponse(
                    201,
                    {
                        "id": 9000,
                        "doi": "10.5072/zenodo.9000",
                        "conceptrecid": "7001",
                        "metadata": {"title": "Published title", "version": "0.0.1"},
                        "links": {
                            "html": "https://sandbox.zenodo.org/records/9000",
                            "newversion": "https://sandbox.zenodo.org/api/deposit/depositions/9000/actions/newversion",
                            "latest_draft": "https://sandbox.zenodo.org/api/deposit/depositions/9001",
                            "latest_draft_html": "https://sandbox.zenodo.org/deposit/9001",
                        },
                    },
                )
            direct_draft_payload = self._draft_payload()
            (direct_draft_payload.get("links") or {}).pop("latest_draft", None)
            return _DummyResponse(
                201,
                direct_draft_payload,
            )
        if url.endswith("/actions/publish"):
            last_metadata = {}
            for put_url, put_kwargs in reversed(self.put_calls):
                if put_url.endswith("/9001"):
                    last_metadata = dict((put_kwargs.get("json") or {}).get("metadata") or {})
                    break
            return _DummyResponse(
                202,
                {
                    "id": 9001,
                    "doi": "10.5072/zenodo.9001",
                    "conceptrecid": "7001",
                    "conceptdoi": "10.5072/zenodo.7001",
                    "files": [
                        {"filename": "model.glb", "key": "model.glb", "checksum": "md5:abc", "filesize": 100},
                        {"filename": "preview.png", "key": "preview.png", "checksum": "md5:def", "filesize": 200},
                    ],
                    "links": {
                        "html": "https://sandbox.zenodo.org/records/9001",
                        "edit": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/edit",
                    },
                    "metadata": last_metadata or {"title": "Draft title"},
                },
            )
        return _DummyResponse(
            201,
            self._draft_payload(),
        )

    def put(self, url, **kwargs):
        self.put_calls.append((url, kwargs))
        filename = url.rsplit("/", 1)[-1]
        if filename == "9001":
            payload = dict((kwargs.get("json") or {}).get("metadata") or {})
            payload.setdefault("title", "Draft title")
            payload.setdefault("version", "0.0.2")
            self.draft_metadata = payload
            return _DummyResponse(200, self._draft_payload())
        file_payload = {
            "id": f"file-{filename}",
            "filename": filename,
            "key": filename,
            "checksum": f"md5:{filename}",
            "filesize": 128,
            "links": {"self": url},
        }
        self.draft_files = [
            item for item in self.draft_files if str(item.get("filename") or item.get("key") or "").lower() != filename.lower()
        ]
        self.draft_files.append(file_payload)
        return _DummyResponse(200, file_payload)

    def delete(self, url, **kwargs):
        self.delete_calls.append((url, kwargs))
        filename = url.rsplit("/", 1)[-1]
        self.draft_files = [
            item for item in self.draft_files if str(item.get("filename") or item.get("key") or "").lower() != filename.lower()
        ]
        return _DummyResponse(204, {})

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if url.endswith("/api/deposit/depositions/9001"):
            return _DummyResponse(200, self._draft_payload())
        return _DummyResponse(
            200,
            self._draft_payload(),
        )


def _create_hdpc_with_source(path: str, root_dir: str) -> tuple[str, str]:
    uploads_dir = os.path.join(root_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    source_path = os.path.join(uploads_dir, "model.glb")
    with open(source_path, "w", encoding="utf-8") as handle:
        handle.write("glb")

    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE source_files (
            file_id INTEGER PRIMARY KEY,
            filename TEXT,
            absolute_path TEXT,
            relative_path TEXT,
            file_type TEXT,
            status TEXT,
            size_bytes INTEGER,
            mime_type TEXT,
            pipeline_source TEXT,
            step_source TEXT,
            added_timestamp TEXT
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO source_files (
            file_id, filename, absolute_path, relative_path, file_type, status,
            size_bytes, mime_type, pipeline_source, step_source, added_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            101,
            "model.glb",
            source_path,
            "model.glb",
            "primary_source",
            "ready",
            100,
            "model/gltf-binary",
            "ingestion",
            "scan",
            "2026-03-10T10:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    preview_path = os.path.join(root_dir, "outputs", "preview.png")
    os.makedirs(os.path.dirname(preview_path), exist_ok=True)
    with open(preview_path, "w", encoding="utf-8") as handle:
        handle.write("png")
    return source_path, preview_path


def test_create_api_draft_updates_local_hdpc_state(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={"title": "Draft title", "description": "Description", "creators": [{"name": "Museum"}]},
        is_sandbox=True,
        access_token="sandbox-token",
    )

    result = create_api_draft(hdpc_path, 1, http=_DummyZenodoHttp())

    assert result["success"] is True
    conn = sqlite3.connect(hdpc_path)
    conn.row_factory = sqlite3.Row
    try:
        record = conn.execute("SELECT * FROM zenodo_records WHERE record_id = 1").fetchone()
        assert record["record_status"] == "draft"
        assert record["zenodo_record_id"] == "9001"
        links = conn.execute("SELECT link_rel, link_url FROM zenodo_record_links WHERE record_id = 1").fetchall()
        assert {row["link_rel"] for row in links} >= {"self", "publish", "bucket", "html"}
    finally:
        conn.close()


def test_append_community_to_draft_updates_local_metadata(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={
            "title": "Draft title",
            "description": "Description",
            "creators": [{"name": "Museum"}],
            "communities": [{"identifier": "alpha"}],
        },
        is_sandbox=True,
        access_token="sandbox-token",
    )

    conn = sqlite3.connect(hdpc_path)
    try:
        conn.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'draft',
                concept_rec_id = '7001',
                record_metadata_json = ?,
                zenodo_record_id = '9001'
            WHERE record_id = 1
            """,
            (
                json.dumps(
                    {
                        "id": 9001,
                        "conceptrecid": "7001",
                        "metadata": {"title": "Draft title", "communities": [{"identifier": "alpha"}]},
                        "links": {
                            "self": "https://sandbox.zenodo.org/api/deposit/depositions/9001",
                            "publish": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/publish",
                            "html": "https://sandbox.zenodo.org/deposit/9001",
                        },
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = append_community_to_record(hdpc_path, 1, "beta", http=_DummyZenodoHttp())

    assert result["success"] is True
    assert result["result"]["status"] == "succeeded"
    assert result["result"]["communities_after"] == ["alpha", "beta"]
    conn = sqlite3.connect(hdpc_path)
    try:
        stored = json.loads(conn.execute("SELECT record_metadata_json FROM zenodo_records WHERE record_id = 1").fetchone()[0])
        assert stored["metadata"]["communities"] == [{"identifier": "alpha"}, {"identifier": "beta"}]
    finally:
        conn.close()


def test_remove_community_from_published_record_edits_and_republishes(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={
            "title": "Published title",
            "description": "Description",
            "creators": [{"name": "Museum"}],
            "communities": [{"identifier": "alpha"}, {"identifier": "beta"}],
        },
        is_sandbox=True,
        access_token="sandbox-token",
    )

    conn = sqlite3.connect(hdpc_path)
    try:
        conn.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'published',
                concept_rec_id = '7001',
                record_metadata_json = ?,
                zenodo_record_id = '9001'
            WHERE record_id = 1
            """,
            (
                json.dumps(
                    {
                        "id": 9001,
                        "conceptrecid": "7001",
                        "metadata": {
                            "title": "Published title",
                            "communities": [{"identifier": "alpha"}, {"identifier": "beta"}],
                        },
                        "links": {
                            "self": "https://sandbox.zenodo.org/api/deposit/depositions/9001",
                            "edit": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/edit",
                            "publish": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/publish",
                            "html": "https://sandbox.zenodo.org/records/9001",
                        },
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    http = _DummyZenodoHttp()
    result = remove_community_from_record(hdpc_path, 1, "alpha", http=http)

    assert result["success"] is True
    assert result["result"]["status"] == "succeeded"
    assert result["result"]["communities_after"] == ["beta"]
    assert any(url.endswith("/actions/edit") for url, _ in http.post_calls)
    assert any(url.endswith("/actions/publish") for url, _ in http.post_calls)
    conn = sqlite3.connect(hdpc_path)
    try:
        stored = json.loads(conn.execute("SELECT record_metadata_json FROM zenodo_records WHERE record_id = 1").fetchone()[0])
        assert stored["metadata"]["communities"] == [{"identifier": "beta"}]
    finally:
        conn.close()


def test_upload_files_for_deposition_updates_file_statuses_and_publishes(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    _, preview_path = _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={"title": "Draft title", "description": "Description", "creators": [{"name": "Museum"}]},
        is_sandbox=True,
        access_token="sandbox-token",
    )
    add_local_source_files(
        hdpc_path,
        absolute_file_paths=[preview_path],
        record_id_to_associate=1,
        pipeline_name="render",
        step_name="fast_renderer",
    )

    http = _DummyZenodoHttp()
    draft_result = create_api_draft(hdpc_path, 1, http=http)
    assert draft_result["success"] is True

    result = upload_files_for_deposition(hdpc_path, 1, publish=True, http=http)

    assert result["success"] is True
    assert result["published"] is True
    conn = sqlite3.connect(hdpc_path)
    conn.row_factory = sqlite3.Row
    try:
        record = conn.execute("SELECT * FROM zenodo_records WHERE record_id = 1").fetchone()
        assert record["record_status"] == "published"
        mapped = conn.execute(
            "SELECT upload_status, zenodo_file_key FROM record_files_map WHERE record_id = 1 ORDER BY map_id ASC"
        ).fetchall()
        assert [row["upload_status"] for row in mapped] == ["uploaded", "uploaded"]
        assert {row["zenodo_file_key"] for row in mapped} == {"model.glb", "preview.png"}
    finally:
        conn.close()


def test_discard_draft_restores_prepared_metadata_and_resets_upload_state(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    _, preview_path = _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={
            "title": "Draft title",
            "description": "Description",
            "creators": [{"name": "Museum"}],
        },
        is_sandbox=True,
        access_token="sandbox-token",
    )
    add_local_source_files(
        hdpc_path,
        absolute_file_paths=[preview_path],
        record_id_to_associate=1,
        pipeline_name="render",
        step_name="fast_renderer",
    )

    http = _DummyZenodoHttp()
    draft_result = create_api_draft(hdpc_path, 1, http=http)
    assert draft_result["success"] is True

    conn = sqlite3.connect(hdpc_path)
    try:
        conn.execute(
            """
            UPDATE record_files_map
            SET upload_status = 'uploaded',
                zenodo_file_id = 'zf-1',
                zenodo_file_key = 'model.glb'
            WHERE record_id = 1
            """
        )
        conn.commit()
    finally:
        conn.close()

    result = discard_draft(hdpc_path, 1, http=http)

    assert result["success"] is True
    assert result["restored_status"] == "prepared"
    assert result["remote_discard"]["success"] is True
    assert any(url.endswith("/actions/discard") for url, _ in http.post_calls)
    conn = sqlite3.connect(hdpc_path)
    conn.row_factory = sqlite3.Row
    try:
        record = conn.execute("SELECT * FROM zenodo_records WHERE record_id = 1").fetchone()
        assert record["record_status"] == "prepared"
        assert record["zenodo_record_id"] is None
        assert record["concept_rec_id"] is None
        restored_payload = json.loads(record["record_metadata_json"])
        assert restored_payload == {
            "metadata": {
                "title": "Draft title",
                "description": "Description",
                "creators": [{"name": "Museum"}],
            }
        }
        file_map = conn.execute(
            """
            SELECT upload_status, zenodo_file_id, zenodo_file_key
            FROM record_files_map
            WHERE record_id = 1
            ORDER BY map_id ASC
            """
        ).fetchall()
        assert [row["upload_status"] for row in file_map] == ["pending", "pending"]
        assert all(row["zenodo_file_id"] is None for row in file_map)
        links = conn.execute("SELECT COUNT(*) FROM zenodo_record_links WHERE record_id = 1").fetchone()[0]
        assert links == 0
        snapshot_stages = [
            row[0]
            for row in conn.execute(
                "SELECT snapshot_stage FROM zenodo_record_snapshots WHERE record_id = 1 ORDER BY snapshot_id ASC"
            ).fetchall()
        ]
        assert "prepared_before_draft" in snapshot_stages
        assert "draft_discarded_local_restore" in snapshot_stages
    finally:
        conn.close()


def test_create_new_version_with_files_builds_new_local_record_and_replaces_file_set(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    source_path, preview_path = _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={"title": "Published title", "description": "Description", "creators": [{"name": "Museum"}]},
        is_sandbox=True,
        access_token="sandbox-token",
    )
    add_local_source_files(
        hdpc_path,
        absolute_file_paths=[preview_path],
        record_id_to_associate=1,
        pipeline_name="render",
        step_name="fast_renderer",
    )

    conn = sqlite3.connect(hdpc_path)
    try:
        conn.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'published',
                concept_rec_id = '7001',
                version = '0.0.1',
                record_metadata_json = ?,
                zenodo_record_id = '9000',
                zenodo_doi = '10.5072/zenodo.9000'
            WHERE record_id = 1
            """,
            (
                json.dumps(
                    {
                        "id": 9000,
                        "doi": "10.5072/zenodo.9000",
                        "conceptrecid": "7001",
                        "metadata": {"title": "Published title", "version": "0.0.1"},
                        "links": {
                            "html": "https://sandbox.zenodo.org/records/9000",
                            "newversion": "https://sandbox.zenodo.org/api/deposit/depositions/9000/actions/newversion",
                        },
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    http = _DummyZenodoHttp()
    result = create_new_version_with_files(
        hdpc_path,
        concept_rec_id="7001",
        is_sandbox=True,
        source_file_path=source_path,
        absolute_file_paths=[source_path, preview_path],
        publish=False,
        http=http,
    )

    assert result["success"] is True
    assert result["new_local_record_id"] == 2
    assert result["registered_file_count"] == 2
    assert result["uploaded_file_count"] == 2
    assert result["version"] == "0.0.2"
    assert http.post_calls[0][0].endswith("/actions/newversion")
    assert any(
        call[0] == "https://sandbox.zenodo.org/api/deposit/depositions/9001" and call[1].get("timeout") == 60
        for call in http.get_calls
    )
    conn = sqlite3.connect(hdpc_path)
    conn.row_factory = sqlite3.Row
    try:
        new_record = conn.execute("SELECT * FROM zenodo_records WHERE record_id = 2").fetchone()
        assert new_record["record_status"] == "draft"
        assert new_record["concept_rec_id"] == "7001"
        assert new_record["version_rank"] == 2
        assert new_record["previous_record_id"] == 1
        assert new_record["record_origin"] == "versioning"
        file_map = conn.execute(
            "SELECT file_purpose, upload_status, file_path FROM record_files_map WHERE record_id = 2 ORDER BY map_id ASC"
        ).fetchall()
        assert [row["file_purpose"] for row in file_map] == ["main", "derived"]
        assert [row["upload_status"] for row in file_map] == ["uploaded", "uploaded"]
        assert [row["file_path"] for row in file_map] == ["model.glb", "preview.png"]
    finally:
        conn.close()


def test_create_new_version_with_files_falls_back_when_newversion_returns_draft_payload(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    source_path, preview_path = _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={"title": "Published title", "description": "Description", "creators": [{"name": "Museum"}]},
        is_sandbox=True,
        access_token="sandbox-token",
    )
    add_local_source_files(
        hdpc_path,
        absolute_file_paths=[preview_path],
        record_id_to_associate=1,
        pipeline_name="render",
        step_name="fast_renderer",
    )

    conn = sqlite3.connect(hdpc_path)
    try:
        conn.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'published',
                concept_rec_id = '7001',
                version = '0.0.1',
                record_metadata_json = ?,
                zenodo_record_id = '9000',
                zenodo_doi = '10.5072/zenodo.9000'
            WHERE record_id = 1
            """,
            (
                json.dumps(
                    {
                        "id": 9000,
                        "doi": "10.5072/zenodo.9000",
                        "conceptrecid": "7001",
                        "metadata": {"title": "Published title", "version": "0.0.1"},
                        "links": {
                            "html": "https://sandbox.zenodo.org/records/9000",
                            "newversion": "https://sandbox.zenodo.org/api/deposit/depositions/9000/actions/newversion",
                        },
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    http = _DummyZenodoHttp(emulate_newversion_contract=False)
    result = create_new_version_with_files(
        hdpc_path,
        concept_rec_id="7001",
        is_sandbox=True,
        source_file_path=source_path,
        absolute_file_paths=[source_path, preview_path],
        publish=False,
        http=http,
    )

    assert result["success"] is True
    assert result["new_local_record_id"] == 2
    assert not any(call[1].get("timeout") == 60 for call in http.get_calls)


def test_create_new_version_with_files_reuses_existing_draft_without_reuploading_unchanged_files(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    source_path, preview_path = _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path,
        file_id=101,
        metadata={"title": "Published title", "description": "Description", "creators": [{"name": "Museum"}]},
        is_sandbox=True,
        access_token="sandbox-token",
    )
    add_local_source_files(
        hdpc_path,
        absolute_file_paths=[preview_path],
        record_id_to_associate=1,
        pipeline_name="render",
        step_name="fast_renderer",
    )

    conn = sqlite3.connect(hdpc_path)
    try:
        conn.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'published',
                concept_rec_id = '7001',
                version = '0.0.1',
                record_metadata_json = ?,
                zenodo_record_id = '9000',
                zenodo_doi = '10.5072/zenodo.9000'
            WHERE record_id = 1
            """,
            (
                json.dumps(
                    {
                        "id": 9000,
                        "doi": "10.5072/zenodo.9000",
                        "conceptrecid": "7001",
                        "metadata": {"title": "Published title", "version": "0.0.1"},
                        "links": {
                            "html": "https://sandbox.zenodo.org/records/9000",
                            "newversion": "https://sandbox.zenodo.org/api/deposit/depositions/9000/actions/newversion",
                        },
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    first_http = _DummyZenodoHttp()
    first_result = create_new_version_with_files(
        hdpc_path,
        concept_rec_id="7001",
        is_sandbox=True,
        source_file_path=source_path,
        absolute_file_paths=[source_path, preview_path],
        publish=False,
        http=first_http,
    )
    assert first_result["success"] is True
    assert first_result["uploaded_file_count"] == 2

    put_call_count_before = len(first_http.put_calls)
    delete_call_count_before = len(first_http.delete_calls)
    second_result = create_new_version_with_files(
        hdpc_path,
        concept_rec_id="7001",
        is_sandbox=True,
        source_file_path=source_path,
        absolute_file_paths=[source_path, preview_path],
        publish=False,
        http=first_http,
    )

    assert second_result["success"] is True
    assert second_result["new_local_record_id"] == 2
    assert second_result["uploaded_file_count"] == 0
    assert second_result["preserved_file_count"] == 2
    assert second_result["deleted_inherited_files"] == []
    assert len(first_http.put_calls) == put_call_count_before
    assert len(first_http.delete_calls) == delete_call_count_before

    conn = sqlite3.connect(hdpc_path)
    conn.row_factory = sqlite3.Row
    try:
        file_map = conn.execute(
            """
            SELECT file_purpose, upload_status, zenodo_file_key
            FROM record_files_map
            WHERE record_id = 2
            ORDER BY map_id ASC
            """
        ).fetchall()
        assert [row["file_purpose"] for row in file_map] == ["main", "derived"]
        assert [row["upload_status"] for row in file_map] == ["uploaded", "uploaded"]
        assert [row["zenodo_file_key"] for row in file_map] == ["model.glb", "preview.png"]
    finally:
        conn.close()


def test_retry_reuses_draft_and_restores_missing_original(tmp_path):
    hdpc_path = str(tmp_path / "retry.hdpc")
    _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path, file_id=101,
        metadata={"title": "Retry", "description": "Description", "creators": [{"name": "Museum"}]},
        is_sandbox=True, access_token="sandbox-token",
    )
    http = _DummyZenodoHttp()
    assert create_api_draft(hdpc_path, 1, http=http)["success"]
    assert upload_files_for_deposition(hdpc_path, 1, http=http)["success"]
    http.draft_files = []  # A remote deletion must not leave a false uploaded flag.
    result = create_api_draft(hdpc_path, 1, http=http)
    assert result["success"]
    assert result["zenodo_response"]["id"] == 9001
    assert len(http.post_calls) == 1
    upload = upload_files_for_deposition(hdpc_path, 1, http=http)
    assert upload["success"] and upload["uploaded_file_count"] == 1
    assert any(item["filename"] == "model.glb" for item in http.draft_files)
    assert create_api_draft(hdpc_path, 1, http=http)["success"]
    assert upload_files_for_deposition(hdpc_path, 1, http=http)["uploaded_file_count"] == 0
    assert len(http.post_calls) == 1


def test_retry_does_not_replace_unavailable_or_submitted_draft(tmp_path):
    hdpc_path = str(tmp_path / "retry.hdpc")
    _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path, file_id=101,
        metadata={"title": "Retry", "creators": [{"name": "Museum"}]},
        is_sandbox=True, access_token="sandbox-token",
    )
    http = _DummyZenodoHttp()
    assert create_api_draft(hdpc_path, 1, http=http)["success"]
    http.get = lambda *args, **kwargs: _DummyResponse(503, {})
    assert not create_api_draft(hdpc_path, 1, http=http)["success"]
    http.get = lambda *args, **kwargs: _DummyResponse(200, {"id": 9001, "submitted": True})
    assert not create_api_draft(hdpc_path, 1, http=http)["success"]
    assert len(http.post_calls) == 1


def test_failed_file_upload_retries_without_creating_another_draft(tmp_path):
    import requests
    hdpc_path = str(tmp_path / 'retry-transfer.hdpc')
    _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(hdpc_path, file_id=101, metadata={'title':'Retry transfer','creators':[{'name':'Museum'}]},is_sandbox=True,access_token='sandbox-token')
    http=_DummyZenodoHttp()
    assert create_api_draft(hdpc_path,1,http=http)['success']
    put=http.put
    def interrupted(*args,**kwargs):raise requests.Timeout('Interrupted transfer')
    http.put=interrupted
    failed=upload_files_for_deposition(hdpc_path,1,http=http)
    assert not failed['success'] and failed['failed_upload_count']==1
    http.put=put
    assert create_api_draft(hdpc_path,1,http=http)['success']
    retried=upload_files_for_deposition(hdpc_path,1,http=http)
    assert retried['success'] and retried['uploaded_file_count']==1
    assert len(http.post_calls)==1
    assert upload_files_for_deposition(hdpc_path,1,http=http)['uploaded_file_count']==0


def test_upload_encodes_reserved_and_unicode_filename_characters(tmp_path):
    from urllib.parse import quote
    hdpc_path=str(tmp_path/'reserved.hdpc');source,_=_create_hdpc_with_source(hdpc_path,str(tmp_path))
    from pathlib import Path
    renamed=Path(source).with_name('模型 #1? 50%.glb');Path(source).rename(renamed)
    with sqlite3.connect(hdpc_path) as conn:conn.execute('UPDATE source_files SET filename=?,absolute_path=?,relative_path=? WHERE file_id=101',(renamed.name,str(renamed),renamed.name))
    create_local_record_with_metadata(hdpc_path,file_id=101,metadata={'title':'Reserved names','creators':[{'name':'Museum'}]},is_sandbox=True,access_token='sandbox-token')
    http=_DummyZenodoHttp();assert create_api_draft(hdpc_path,1,http=http)['success']
    assert upload_files_for_deposition(hdpc_path,1,http=http)['success']
    assert http.put_calls[0][0].endswith('/'+quote(renamed.name,safe=''))


def test_changed_generated_file_is_reuploaded_after_remote_refresh(tmp_path):
    from pathlib import Path
    from services.hdpc_zenodo_service import _sync_uploaded_files
    hdpc_path = str(tmp_path / "changed.hdpc")
    source, _ = _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(
        hdpc_path, file_id=101, metadata={"title": "Changed file", "creators": [{"name": "Museum"}]},
        is_sandbox=True, access_token="sandbox-token",
    )
    http = _DummyZenodoHttp()
    assert create_api_draft(hdpc_path, 1, http=http)["success"]
    assert upload_files_for_deposition(hdpc_path, 1, http=http)["success"]
    Path(source).write_bytes(b"changed model bytes")
    add_local_source_files(hdpc_path, absolute_file_paths=[source], record_id_to_associate=1, pipeline_name="render")
    with sqlite3.connect(hdpc_path) as conn:
        conn.row_factory = sqlite3.Row
        _sync_uploaded_files(conn.cursor(), 1, http._draft_payload())
        assert conn.execute("SELECT upload_status FROM record_files_map WHERE record_id=1").fetchone()[0] == "pending"
    assert upload_files_for_deposition(hdpc_path, 1, http=http)["uploaded_file_count"] == 1
    add_local_source_files(hdpc_path, absolute_file_paths=[source], record_id_to_associate=1, pipeline_name="render")
    assert upload_files_for_deposition(hdpc_path, 1, http=http)["uploaded_file_count"] == 0
    assert len(http.post_calls) == 1


def test_lod_upload_requires_explicit_validation_and_matching_content_hash(tmp_path):
    from pathlib import Path
    from services.lod_reliability import digest
    from services.lod_artifact_service import suspend_previous_artifacts, current_record_context
    hdpc_path = str(tmp_path / 'lod-upload.hdpc')
    _create_hdpc_with_source(hdpc_path, str(tmp_path))
    create_local_record_with_metadata(hdpc_path, file_id=101, metadata={'title': 'Metadata', 'creators': [{'name': 'Museum'}]}, is_sandbox=True, access_token='sandbox-token')
    http = _DummyZenodoHttp()
    assert create_api_draft(hdpc_path, 1, http=http)['success']
    output = tmp_path / 'outputs/record-1/model'
    output.mkdir(parents=True)
    path = str(output / 'edm.xml')
    Path(path).write_text('<rdf/>')
    report = {'valid': True, 'sha256': digest(Path(path).read_bytes()), 'standard': 'edm'}
    manifest = {'request': {'record': current_record_context(hdpc_path, 1), 'options': {
        'generate_iiif': False, 'generate_mets': False, 'generate_cidoc_crm': False, 'generate_jsonld': False,
    }}, 'formats': {'edm': {'success': True, 'status': 'generated', 'sha256': report['sha256'], 'validation': report}}}
    (output / 'lod-generation.json').write_text(json.dumps(manifest))
    add_local_source_files(hdpc_path, absolute_file_paths=[path], record_id_to_associate=1, pipeline_name='lod_generation')
    result = upload_files_for_deposition(hdpc_path, 1, http=http)
    assert not result['success']
    assert not any('edm.xml' in str(call) for call in http.put_calls)
    report = {'valid': True, 'sha256': digest(Path(path).read_bytes()), 'standard': 'edm'}
    add_local_source_files(hdpc_path, absolute_file_paths=[path], record_id_to_associate=1, pipeline_name='lod_generation', validation_reports={path: report})
    Path(path).write_text('changed after validation')
    result = upload_files_for_deposition(hdpc_path, 1, http=http)
    assert not result['success']
    assert not any('edm.xml' in str(call) for call in http.put_calls)
    suspend_previous_artifacts(hdpc_path, 1)
    with sqlite3.connect(hdpc_path) as conn:
        assert conn.execute("SELECT upload_status FROM record_files_map WHERE file_id IN (SELECT file_id FROM source_files WHERE filename='edm.xml')").fetchone()[0] == 'validation_pending'
    report['sha256'] = digest(Path(path).read_bytes())
    manifest['formats']['edm']['sha256'] = report['sha256']
    manifest['formats']['edm']['validation'] = report
    (output / 'lod-generation.json').write_text(json.dumps(manifest))
    add_local_source_files(hdpc_path, absolute_file_paths=[path], record_id_to_associate=1, pipeline_name='lod_generation', validation_reports={path: report})
    assert upload_files_for_deposition(hdpc_path, 1, http=http)['uploaded_file_count'] == 1
