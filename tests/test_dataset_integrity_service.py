from types import SimpleNamespace
import json

import pytest

from services import dataset_integrity_service as service


def test_duplicate_groups_preserve_real_conflicts_in_each_environment():
    records = [{
        "normalized_source_file_path": "Models_Dataset/model.glb",
        "record_status": "published",
        "session_id": index,
        "local_record_id": index,
        "concept_rec_id": str(index),
        "is_sandbox": is_sandbox,
    } for index, is_sandbox in enumerate([False, False, True, True], start=1)]

    groups = service.build_duplicate_groups("Models_Dataset", records)

    assert len(groups) == 2
    assert {group["environment"] for group in groups} == {"production", "sandbox"}
    assert all(group["record_count"] == 2 and group["published_record_count"] == 2 for group in groups)
    assert all(len({record["is_sandbox"] for record in group["records"]}) == 1 for group in groups)


def test_draft_classification_does_not_match_concept_ids_across_environments():
    draft = {"record_status": "draft", "concept_rec_id": "123", "is_sandbox": True}
    production_record = {"record_status": "published", "concept_rec_id": "123", "is_sandbox": False}

    assert service.classify_draft_kind(draft, [draft, production_record]) == "partial_draft"


def test_session_dataset_context_does_not_add_synthetic_alias_for_named_record_dataset(monkeypatch):
    monkeypatch.setattr(service, "get_session_dataset_context", lambda session: {})

    assert service.get_session_dataset_keys(SimpleNamespace(id=27), [{"dataset_key": "Models_Dataset"}]) == {"Models_Dataset"}


def test_build_model_preview_resolves_encoded_published_glb_url():
    preview = service.build_model_preview(
        {
            "source_file_name": "model space #1.glb",
            "record_status": "published",
            "zenodo_record_id": "18967159",
            "is_sandbox": False,
            "record_metadata": {"files": [{"filename": "model space #1.glb"}]},
        }
    )

    assert preview == {
        "is_3d_record": True,
        "can_inline_preview": True,
        "url": "https://zenodo.org/api/records/18967159/files/model%20space%20%231.glb/content",
        "filename": "model space #1.glb",
        "format": "glb",
        "source": "zenodo_direct_file",
        "reason": None,
    }


def test_build_model_preview_prefers_previewable_model_when_metadata_has_usdz_first():
    preview = service.build_model_preview(
        {
            "source_file_name": "model.obj",
            "record_status": "published",
            "zenodo_record_id": "123",
            "is_sandbox": False,
            "record_metadata": {"files": [{"filename": "model.usdz"}, {"filename": "model.glb"}]},
        }
    )

    assert preview["can_inline_preview"] is True
    assert preview["filename"] == "model.glb"
    assert preview["url"] == "https://zenodo.org/api/records/123/files/model.glb/content"


def test_build_model_preview_marks_non_3d_records_unpreviewable():
    preview = service.build_model_preview(
        {
            "source_file_name": "notes.txt",
            "record_status": "published",
            "zenodo_record_id": "123",
            "record_metadata": {"files": [{"filename": "notes.txt"}]},
        }
    )

    assert preview["is_3d_record"] is False
    assert preview["can_inline_preview"] is False
    assert preview["reason"] == "not_3d_record"


@pytest.mark.parametrize("filename", ["model.obj", "model.ply", "model.stl", "model.usdz"])
def test_build_model_preview_keeps_non_inline_3d_formats_fallback_only(filename):
    preview = service.build_model_preview(
        {
            "source_file_name": filename,
            "record_status": "published",
            "zenodo_record_id": "123",
            "record_metadata": {"files": [{"filename": filename}]},
        }
    )

    assert preview["is_3d_record"] is True
    assert preview["can_inline_preview"] is False
    assert preview["format"] == filename.rsplit(".", 1)[1]
    assert preview["reason"] == "inline_preview_unsupported_format"


