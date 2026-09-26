# constants.py
"""
Shared constants to avoid circular dependencies.
"""

PREDEFINED_PIPELINE_ID = "render"
METADATA_ONLY_PIPELINE_ID = "metadata_only"
LEGACY_PIPELINE_ALIASES = {
    "glb_simple": PREDEFINED_PIPELINE_ID,
    "full_workflow": PREDEFINED_PIPELINE_ID,
    "fast-render": PREDEFINED_PIPELINE_ID,
    "ingestion": PREDEFINED_PIPELINE_ID,
}
UPLOAD_SUBMIT_TOKEN_FIELD = "upload_submit_token"
UPLOAD_TASK_ID_FIELD = "upload_task_id"
UPLOAD_STORAGE_MODE_FIELD = "upload_storage_mode"
UPLOAD_PROGRESS_FIELD = "upload_progress"
UPLOAD_WORKER_GROUP_ID_FIELD = "upload_worker_group_id"
WORKFLOW_STATE_FIELD = "workflow_state"
RECORD_RESOLUTION_STATE_FIELD = "record_resolution_state"

PIPELINE_DEFINITION = {
    "identifier": PREDEFINED_PIPELINE_ID,
    "name": "render",
    "description": "Fast 3D Model Renderer & Zenodo Submission Pipeline",
    "status": "active",
    "modality": "3D Model",
    "processingMode": "root",
    "version": "1.1.0",
    "tags": ["3d", "zenodo", "heritage"],
    "steps": [
        {
            "id": "fast_renderer",
            "name": "Fast 3D Model Renderer",
            "description": "Generates 2D previews and thumbnails from 3D models.",
            "enabled": True,
            "parameters": {
                "resolution": 512,
                "samples": 32,
                "engine": "CYCLES",
                "transparent_background": True,
                "angle_iteration": 5,
                "batch_size": 100,
                "parallel_mode": True,
                "parallel_workers": 0
            }
        },
        {
            "id": "any_to_usdz",
            "name": "Any to USDZ Conversion",
            "description": "Converts the input model to USDZ format for AR compatibility.",
            "enabled": True,
            "parameters": {
                "scale": 1.0,
                "apply_modifiers": True
            }
        },
        {
            "id": "zenodo_draft",
            "name": "Zenodo Draft Creation",
            "description": "Creates a draft deposition on Zenodo to get persistent identifiers.",
            "enabled": True,
            "parameters": {}
        },
        {
            "id": "lod_generation",
            "name": "LOD Generation",
            "description": "Generates EDM, CIDOC-CRM, JSON-LD, IIIF, and METS/MODS metadata files.",
            "enabled": True,
            "parameters": {
                "generate_edm": True,
                "generate_iiif": True,
                "generate_mets": True
            }
        },
        {
            "id": "zenodo_upload",
            "name": "Zenodo File Upload",
            "description": "Uploads the model and all generated metadata files to Zenodo.",
            "enabled": True,
            "parameters": {
                "publish": False
            }
        }
    ],
}

METADATA_ONLY_PIPELINE_DEFINITION = {
    "identifier": METADATA_ONLY_PIPELINE_ID,
    "name": "metadata_only",
    "description": "Metadata-Only (No Processing) - Low Resource Mode",
    "status": "active",
    "modality": "3D Model",
    "processingMode": "root",
    "version": "1.0.0",
    "tags": ["metadata", "zenodo", "heritage", "low-resource"],
    "steps": [
        {
            "id": "fast_renderer",
            "name": "Fast 3D Model Renderer",
            "description": "DISABLED in Low Resource Mode",
            "enabled": False,
            "parameters": {}
        },
        {
            "id": "any_to_usdz",
            "name": "Any to USDZ Conversion",
            "description": "DISABLED in Low Resource Mode",
            "enabled": False,
            "parameters": {}
        },
        {
            "id": "zenodo_draft",
            "name": "Zenodo Draft Creation",
            "description": "Creates a draft deposition on Zenodo.",
            "enabled": True,
            "parameters": {}
        },
        {
            "id": "lod_generation",
            "name": "LOD Generation",
            "description": "Generates EDM, CIDOC-CRM, JSON-LD, IIIF, and METS/MODS metadata.",
            "enabled": True,
            "parameters": {
                "generate_edm": True,
                "generate_iiif": True,
                "generate_mets": True
            }
        },
        {
            "id": "zenodo_upload",
            "name": "Zenodo File Upload",
            "description": "Uploads original files and metadata to Zenodo.",
            "enabled": True,
            "parameters": {
                "publish": False
            }
        }
    ],
}

THREE_D_PREPUBLICATION_ANALYSIS_PIPELINE_ID = "3d_prepublication_analysis"
THREE_D_PUBLICATION_DERIVATIVES_PIPELINE_ID = "3d_publication_derivatives"
THREE_D_POINT_CLOUD_READINESS_PIPELINE_ID = "3d_point_cloud_readiness"

