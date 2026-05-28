"""Metadata workflow support contract for the WebHDP-native stack."""

from __future__ import annotations

from typing import Any


OFFICIAL_METADATA_WORKFLOW_ID = "webhdp_native_msf"


def get_metadata_workflow_contract() -> dict[str, Any]:
    return {
        "official_workflow_id": OFFICIAL_METADATA_WORKFLOW_ID,
        "status": "active",
        "summary": (
            "WebHDP officially supports the MSF-driven metadata workflow, LOD mapping previews, "
            "output preview QA, and native pipeline execution."
        ),
        "decision": {
            "port_old_mapping_workflow": False,
            "retain_msf_lod_workflow": True,
            "retire_legacy_prepare_metadata": True,
        },
        "supported_surfaces": {
            "default_mapping": "/api/v1/msf/default-mapping",
            "metadata_for_files": "/api/v1/msf/metadata-for-files",
            "zenodo_mapping_test": "/api/v1/metadata/test-mapping",
            "edm_mapping_test": "/api/v1/edm/test-mapping",
            "iiif_mapping_test": "/api/v1/iiif/test-mapping",
            "mets_mapping_test": "/api/v1/mets/test-mapping",
            "output_preview_qa": "/api/v1/tools/output-preview/local",
            "native_pipeline_workspace": "/workflow/pipeline",
        },
        "retired_surfaces": [
            {
                "id": "legacy_prepare_metadata_for_file",
                "status": "retired",
                "reason": (
                    "The legacy HDP-Server prepare-metadata flow is no longer part of the supported "
                    "WebHDP workflow."
                ),
                "replacement": {
                    "metadata_authoring": "Use session metadata drafts and the MSF-driven LOD mapper.",
                    "preview": "Use the mapping test endpoints and /api/v1/tools/output-preview/local.",
                    "record_creation": "Create prepared local records through the local .hdpc-backed record flow.",
                },
            }
        ],
        "notes": [
            "The LodMapper UI remains supported and uses the native mapping test endpoints.",
            "Output preview QA is the supported way to validate generated EDM, IIIF, and METS artifacts before execution.",
            "Submission-time record preparation is handled inside the local .hdpc workflow rather than by a standalone legacy prepare endpoint.",
        ],
    }


def get_retired_prepare_metadata_message() -> str:
    return (
        "Legacy prepare_metadata_for_file behavior is retired. "
        "Use the WebHDP-native MSF mapping workflow, output preview QA, and local .hdpc record creation instead."
    )