def test_build_model_preview_reports_missing_public_record_data():
    preview = service.build_model_preview(
        {
            "source_file_name": "model.glb",
            "record_status": "published",
            "record_metadata": {"files": [{"filename": "model.glb"}]},
        }
    )

    assert preview["is_3d_record"] is True
    assert preview["can_inline_preview"] is False
    assert preview["reason"] == "missing_zenodo_record_id"


def test_build_model_preview_reports_missing_model_file_for_mime_only_3d_record():
    preview = service.build_model_preview(
        {
            "source_mime_type": "model/gltf-binary",
            "record_status": "published",
            "zenodo_record_id": "123",
            "record_metadata": {"files": []},
        }
    )

    assert preview["is_3d_record"] is True
    assert preview["can_inline_preview"] is False
    assert preview["reason"] == "missing_model_file"


def test_sandbox_record_creation_allows_missing_dataset_key(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_session_dataset_context",
        lambda session_row: {
            "msf_path": None,
            "directory_root": None,
            "dataset_key": None,
            "directory_recursive": True,
            "prepared_candidate_files": [],
        },
    )
    monkeypatch.setattr(
        service,
        "collect_dataset_records",
        lambda include_all_sessions=True: ([], []),
    )

    service.ensure_fresh_record_creation_allowed(
        SimpleNamespace(id=1),
        source_file_path="/shared/sessions/hdp_session_abcd/uploads/test_model.glb",
        is_sandbox=True,
    )


def test_scan_candidate_files_infers_upload_context_for_zip_batch(tmp_path, monkeypatch):
    session_dir = tmp_path / "hdp_session_abcd"
    uploads_dir = session_dir / "uploads"
    uploads_dir.mkdir(parents=True)
    model_path = uploads_dir / "asset.glb"
    model_path.write_bytes(b"glb")
    (uploads_dir / "upload.msf.xlsx").write_bytes(b"msf")

    profile = {
        "file_path": str(uploads_dir / "upload.msf.xlsx"),
        "prepared_candidate_files": [],
    }
    monkeypatch.setattr(service, "get_session_metadata_map", lambda session_id, field_names=None: {"msf_profile": json.dumps(profile)})
    monkeypatch.setattr(service, "_shared_candidate_metadata_for_session", lambda session_row: {})
    monkeypatch.setattr(service, "_batch_candidate_metadata_by_filename", lambda session_row: {})

    candidates = service.scan_candidate_files_for_session(
        SimpleNamespace(
            id=42,
            session_dir=str(session_dir),
            hdpc_path=str(session_dir / "session.hdpc"),
            default_zenodo_environment="sandbox",
        )
    )

    assert len(candidates) == 1
    assert candidates[0].source_file_name == "asset.glb"
    assert candidates[0].dataset_key == "session_42_dataset"


def test_production_uploaded_files_use_session_identity_and_block_duplicates(monkeypatch):
    monkeypatch.setattr(service, "get_session_dataset_context", lambda session_row: {})
    source = "/shared/sessions/hdp_session_abcd/uploads/test_model.glb"
    monkeypatch.setattr(service, "collect_dataset_records", lambda **kwargs: ([], []))
    service.ensure_fresh_record_creation_allowed(SimpleNamespace(id=1), source_file_path=source, is_sandbox=False)
    monkeypatch.setattr(service, "collect_dataset_records", lambda **kwargs: ([{
        "dataset_key_lower": "session_1_dataset", "source_file_path": source,
        "normalized_source_file_path": service.normalize_source_path(source, "session_1_dataset"),
        "source_file_name": "test_model.glb", "is_sandbox": False,
        "record_status": "draft", "concept_rec_id": "123", "session_id": 1,
    }], []))
    with pytest.raises(service.DatasetIntegrityConflictError, match="Duplicate"):
        service.ensure_fresh_record_creation_allowed(SimpleNamespace(id=1), source_file_path=source, is_sandbox=False)


