"""Routes for in-app documentation browsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from flask import Blueprint, send_from_directory

from api_utils import APIResponse


docs_bp = Blueprint("docs", __name__)

# Resolve repository root from this file: routes/docs_routes.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = PROJECT_ROOT / "docs"


@dataclass(frozen=True)
class DocEntry:
    doc_id: str
    title: str
    category: str
    audience: str
    description: str
    rel_path: str
    sort_order: int = 100


VALID_DOC_AUDIENCES = {"beginner", "user", "operator", "developer", "all"}
VALID_DOC_CATEGORIES = {
    "start-here",
    "workflows",
    "account-security",
    "reference",
    "operations",
    "development",
    "video-guides",
}


VIDEO_GUIDE_DOCS: List[DocEntry] = [
    DocEntry(
        doc_id="release-walkthrough-videos",
        title="Release Walkthrough Videos",
        category="video-guides",
        audience="all",
        description="Index of accepted alpha walkthrough recordings grouped by workflow.",
        rel_path="guides/video_guides/release_walkthroughs.md",
        sort_order=60,
    ),
    DocEntry(
        doc_id="walkthrough-installation-setup",
        title="Walkthroughs: Installation And Setup",
        category="video-guides",
        audience="beginner",
        description="Clone, Docker startup, health checks, and first-time setup walkthroughs.",
        rel_path="guides/video_guides/installation_and_setup.md",
        sort_order=61,
    ),
    DocEntry(
        doc_id="walkthrough-publication-processing",
        title="Walkthroughs: Publication And Processing",
        category="video-guides",
        audience="user",
        description="Upload, MSF preflight, pipeline execution, records, provenance, and persisted validation walkthroughs.",
        rel_path="guides/video_guides/publication_and_processing.md",
        sort_order=62,
    ),
    DocEntry(
        doc_id="walkthrough-metadata-retrieval",
        title="Walkthroughs: Metadata And Retrieval",
        category="video-guides",
        audience="user",
        description="EDM validation, Zenodo credentials, OAI harvest, and account retrieval walkthroughs.",
        rel_path="guides/video_guides/metadata_and_retrieval.md",
        sort_order=63,
    ),
    DocEntry(
        doc_id="walkthrough-public-operations",
        title="Walkthroughs: Public Records And Operations",
        category="video-guides",
        audience="operator",
        description="Public record, oEmbed, cloud mirror, and admin observability walkthroughs.",
        rel_path="guides/video_guides/public_records_and_operations.md",
        sort_order=64,
    ),
    DocEntry(
        doc_id="walkthrough-components-development",
        title="Walkthroughs: Components And Development",
        category="video-guides",
        audience="developer",
        description="HDP Component Playground and component test walkthroughs.",
        rel_path="guides/video_guides/components_and_development.md",
        sort_order=65,
    ),
]


DOCS_CATALOG: List[DocEntry] = [
    DocEntry(
        doc_id="portal",
        title="Documentation Portal",
        category="start-here",
        audience="beginner",
        description="Entry point and navigation map for all documentation.",
        rel_path="README.md",
        sort_order=1,
    ),
    DocEntry(
        doc_id="docker-quickstart",
        title="Docker Quickstart",
        category="start-here",
        audience="beginner",
        description="Best-practice fresh-clone path to a safe local Docker WebHDP instance.",
        rel_path="guides/docker_quickstart.md",
        sort_order=2,
    ),
    DocEntry(
        doc_id="architecture",
        title="System Architecture",
        category="reference",
        audience="developer",
        description="System components, data flow, lifecycle rationale, and traceability surfaces.",
        rel_path="architecture/system_architecture.md",
        sort_order=70,
    ),
    DocEntry(
        doc_id="hdpc-schema",
        title="HDPC Schema",
        category="reference",
        audience="developer",
        description="Canonical .hdpc SQLite schema, migration rules, and shared-export boundaries.",
        rel_path="architecture/hdpc_schema.md",
        sort_order=75,
    ),
    DocEntry(
        doc_id="developer-onboarding",
        title="Developer Onboarding",
        category="development",
        audience="developer",
        description="First-hour setup, contribution tracks, first-change guidance, and common pitfalls.",
        rel_path="development/onboarding.md",
        sort_order=20,
    ),
    DocEntry(
        doc_id="devcontainer",
        title="Devcontainer Setup",
        category="development",
        audience="developer",
        description="Ready VS Code/Codespaces environment for Python, Node, uv, Docker, and onboarding checks.",
        rel_path="development/devcontainer.md",
    ),
    DocEntry(
        doc_id="first-pr-walkthrough",
        title="First PR Walkthrough",
        category="development",
        audience="developer",
        description="Developer first contribution path from workspace health check to a focused first review.",
        rel_path="development/first_pr_walkthrough.md",
    ),
    DocEntry(
        doc_id="developer-troubleshooting",
        title="Developer Troubleshooting Decision Tree",
        category="development",
        audience="developer",
        description="Developer failure-mode guide for doctor, frontend, API, auth, golden workflow, Docker, and Devcontainer issues.",
        rel_path="development/troubleshooting_decision_tree.md",
    ),
    DocEntry(
        doc_id="contributor-architecture-map",
        title="Contributor Architecture Map",
        category="development",
        audience="developer",
        description="Developer ownership map for frontend, Flask routes, services, models, tasks, .hdpc, and external integrations.",
        rel_path="development/architecture_map.md",
    ),
    DocEntry(
        doc_id="developer-glossary",
        title="Developer Glossary",
        category="development",
        audience="developer",
        description="Developer vocabulary for workflow, metadata, .hdpc, permissions, background work, Zenodo, and onboarding tools.",
        rel_path="development/developer_glossary.md",
    ),
    DocEntry(
        doc_id="pr-scope-examples",
        title="PR Size And Scope Examples",
        category="development",
        audience="developer",
        description="Developer examples for reviewable PR size, splitting work, ADR triggers, and verification lists.",
        rel_path="development/pr_scope_examples.md",
    ),
    DocEntry(
        doc_id="known-development-warnings",
        title="Known Development Warnings",
        category="development",
        audience="developer",
        description="Developer triage guide for known SQLAlchemy, Vitest, Browserslist, npm, uv, Docker, and Devcontainer warnings.",
        rel_path="development/known_warnings.md",
    ),
    DocEntry(
        doc_id="contributor-handbook",
        title="Contributor Handbook",
        category="development",
        audience="developer",
        description="Codebase map, layering rules, local setup, testing matrix, and review expectations.",
        rel_path="development/contributor_handbook.md",
    ),
    DocEntry(
        doc_id="developer-examples",
        title="Developer Examples Cookbook",
        category="development",
        audience="developer",
        description="Copyable patterns for backend, frontend, tests, docs, configuration, and PRs.",
        rel_path="development/examples.md",
    ),
    DocEntry(
        doc_id="webhdp-link",
        title="WebHDP-Link Application Integration",
        category="development",
        audience="all",
        description="Connect applications to managed pipelines, use hosted processing pages, and run the three prototypes.",
        rel_path="guides/webhdp_link.md",
    ),
    DocEntry(
        doc_id="model-publication",
        title="Prepare a 3D Model for Zenodo Sandbox",
        category="workflows",
        audience="all",
        description="Prepare a sample or upload a 3D model, follow the CPU queue, and review its Sandbox draft.",
        rel_path="guides/model_publication.md",
    ),
    DocEntry(
        doc_id="zenodo-community-components",
        title="Published Zenodo Community Components",
        category="workflows",
        audience="all",
        description="Install the published components, inspect metadata and geometry, validate files, export HDPC data, and build native pipelines.",
        rel_path="guides/zenodo_community_components.md",
    ),
    DocEntry(
        doc_id="hmsm-components",
        title="HMSM Studio Components",
        category="workflows",
        audience="all",
        description="Digitize carrier scans, interpret MIDI, and generate carrier layouts in Playground.",
        rel_path="guides/hmsm_components.md",
    ),
    DocEntry(
        doc_id="hdp-component-installation",
        title="HDP Component Installation and Upgrades",
        category="operations",
        audience="operator",
        description="Install pinned component runtimes and preserve the registry through a WebHDP upgrade.",
        rel_path="guides/hdp_component_hpc_installation.md",
    ),
    DocEntry(
        doc_id="historic-reconstruction",
        title="Historic Reconstruction Components and Pipelines",
        category="workflows",
        audience="all",
        description="Prepare scene archives, reconstruct photographs, georeference models, and install the native component recipes.",
        rel_path="guides/historic_reconstruction.md",
    ),
    DocEntry(
        doc_id="historic-reconstruction-research",
        title="Historic Reconstruction Research Runtime",
        category="operations",
        audience="operator",
        description="Provision pinned source, model weights and dependencies for the six original research stages.",
        rel_path="guides/historic_reconstruction_research.md",
    ),
    DocEntry(
        doc_id="historic-reconstruction-evaluation",
        title="Historic Reconstruction Source Evaluation",
        category="development",
        audience="developer",
        description="Source inventory, scientific workflow mapping, portability findings and validation boundaries.",
        rel_path="development/historic_reconstruction_evaluation.md",
    ),
    DocEntry(
        doc_id="first-hdp-component",
        title="Build Your First HDP Component",
        category="development",
        audience="developer",
        description="Step-by-step guide for turning an ordinary container into a manifest-backed HDP Component.",
        rel_path="development/first_hdp_component.md",
    ),
    DocEntry(
        doc_id="hdp-component-manifest-specification",
        title="HDP Component Manifest Specification",
        category="development",
        audience="developer",
        description="Normative component.yaml field contract, runtime contract, UI metadata, validation rules, and best-practice checklist.",
        rel_path="development/hdp_component_manifest_specification.md",
    ),
    DocEntry(
        doc_id="hdp-component-publishing-guide",
        title="HDP Component Publishing Guide",
        category="development",
        audience="developer",
        description="Detailed release, artifact, index, Git, Zenodo, trust, and verification workflow for sharing HDP Components.",
        rel_path="development/hdp_component_publishing_guide.md",
    ),
    DocEntry(
        doc_id="good-first-changes",
        title="Good First Changes",
        category="development",
        audience="developer",
        description="Scoped starter tasks and checks for new WebHDP contributors.",
        rel_path="development/good_first_changes.md",
    ),
    DocEntry(
        doc_id="golden-workflow",
        title="Golden Sample Workflow",
        category="development",
        audience="developer",
        description="Local fixture-backed scan, .hdpc, and MSF confidence check for onboarding.",
        rel_path="development/golden_workflow.md",
    ),
    DocEntry(
        doc_id="architecture-decisions",
        title="Architecture Decision Records",
        category="development",
        audience="developer",
        description="Short records explaining important WebHDP architecture decisions.",
        rel_path="development/adr/README.md",
    ),
    DocEntry(
        doc_id="user-guide",
        title="End-to-End User Guide",
        category="start-here",
        audience="beginner",
        description="Step-by-step workflow guide explaining both actions and rationale.",
        rel_path="guides/end_to_end_user_guide.md",
        sort_order=3,
    ),
    DocEntry(
        doc_id="workflows",
        title="WebHDP Workflow Guide",
        category="workflows",
        audience="all",
        description="Task-based index for publication, retrieval, credentials, operations, video walkthroughs, and developer workflow checks.",
        rel_path="guides/workflows.md",
        sort_order=20,
    ),
    DocEntry(
        doc_id="common-workflow-recipes",
        title="Common Workflow Recipes",
        category="workflows",
        audience="user",
        description="Single records, batch metadata review, model derivatives, media-specific exports, and recovery.",
        rel_path="guides/common-workflow-recipes.md",
        sort_order=19,
    ),
    DocEntry(
        doc_id="metadata-generation-reliability",
        title="Reliable Metadata Generation",
        category="workflows",
        audience="all",
        description="Format profiles, validation limits, reproducibility, and metadata recovery.",
        rel_path="lod-generation-reliability.md",
        sort_order=19,
    ),
    DocEntry(
        doc_id="workflow-inventory",
        title="Complete Workflow Inventory",
        category="workflows",
        audience="all",
        description="Complete workflow coverage map for UI, API, background jobs, native pipelines, and operator scripts.",
        rel_path="workflows/README.md",
        sort_order=21,
    ),
    DocEntry(
        doc_id="workflow-access-setup-identity",
        title="Workflows: Access, Setup, And Identity",
        category="workflows",
        audience="all",
        description="Setup, reset, authentication, MFA, onboarding, account profile, and recovery-code workflows.",
        rel_path="workflows/access-setup-identity.md",
        sort_order=22,
    ),
    DocEntry(
        doc_id="workflow-public-docs-profiles",
        title="Workflows: Public, Docs, And Profiles",
        category="workflows",
        audience="all",
        description="Documentation center, public pages, legal pages, public record pages, embeds, oEmbed, and profiles.",
        rel_path="workflows/public-docs-profiles.md",
        sort_order=23,
    ),
    DocEntry(
        doc_id="workflow-publication-upload-msf",
        title="Workflows: Publication, Upload, And MSF",
        category="workflows",
        audience="user",
        description="Main publication, ingestion, upload recovery, streaming upload, MSF QA, repair, and record resolution.",
        rel_path="workflows/publication-upload-msf.md",
        sort_order=24,
    ),
    DocEntry(
        doc_id="workflow-metadata-standards-templates",
        title="Workflows: Metadata, Standards, And Templates",
        category="workflows",
        audience="user",
        description="Metadata drafts, mapping tests, EDM/IIIF/METS, LOD preview, output QA, and template management.",
        rel_path="workflows/metadata-standards-templates.md",
        sort_order=25,
    ),
    DocEntry(
        doc_id="workflow-pipelines-components-playground",
        title="Workflows: Pipelines, Components, And Playground",
        category="workflows",
        audience="developer",
        description="Built-in pipelines, native pipeline platform, component registry/import, Pipeline Constructor, and Playground.",
        rel_path="workflows/pipelines-components-playground.md",
        sort_order=26,
    ),
    DocEntry(
        doc_id="workflow-3d-hdp-component-lifecycle",
        title="Workflows: 3D HDP Component Lifecycle",
        category="workflows",
        audience="developer",
        description="Create, validate, distribute, install, and smoke-test external 3D HDP Components for local Docker or HPC SIF execution.",
        rel_path="workflows/3d-hdp-component-lifecycle.md",
        sort_order=27,
    ),
    DocEntry(
        doc_id="workflow-3d-analysis-processing-pipelines",
        title="Workflows: 3D Analysis And Processing Pipelines",
        category="workflows",
        audience="operator",
        description="Optional 3D prepublication analysis, publication derivative, point-cloud readiness, constructor execution, and run artifact review workflows.",
        rel_path="workflows/3d-analysis-processing-pipelines.md",
        sort_order=28,
    ),
    DocEntry(
        doc_id="workflow-sessions-records-provenance",
        title="Workflows: Sessions, Records, And Provenance",
        category="workflows",
        audience="user",
        description="Session governance, records, explorers, provenance, downloads, versioning, batch operations, and dataset integrity.",
        rel_path="workflows/sessions-records-provenance.md",
        sort_order=29,
    ),
    DocEntry(
        doc_id="workflow-zenodo-retrieval-communities",
        title="Workflows: Zenodo Retrieval And Communities",
        category="workflows",
        audience="operator",
        description="Zenodo account retrieval, schedules, compaction, community batch operations, moderation, and migration.",
        rel_path="workflows/zenodo-retrieval-communities.md",
        sort_order=30,
    ),
    DocEntry(
        doc_id="workflow-institutions-credentials-governance",
        title="Workflows: Institutions, Credentials, And Governance",
        category="workflows",
        audience="operator",
        description="Personal and institution credentials, sharing, institution membership, community policy, and admin user governance.",
        rel_path="workflows/institutions-credentials-governance.md",
        sort_order=31,
    ),
    DocEntry(
        doc_id="workflow-hpc-cloud-storage",
        title="Workflows: HPC, Cloud, And Storage",
        category="workflows",
        audience="operator",
        description="HPC access, HPC-Link allocations, staging, diagnostics, storage modes, cloud tests, and local/HPC component installation.",
        rel_path="workflows/hpc-cloud-storage.md",
        sort_order=32,
    ),
    DocEntry(
        doc_id="workflow-hpc-batch-automation",
        title="Workflows: HPC Batch Automation",
        category="workflows",
        audience="operator",
        description="Unattended chunked HPC processing with scheduler retries, tmux observation, artifact gates, recovery queues, and reporting.",
        rel_path="workflows/hpc-batch-automation.md",
        sort_order=33,
    ),
    DocEntry(
        doc_id="workflow-admin-operations-observability",
        title="Workflows: Admin Operations And Observability",
        category="workflows",
        audience="operator",
        description="Admin submissions, session monitoring, configuration, backups, observability, readiness, and cleanup.",
        rel_path="workflows/admin-operations-observability.md",
        sort_order=34,
    ),
    DocEntry(
        doc_id="workflow-issues-notifications",
        title="Workflows: Issues And Notifications",
        category="workflows",
        audience="all",
        description="Issue reporting, triage, comments, code-reference refresh, notifications, delivery audit, digest, and cleanup.",
        rel_path="workflows/issues-notifications.md",
        sort_order=35,
    ),
    DocEntry(
        doc_id="workflow-developer-operator-scripts",
        title="Workflows: Developer And Operator Scripts",
        category="workflows",
        audience="developer",
        description="Developer status, golden workflow, doctor, API/docs checks, release checks, maintenance scripts, HPC scripts, and agent CLI.",
        rel_path="workflows/developer-operator-scripts.md",
        sort_order=36,
    ),
    DocEntry(
        doc_id="workflow-source-surface-coverage",
        title="Workflows: Source Surface Coverage",
        category="workflows",
        audience="developer",
        description="Audit checklist mapping frontend routes, backend route families, Celery tasks, native pipelines, and scripts to workflow documents.",
        rel_path="workflows/source-surface-coverage.md",
        sort_order=37,
    ),
    DocEntry(
        doc_id="zenodo-api-keys",
        title="Zenodo API Keys",
        category="account-security",
        audience="user",
        description="Create, add, validate, share, and rotate Zenodo Sandbox and Production keys.",
        rel_path="guides/zenodo_api_keys.md",
        sort_order=10,
    ),
    DocEntry(
        doc_id="security-and-credentials",
        title="Security and Credentials",
        category="account-security",
        audience="all",
        description="How WebHDP protects passwords, recovery codes, Zenodo keys, and shared credential access.",
        rel_path="guides/security_and_credentials.md",
        sort_order=11,
    ),
    DocEntry(
        doc_id="account-usage",
        title="Account access, usage and limits",
        category="account-security",
        audience="user",
        description="Check workspace permissions, upload and processing limits, and HPC allocations.",
        rel_path="guides/account_usage.md",
        sort_order=12,
    ),
    DocEntry(
        doc_id="operations",
        title="Operations and Setup Guide",
        category="operations",
        audience="operator",
        description="Deployment, setup, runbook, and release readiness checklist.",
        rel_path="guides/operations_and_setup_guide.md",
        sort_order=40,
    ),
    DocEntry(
        doc_id="upgrade-alpha4",
        title="Upgrade WebHDP to v0.1.0-alpha.4",
        category="operations",
        audience="operator",
        description="Rehearse the database migration, account continuity and optional runtime checks before rollout.",
        rel_path="guides/upgrade_alpha4.md",
        sort_order=41,
    ),
    DocEntry(
        doc_id="hpc-single-gpu-setup",
        title="HPC Single-GPU Setup",
        category="operations",
        audience="operator",
        description="Portable Singularity/Apptainer setup for running WebHDP on one HPC node, including side-by-side Draco test roots.",
        rel_path="guides/hpc_single_gpu_setup_guide.md",
        sort_order=41,
    ),
    DocEntry(
        doc_id="hpc-local-mode-setup",
        title="HPC Local-Mode Setup",
        category="operations",
        audience="operator",
        description="Best-practice HPC local-mode setup without public server deployment or HPC-Link.",
        rel_path="guides/hpc_local_mode_setup.md",
        sort_order=42,
    ),
    DocEntry(
        doc_id="restore-drill-checklist",
        title="Restore Drill Checklist",
        category="operations",
        audience="operator",
        description="Checklist for proving backup restore into an isolated target root before release.",
        rel_path="guides/restore_drill_checklist.md",
        sort_order=43,
    ),
    DocEntry(
        doc_id="zenodo-account-retrieval",
        title="Zenodo Account Deep Retrieval",
        category="workflows",
        audience="user",
        description="Retrieve published records and drafts into persistent explorer-only .hdpc shards.",
        rel_path="guides/zenodo_account_retrieval.md",
        sort_order=30,
    ),
    DocEntry(
        doc_id="zenodo-oai-harvest",
        title="Zenodo OAI Harvest",
        category="workflows",
        audience="user",
        description="Harvest public Zenodo OAI-PMH metadata into explorer-only .hdpc shard collections.",
        rel_path="guides/zenodo_oai_harvest.md",
        sort_order=31,
    ),
    DocEntry(
        doc_id="local-edm-validator",
        title="Local EDM Validator",
        category="operations",
        audience="operator",
        description="Managed local EDM validator deployment, status metadata, persistence, and troubleshooting.",
        rel_path="guides/local_edm_validator.md",
        sort_order=47,
    ),
    DocEntry(
        doc_id="storage-modes",
        title="Storage Modes Architecture",
        category="reference",
        audience="operator",
        description="Storage-mode constraints for upload, processing, mirroring, and downloads.",
        rel_path="storage_modes_architecture.md",
        sort_order=76,
    ),
    DocEntry(
        doc_id="docker-deployment",
        title="Docker Deployment Guide",
        category="operations",
        audience="operator",
        description="Docker deployment variants and operational setup notes.",
        rel_path="docker_deployment_guide.md",
        sort_order=48,
    ),
    DocEntry(
        doc_id="cloud-storage",
        title="Cloud Storage",
        category="operations",
        audience="operator",
        description="Cloud storage configuration, mirroring behavior, and download availability.",
        rel_path="cloud_storage.md",
        sort_order=49,
    ),
    DocEntry(
        doc_id="renderer-configuration",
        title="Renderer Configuration",
        category="operations",
        audience="operator",
        description="Renderer setup, tuning, and diagnostics for generated visual outputs.",
        rel_path="renderer_configuration.md",
        sort_order=50,
    ),
    DocEntry(
        doc_id="external-standards-links",
        title="External Standards Links",
        category="reference",
        audience="developer",
        description="Official upstream links for EDM, IIIF, METS/MODS, and Zenodo standards documentation.",
        rel_path="standards_links.md",
        sort_order=74,
    ),
    DocEntry(
        doc_id="planned-future-updates",
        title="Future Roadmap And Planned Updates",
        category="reference",
        audience="all",
        description="Post-alpha roadmap for sustainability, architecture transition, interoperability, cloud transfer, embedded intelligence, multi-instance state transfer, HITL design, collections, and seeding.",
        rel_path="guides/planned_future_updates.md",
        sort_order=91,
    ),
    DocEntry(
        doc_id="troubleshooting",
        title="Troubleshooting Guide",
        category="operations",
        audience="all",
        description="Failure patterns, diagnostics, and recovery procedures.",
        rel_path="guides/troubleshooting.md",
        sort_order=45,
    ),
    DocEntry(
        doc_id="glossary",
        title="Glossary",
        category="reference",
        audience="beginner",
        description="Shared vocabulary for scientific and technical audiences.",
        rel_path="guides/glossary.md",
        sort_order=80,
    ),
    DocEntry(
        doc_id="api-reference",
        title="WebHDP API Reference",
        category="reference",
        audience="developer",
        description="Complete route-level API documentation for WebHDP.",
        rel_path="api/webhdp_api_reference.md",
        sort_order=72,
    ),
    DocEntry(
        doc_id="api-examples",
        title="WebHDP API Examples",
        category="reference",
        audience="developer",
        description="Practical request/response examples for key integration flows.",
        rel_path="api/webhdp_api_examples.md",
        sort_order=73,
    ),
    *VIDEO_GUIDE_DOCS,
]

CATALOG_BY_ID: Dict[str, DocEntry] = {entry.doc_id: entry for entry in DOCS_CATALOG}


def _resolve_catalog_path(entry: DocEntry) -> Path | None:
    """Resolve and validate a catalog markdown path under docs root."""
    resolved = (DOCS_ROOT / entry.rel_path).resolve()

    if DOCS_ROOT != resolved and DOCS_ROOT not in resolved.parents:
        return None

    if not resolved.exists() or not resolved.is_file() or resolved.suffix.lower() != ".md":
        return None

    return resolved


def _word_count(markdown_text: str) -> int:
    return len(markdown_text.split())


@docs_bp.route("/index", methods=["GET"])
def get_docs_index():
    """Return catalog metadata for frontend documentation navigation."""
    docs = []

    for entry in DOCS_CATALOG:
        resolved = _resolve_catalog_path(entry)
        if not resolved:
            continue

        stat = resolved.stat()
        docs.append(
            {
                "id": entry.doc_id,
                "title": entry.title,
                "category": entry.category,
                "audience": entry.audience,
                "description": entry.description,
                "path": entry.rel_path,
                "sort_order": entry.sort_order,
                "updated_at": int(stat.st_mtime),
            }
        )

    return APIResponse.success(data={"documents": docs})


@docs_bp.route("/content/<doc_id>", methods=["GET"])
def get_doc_content(doc_id: str):
    """Return markdown content and metadata for a specific documentation page."""
    entry = CATALOG_BY_ID.get(doc_id)
    if not entry:
        return APIResponse.not_found("Documentation page not found")

    resolved = _resolve_catalog_path(entry)
    if not resolved:
        return APIResponse.not_found("Documentation source file not available")

    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return APIResponse.server_error("Documentation file encoding is invalid")
    except OSError as exc:
        return APIResponse.server_error(f"Failed to read documentation file: {exc}")

    words = _word_count(content)
    read_time_minutes = max(1, round(words / 220))

    return APIResponse.success(
        data={
            "document": {
                "id": entry.doc_id,
                "title": entry.title,
                "category": entry.category,
                "audience": entry.audience,
                "description": entry.description,
                "path": entry.rel_path,
                "sort_order": entry.sort_order,
                "word_count": words,
                "estimated_read_time_min": read_time_minutes,
                "content": content,
            }
        }
    )


@docs_bp.route("/assets/<path:asset_path>", methods=["GET"])
def get_doc_asset(asset_path: str):
    """Serve documentation assets (videos/images) located under docs/."""
    candidates = [
        (DOCS_ROOT / asset_path).resolve(),
        (DOCS_ROOT / "assets" / asset_path).resolve(),
    ]

    for resolved in candidates:
        if DOCS_ROOT != resolved and DOCS_ROOT not in resolved.parents:
            continue

        if resolved.exists() and resolved.is_file():
            return send_from_directory(resolved.parent, resolved.name)

    return APIResponse.not_found("Documentation asset not found")