THREE_D_PREPUBLICATION_ANALYSIS_PIPELINE_DEFINITION = {
    "identifier": THREE_D_PREPUBLICATION_ANALYSIS_PIPELINE_ID,
    "name": "3D Prepublication Analysis",
    "description": (
        "Non-mutating analysis pipeline for 3D publication readiness. It classifies the source asset, "
        "profiles technical metadata, audits dependencies, checks geometry, scores viewer readiness, "
        "and computes durable fingerprints."
    ),
    "status": "active",
    "modality": "3D Model",
    "processingMode": "root",
    "version": "1.0.0",
    "tags": ["3d", "analysis", "qa", "prepublication", "local-container"],
    "steps": [
        {
            "id": "classify_asset",
            "component_ref": "input_file_classification",
            "name": "Classify Source Asset",
            "description": "Classify the source file for downstream QA and branching.",
            "execution_profile_ref": "builtin_default",
            "scope": "record",
            "enabled": True,
            "parameters": {},
        },
        {
            "id": "profile_model",
            "component_ref": "model_profiler",
            "name": "3D Asset Profiler",
            "description": "Extract file, geometry, material, texture, and metadata-target facts.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
            "output_actions": [
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.model_type",
                    "target_field": "model_type",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.vertex_count",
                    "target_field": "vertex_count",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.polygon_count",
                    "target_field": "polygon_count",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.point_count",
                    "target_field": "point_count",
                    "overwrite_policy": "overwrite",
                },
            ],
        },
        {
            "id": "audit_dependencies",
            "component_ref": "texture_dependency_auditor",
            "name": "Texture And Dependency Auditor",
            "description": "Check sidecar, texture, MTL, and glTF dependency completeness.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
        },
        {
            "id": "geometry_gate",
            "component_ref": "geometry_qa_gate",
            "name": "Geometry QA / Publishability Gate",
            "description": "Produce pass, manual-review, or quarantine recommendations.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
        },
        {
            "id": "viewer_readiness",
            "component_ref": "viewer_readiness_analyzer",
            "name": "Viewer Readiness / Web Delivery Analyzer",
            "description": "Score suitability for embedded web and mobile viewing.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
        },
        {
            "id": "fingerprint_model",
            "component_ref": "model_fingerprint_deduplication",
            "name": "3D Fingerprint / Deduplication Component",
            "description": "Compute stable file and geometry signatures for deduplication.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
        },
    ],
}

THREE_D_PUBLICATION_DERIVATIVES_PIPELINE_DEFINITION = {
    "identifier": THREE_D_PUBLICATION_DERIVATIVES_PIPELINE_ID,
    "name": "3D Publication Derivatives",
    "description": (
        "Explicit derivative-generation pipeline. It creates a canonical GLB-style derivative, "
        "optionally emits spatially normalized and repaired derivatives, generates a lightweight "
        "geometric LOD preview, and checks viewer readiness of the derivative path."
    ),
    "status": "active",
    "modality": "3D Model",
    "processingMode": "root",
    "version": "1.0.0",
    "tags": ["3d", "derivatives", "glb", "lod", "local-container"],
    "steps": [
        {
            "id": "classify_asset",
            "component_ref": "input_file_classification",
            "name": "Classify Source Asset",
            "description": "Classify the source file before derivative generation.",
            "execution_profile_ref": "builtin_default",
            "scope": "record",
            "enabled": True,
            "parameters": {},
        },
        {
            "id": "canonical_glb",
            "component_ref": "canonical_glb_normalizer",
            "name": "Canonical GLB Normalizer",
            "description": "Emit a canonical publication derivative without mutating the source asset.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
        },
        {
            "id": "spatial_normalization",
            "component_ref": "scale_orientation_centering_normalizer",
            "name": "Scale, Orientation, And Centering Normalizer",
            "description": "Emit a spatially normalized derivative from the canonical asset.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "artifact_file",
                    "source_step": "canonical_glb",
                    "source_output": "canonical_asset",
                }
            ],
            "parameters": {
                "target_up_axis": "Y",
                "apply_changes": True,
            },
        },
        {
            "id": "repair_derivative",
            "component_ref": "model_repair_component",
            "name": "Model Repair Component",
            "description": "Emit an explicit repaired derivative from the spatial derivative.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "artifact_file",
                    "source_step": "spatial_normalization",
                    "source_output": "normalized_asset",
                }
            ],
            "parameters": {
                "apply_repair": True,
            },
        },
        {
            "id": "geometric_lod",
            "component_ref": "geometric_lod_generator",
            "name": "Geometric LOD Generator",
            "description": "Generate a lightweight web-delivery preview derivative.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "artifact_file",
                    "source_step": "repair_derivative",
                    "source_output": "repaired_asset",
                }
            ],
            "parameters": {
                "target_ratio": 0.5,
            },
        },
        {
            "id": "viewer_readiness",
            "component_ref": "viewer_readiness_analyzer",
            "name": "Viewer Readiness / Web Delivery Analyzer",
            "description": "Score the generated LOD preview for web delivery.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "artifact_file",
                    "source_step": "geometric_lod",
                    "source_output": "lod_preview",
                }
            ],
            "parameters": {},
        },
    ],
}