def test_sandbox_record_creation_still_blocks_duplicates_when_dataset_key_exists(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_session_dataset_context",
        lambda session_row: {
            "msf_path": "/shared/sessions/Turin_Dataset/upload.msf.xlsx",
            "directory_root": "/shared/sessions/Turin_Dataset",
            "dataset_key": "Turin_Dataset",
            "directory_recursive": True,
            "prepared_candidate_files": [],
        },
    )
    monkeypatch.setattr(service, "collect_dataset_records", lambda include_all_sessions=True: ([{"id": 1}], None))
    monkeypatch.setattr(service, "classify_candidate", lambda candidate, all_records: {"classification": "blocker"})

    with pytest.raises(service.DatasetIntegrityConflictError) as exc_info:
        service.ensure_fresh_record_creation_allowed(
            SimpleNamespace(id=1),
            source_file_path="/shared/sessions/Turin_Dataset/uploads/test_model.glb",
            is_sandbox=True,
        )

    assert "Duplicate dataset source detected" in str(exc_info.value)


def test_sandbox_record_operation_allows_missing_dataset_key_when_source_path_exists(monkeypatch):
    monkeypatch.setattr(
        service,
        "read_session_records",
        lambda session_row: [
            {
                "local_record_id": 7,
                "dataset_key": None,
                "source_file_path": "/shared/sessions/hdp_session_abcd/uploads/test_model.glb",
                "source_file_name": "test_model.glb",
                "is_sandbox": True,
                "concept_rec_id": "",
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "collect_dataset_records",
        lambda include_all_sessions=True: pytest.fail("duplicate scan should not run without a dataset key in sandbox"),
    )

    service.ensure_record_operation_allowed(
        SimpleNamespace(id=1),
        local_record_id=7,
        allow_allowed_versioning=False,
        exclude_current_record=True,
    )


def test_production_record_operation_still_requires_dataset_key(monkeypatch):
    monkeypatch.setattr(
        service,
        "read_session_records",
        lambda session_row: [
            {
                "local_record_id": 7,
                "dataset_key": None,
                "source_file_path": "/shared/sessions/hdp_session_abcd/uploads/test_model.glb",
                "source_file_name": "test_model.glb",
                "is_sandbox": False,
                "concept_rec_id": "",
            }
        ],
    )

    with pytest.raises(service.DatasetIntegrityConflictError) as exc_info:
        service.ensure_record_operation_allowed(
            SimpleNamespace(id=1),
            local_record_id=7,
            allow_allowed_versioning=False,
            exclude_current_record=True,
        )

    assert "dataset-aware source path" in str(exc_info.value)


def test_choose_latest_record_uses_version_rank_with_timestamp_tiebreakers():
    older_higher_rank = {
        "local_record_id": 10,
        "version": "0.0.10",
        "version_rank": 10,
        "created_at": "2026-03-01T12:00:00Z",
        "updated_at": "2026-03-20T08:00:00Z",
    }
    newer_lower_rank = {
        "local_record_id": 11,
        "version": "0.0.2",
        "version_rank": 2,
        "created_at": "2026-03-01T12:00:00Z",
        "updated_at": "2026-03-31T08:00:00Z",
    }
    same_rank_newer = {
        "local_record_id": 12,
        "version": "0.0.10",
        "version_rank": 10,
        "created_at": "2026-03-01T12:00:00Z",
        "updated_at": "2026-03-31T09:00:00Z",
    }

    chosen = service.choose_latest_record([older_higher_rank, newer_lower_rank, same_rank_newer])

    assert chosen["local_record_id"] == 12


def test_build_dataset_export_bundle_uses_version_rank_for_primary_selection(monkeypatch):
    monkeypatch.setattr(service, "resolve_glb_direct_link", lambda record, public_cache: f"glb://{record['local_record_id']}")

    records = [
        {
            "session_id": 7,
            "local_record_id": 21,
            "source_file_name": "model.glb",
            "source_file_path": "/tmp/Semantic_Dataset/model.glb",
            "normalized_source_file_path": "semantic_dataset/model.glb",
            "record_status": "published",
            "record_title": "Model v0.0.2",
            "zenodo_record_id": "9002",
            "concept_rec_id": "7001",
            "version": "0.0.2",
            "version_rank": 2,
            "zenodo_doi": "10.5072/zenodo.9002",
            "record_link": "https://sandbox.zenodo.org/records/9002",
            "is_sandbox": True,
            "created_at": "2026-03-10T12:00:00Z",
            "updated_at": "2026-03-28T09:00:00Z",
        },
        {
            "session_id": 7,
            "local_record_id": 22,
            "source_file_name": "model.glb",
            "source_file_path": "/tmp/Semantic_Dataset/model.glb",
            "normalized_source_file_path": "semantic_dataset/model.glb",
            "record_status": "published",
            "record_title": "Model v0.0.10",
            "zenodo_record_id": "9010",
            "concept_rec_id": "7001",
            "version": "0.0.10",
            "version_rank": 10,
            "zenodo_doi": "10.5072/zenodo.9010",
            "record_link": "https://sandbox.zenodo.org/records/9010",
            "is_sandbox": True,
            "created_at": "2026-03-10T12:00:00Z",
            "updated_at": "2026-03-27T09:00:00Z",
        },
        {
            "session_id": 8,
            "local_record_id": 30,
            "source_file_name": "model.glb",
            "source_file_path": "/tmp/Semantic_Dataset/model.glb",
            "normalized_source_file_path": "semantic_dataset/model.glb",
            "record_status": "draft",
            "record_title": "Foreign draft",
            "zenodo_record_id": "9999",
            "concept_rec_id": "7001",
            "version": "0.0.11",
            "version_rank": 11,
            "zenodo_doi": None,
            "record_link": "https://sandbox.zenodo.org/deposit/9999",
            "is_sandbox": True,
            "created_at": "2026-03-31T10:00:00Z",
            "updated_at": "2026-03-31T10:00:00Z",
        },
    ]

    bundle = service.build_dataset_export_bundle(
        "Semantic_Dataset",
        records,
        authoritative_session_id=7,
    )

    primary_payload = bundle["primary"]["json_payload"]
    assert primary_payload["record_count"] == 1
    assert primary_payload["records"][0]["local_record_id"] == 22
    assert primary_payload["records"][0]["version"] == "0.0.10"
    assert primary_payload["records"][0]["version_rank"] == 10


def _balanced_resolution_config():
    return {
        "preset": "balanced",
        "thresholds": {
            "version_recommendation_score": 0.9,
            "warning_score": 0.35,
        },
        "allow_force_create_fresh": True,
        "enabled_signals": {
            "hash_matching": True,
            "metadata_similarity": True,
        },
        "hash_collision_policy": {
            "enabled": True,
            "min_size_bytes": 1048576,
            "excluded_extensions": [".csv", ".json", ".log", ".md", ".text", ".tsv", ".txt", ".xml"],
            "exclude_generated_renders": True,
        },
    }


def _collision_record(overrides=None):
    payload = {
        "session_id": 7,
        "local_record_id": 21,
        "dataset_key": "Other Dataset",
        "dataset_key_lower": "other dataset",
        "normalized_source_file_path": "other/model.glb",
        "source_file_name": "model.glb",
        "source_sha256_hash": "hash-1",
        "source_size_bytes": 2 * 1024 * 1024,
        "source_file_type": "source",
        "source_pipeline_source": "scan",
        "source_step_source": "bootstrap",
        "is_sandbox": False,
        "concept_rec_id": "7001",
        "record_status": "published",
        "record_title": "Published record",
        "zenodo_record_id": "9001",
        "zenodo_doi": "10.5281/zenodo.9001",
        "record_link": "https://zenodo.org/records/9001",
        "version_rank": 2,
        "updated_at": "2026-04-01T00:00:00Z",
    }
    payload.update(overrides or {})
    return payload


def test_global_hash_collision_ignores_files_below_threshold():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/model.glb",
        source_file_name="model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/model.glb",
        is_sandbox=False,
        sha256_hash="hash-1",
        size_bytes=1024,
    )

    matches = service.find_global_hash_collision_records(
        candidate,
        [_collision_record()],
        config=_balanced_resolution_config(),
    )

    assert matches == []


def test_global_hash_collision_ignores_configured_sidecar_extensions_and_generated_renders():
    sidecar_candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/metadata.json",
        source_file_name="metadata.json",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/metadata.json",
        is_sandbox=False,
        sha256_hash="hash-1",
        size_bytes=2 * 1024 * 1024,
    )
    generated_candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/model_render.png",
        source_file_name="model_render.png",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/model_render.png",
        is_sandbox=False,
        sha256_hash="hash-1",
        size_bytes=2 * 1024 * 1024,
        pipeline_source="fast_renderer",
    )

    assert service.find_global_hash_collision_records(
        sidecar_candidate,
        [_collision_record()],
        config=_balanced_resolution_config(),
    ) == []
    assert service.find_global_hash_collision_records(
        generated_candidate,
        [_collision_record()],
        config=_balanced_resolution_config(),
    ) == []
    assert service.find_global_hash_collision_records(
        service.CandidateFile(
            source_file_path="/tmp/Dataset/model.glb",
            source_file_name="model.glb",
            dataset_key="Dataset",
            normalized_source_file_path="dataset/model.glb",
            is_sandbox=False,
            sha256_hash="hash-1",
            size_bytes=2 * 1024 * 1024,
        ),
        [_collision_record({"source_pipeline_source": "fast_renderer"})],
        config=_balanced_resolution_config(),
    ) == []


def test_global_hash_collision_returns_non_exempt_zenodo_records():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/model.glb",
        source_file_name="model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/model.glb",
        is_sandbox=False,
        sha256_hash="hash-1",
        size_bytes=2 * 1024 * 1024,
    )

    matches = service.find_global_hash_collision_records(
        candidate,
        [_collision_record(), _collision_record({"local_record_id": 22, "source_sha256_hash": "other"})],
        config=_balanced_resolution_config(),
    )

    assert len(matches) == 1
    assert matches[0]["record_link"] == "https://zenodo.org/records/9001"


def test_analyze_candidate_record_resolution_surfaces_global_hash_collision_warning():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/new-model.glb",
        source_file_name="new-model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/new-model.glb",
        is_sandbox=False,
        sha256_hash="hash-1",
        size_bytes=2 * 1024 * 1024,
    )

    result = service.analyze_candidate_record_resolution(
        candidate,
        [_collision_record()],
        config=_balanced_resolution_config(),
    )

    assert result["severity"] == "warning"
    assert result["recommended_action"] == "create_fresh_record"
    assert "global_hash_collision" in result["reason_codes"]
    assert result["matched_records"][0]["record_link"] == "https://zenodo.org/records/9001"
    assert result["matched_records"][0]["zenodo_doi"] == "10.5281/zenodo.9001"