THREE_D_POINT_CLOUD_READINESS_PIPELINE_DEFINITION = {
    "identifier": THREE_D_POINT_CLOUD_READINESS_PIPELINE_ID,
    "name": "3D Point Cloud Readiness",
    "description": (
        "Point-cloud focused readiness pipeline for PLY/LAS/LAZ/E57-style assets. It classifies the asset, "
        "runs point-cloud analysis, profiles technical metadata, checks viewer readiness, and fingerprints "
        "the asset for deduplication."
    ),
    "status": "active",
    "modality": "3D Point Cloud",
    "processingMode": "root",
    "version": "1.0.0",
    "tags": ["3d", "point-cloud", "analysis", "qa", "local-container"],
    "steps": [
        {
            "id": "classify_asset",
            "component_ref": "input_file_classification",
            "name": "Classify Source Asset",
            "description": "Classify mesh versus point-cloud source assets.",
            "execution_profile_ref": "builtin_default",
            "scope": "record",
            "enabled": True,
            "parameters": {},
        },
        {
            "id": "analyze_point_cloud",
            "component_ref": "point_cloud_analyzer",
            "name": "Point Cloud Analyzer",
            "description": "Extract point count, fields, and point-cloud readiness hints.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
            "output_actions": [
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.model_type",
                    "target_field": "model_type",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.point_count",
                    "target_field": "point_count",
                    "overwrite_policy": "overwrite",
                },
            ],
        },
        {
            "id": "profile_model",
            "component_ref": "model_profiler",
            "name": "3D Asset Profiler",
            "description": "Extract general technical metadata for the point-cloud asset.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
            "output_actions": [
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.model_type",
                    "target_field": "model_type",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.vertex_count",
                    "target_field": "vertex_count",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.polygon_count",
                    "target_field": "polygon_count",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.point_count",
                    "target_field": "point_count",
                    "overwrite_policy": "overwrite",
                },
            ],
        },
        {
            "id": "viewer_readiness",
            "component_ref": "viewer_readiness_analyzer",
            "name": "Viewer Readiness / Web Delivery Analyzer",
            "description": "Score point-cloud web delivery suitability.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
        },
        {
            "id": "fingerprint_model",
            "component_ref": "model_fingerprint_deduplication",
            "name": "3D Fingerprint / Deduplication Component",
            "description": "Compute stable signatures for point-cloud deduplication.",
            "execution_profile_ref": "local_docker",
            "scope": "record",
            "enabled": True,
            "input_bindings": [
                {
                    "kind": "input",
                    "target": "input_file",
                    "type": "pipeline_source_file",
                }
            ],
            "parameters": {},
        },
    ],
}

MESH_OPTIMIZATION_PIPELINE_ID = "mesh_optimization"
MESH_OPTIMIZATION_PIPELINE_DEFINITION = {
    "identifier": MESH_OPTIMIZATION_PIPELINE_ID,
    "name": "Mesh Optimization & Preview",
    "description": "Optimize static GLB models on an HPC GPU, then create previews of the optimized results. Originals are preserved. No Zenodo upload is performed.",
    "status": "active", "modality": "3D Model", "processingMode": "root", "version": "1.0.0",
    "tags": ["3d", "hpc", "optimization", "preview"],
    "steps": [
        {"id": "mesh_optimizer", "component_ref": "mesh_optimizer", "name": "Optimize model",
         "description": "Create a textured GLB derivative while keeping the original upload.",
         "execution_profile_ref": "hpc_singularity", "scope": "record", "enabled": True,
         "input_bindings": [{"kind": "input", "target": "input_file", "type": "pipeline_source_file"}],
         "parameters": {"quality": "MEDIUM", "texture_resolution": 1024}},
        {"id": "fast_renderer", "component_ref": "fast_renderer", "name": "Preview optimized model",
         "description": "Render the optimized GLB using the active HPC allocation.",
         "execution_profile_ref": "builtin_default", "scope": "record", "enabled": True,
         "input_bindings": [{"kind": "input", "target": "input_files", "type": "artifact_file",
                             "source_step": "mesh_optimizer", "source_output": "optimized_model"}],
         "parameters": {"preset": "medium", "angle-iteration": 5}},
    ],
}