def test_analyze_candidate_record_resolution_recommends_create_version_for_exact_same_lineage():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/model.glb",
        source_file_name="model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/model.glb",
        is_sandbox=True,
        concept_rec_id="7001",
    )
    records = [
        {
            "session_id": 7,
            "local_record_id": 11,
            "dataset_key_lower": "dataset",
            "normalized_source_file_path": "dataset/model.glb",
            "is_sandbox": True,
            "concept_rec_id": "7001",
            "record_status": "published",
            "record_title": "Published lineage",
            "version_rank": 3,
        }
    ]

    result = service.analyze_candidate_record_resolution(candidate, records, config=_balanced_resolution_config())

    assert result["severity"] == "version"
    assert result["recommended_action"] == "create_version"
    assert "create_version" in result["allowed_actions"]
    assert result["recommended_target"]["local_record_id"] == 11


def test_analyze_candidate_record_resolution_blocks_conflicting_lineage_without_version_override():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/model.glb",
        source_file_name="model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/model.glb",
        is_sandbox=True,
        concept_rec_id="7001",
    )
    records = [
        {
            "session_id": 7,
            "local_record_id": 13,
            "dataset_key_lower": "dataset",
            "normalized_source_file_path": "dataset/model.glb",
            "is_sandbox": True,
            "concept_rec_id": "9999",
            "record_status": "published",
            "record_title": "Foreign lineage",
            "version_rank": 1,
        }
    ]

    result = service.analyze_candidate_record_resolution(candidate, records, config=_balanced_resolution_config())

    assert result["severity"] == "blocker"
    assert result["recommended_action"] == "force_create_fresh"
    assert "create_version" not in result["allowed_actions"]
    assert result["reason_codes"] == ["exact_path_conflicting_lineage"]


def test_analyze_candidate_record_resolution_uses_hash_match_as_warning_without_hard_versioning():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/new-model.glb",
        source_file_name="new-model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/new-model.glb",
        is_sandbox=True,
        sha256_hash="hash-1",
    )
    records = [
        {
            "session_id": 7,
            "local_record_id": 21,
            "dataset_key_lower": "dataset",
            "normalized_source_file_path": "dataset/old-model.glb",
            "source_file_name": "old-model.glb",
            "source_sha256_hash": "hash-1",
            "is_sandbox": True,
            "concept_rec_id": "7001",
            "record_status": "published",
            "record_title": "Published record",
            "record_metadata": {"metadata": {"title": "Different title"}},
            "version_rank": 2,
        }
    ]

    result = service.analyze_candidate_record_resolution(candidate, records, config=_balanced_resolution_config())

    assert result["severity"] == "warning"
    assert result["recommended_action"] == "create_fresh_record"
    assert "exact_source_hash_match" in result["reason_codes"]


def test_analyze_candidate_record_resolution_never_promotes_metadata_only_overlap_to_version():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/new-model.glb",
        source_file_name="new-model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/new-model.glb",
        is_sandbox=True,
        metadata={
            "title": "Bronze Statue",
            "creators": [{"name": "Museum"}],
            "publication_date": "2024-01-01",
        },
    )
    records = [
        {
            "session_id": 7,
            "local_record_id": 22,
            "dataset_key_lower": "dataset",
            "normalized_source_file_path": "dataset/other-model.glb",
            "source_file_name": "other-model.glb",
            "source_sha256_hash": "",
            "is_sandbox": True,
            "concept_rec_id": "7001",
            "record_status": "published",
            "record_title": "Bronze Statue",
            "record_metadata": {
                "metadata": {
                    "title": "Bronze Statue",
                    "creators": [{"name": "Museum"}],
                    "publication_date": "2024-03-15",
                }
            },
            "version_rank": 2,
        }
    ]

    result = service.analyze_candidate_record_resolution(candidate, records, config=_balanced_resolution_config())

    assert result["recommended_action"] != "create_version"
    assert result["severity"] in {"warning", "clean"}


def test_analyze_candidate_record_resolution_recommends_repair_version_for_missing_assets():
    candidate = service.CandidateFile(
        source_file_path="/tmp/Dataset/model.glb",
        source_file_name="model.glb",
        dataset_key="Dataset",
        normalized_source_file_path="dataset/model.glb",
        is_sandbox=True,
        concept_rec_id="7001",
    )
    records = [
        {
            "session_id": 7,
            "local_record_id": 31,
            "dataset_key_lower": "dataset",
            "normalized_source_file_path": "dataset/model.glb",
            "is_sandbox": True,
            "concept_rec_id": "7001",
            "record_status": "published",
            "record_title": "Published lineage",
            "source_file_name": "model.glb",
            "version_rank": 5,
            "record_metadata": {"metadata": {"resource_type": {"type": "3dmodel"}}},
            "record_file_count": 3,
            "uploaded_file_count": 1,
            "record_files": [
                {"filename": "model.glb", "upload_status": "uploaded"},
            ],
        }
    ]

    result = service.analyze_candidate_record_resolution(candidate, records, config=_balanced_resolution_config())

    assert result["recommended_action"] == "create_version"
    assert "repair_missing_uploaded_assets" in result["reason_codes"]