GEOREFERENCING_PIPELINE_ID = "model_georeferencing"
GEOREFERENCING_PIPELINE_DEFINITION = {
    "identifier": GEOREFERENCING_PIPELINE_ID,
    "name": "3D Georeferencing & Preview",
    "description": "Align each static GLB to one reference GeoTIFF in its upload bundle on an HPC GPU, then render previews. Download the coordinate report and review the alignment overlay. Absolute elevation is not assigned; originals are preserved.",
    "status": "active", "modality": "3D Model", "processingMode": "root", "version": "1.0.0",
    "tags": ["3d", "hpc", "georeferencing", "preview"],
    "steps": [
        {"id": "georeferencer", "component_ref": "georeferencer", "name": "Align model to reference",
         "description": "Match the model footprint against a supplied orthophoto and check alignment quality.",
         "execution_profile_ref": "hpc_singularity", "scope": "record", "enabled": True,
         "input_bindings": [{"kind": "input", "target": "input_file", "type": "pipeline_source_file"},
                            {"kind": "input", "target": "reference_files", "type": "record_source_files"}],
         "parameters": {}},
        {"id": "fast_renderer", "component_ref": "fast_renderer", "name": "Preview aligned model",
         "description": "Render the aligned GLB using the active HPC allocation.",
         "execution_profile_ref": "builtin_default", "scope": "record", "enabled": True,
         "input_bindings": [{"kind": "input", "target": "input_files", "type": "artifact_file",
                             "source_step": "georeferencer", "source_output": "georeferenced_model"}],
         "parameters": {"preset": "medium", "angle-iteration": 5}},
    ],
}

OPTIONAL_3D_PIPELINE_DEFINITIONS = {
    THREE_D_PREPUBLICATION_ANALYSIS_PIPELINE_ID: THREE_D_PREPUBLICATION_ANALYSIS_PIPELINE_DEFINITION,
    THREE_D_PUBLICATION_DERIVATIVES_PIPELINE_ID: THREE_D_PUBLICATION_DERIVATIVES_PIPELINE_DEFINITION,
    THREE_D_POINT_CLOUD_READINESS_PIPELINE_ID: THREE_D_POINT_CLOUD_READINESS_PIPELINE_DEFINITION,
}

SHARED_SCAN_OPTIONS = {
    "extensions": [".obj", ".mtl", ".jpg", ".png", ".xml", ".txt"],
    "primarysourceext": ".obj",
    "bundling": {"enabled": True, "strategy": "stem_match"},
    "batchEntity": "hybrid",
    "obj_options": {"add_mtl": True, "add_textures": True, "archive_subdirectories": True},
}

# MSF (Metadata Source File) Configuration
MSF_ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MSF_MAX_FILE_SIZE_MB = 50  # 50MB limit for MSF files
MSF_CSV_DELIMITER = ";"  # Semicolon as per test data

# Default column mapping from MSF columns to Zenodo fields
# Keys are MSF column names (case-insensitive matching), values are Zenodo field keys
DEFAULT_MSF_COLUMN_MAPPING = {
    "filename": "_filename",  # Internal: used for file matching, not Zenodo
    "title": "title",
    "dc:title": "title",
    "description": "description",
    "dc:description": "description",
    "creator": "_creators_raw",  # Special handling: parsed into creators list
    "dc:creator": "_creators_raw",
    "creator affiliation": "_affiliations_raw",  # Special handling: paired with creators
    "dcterms:created": "publication_date",
    "dc:date": "publication_date",
    "dc:type": "upload_type",
    "keywords": "keywords",
    "dc:subject": "keywords",
    "dc:identifier": "_external_identifier",
    "dc:source": "_source",
    "related to": "_related_to",  # Custom field, not standard Zenodo
    "dcterms:extent (mb)": "_file_size_mb",  # Informational only
    "reference system": "_reference_system",  # Custom field
    "units": "_units",  # Custom field
    "intended usage": "intended_usage",
    "edm:intendedusage": "intended_usage",
    "digital source type": "digital_source_type",
    "schema:digitalsourcetype": "digital_source_type",
    "model type": "model_type",
    "model_type": "model_type",
    "vertex count": "vertex_count",
    "edm:vertexcount": "vertex_count",
    "polygon count": "polygon_count",
    "edm:polygoncount": "polygon_count",
    "point count": "point_count",
    "edm:pointcount": "point_count",
    "extent": "extent",
    "dcterms:extent": "extent",
}

# Upload type mapping from MSF values to Zenodo vocabulary
MSF_UPLOAD_TYPE_MAPPING = {
    "virtual models": "dataset",
    "dataset": "dataset",
    "image": "image",
    "publication": "publication",
    "software": "software",
    "video": "video",
    "other": "other",
}
