import os
import json
import hashlib
import subprocess
from datetime import datetime
from unittest.mock import patch

import pytest
import yaml
from flask import Flask

from database.database import db
from database.models import ComponentDefinition, ComponentVersion, HpcComponentInstallation, PipelineDefinition, PipelineVersion, User, UserRole
from exceptions import ValidationError
from services.component_index_service import ComponentIndexService
from services.hpc_component_installer_service import REPO_ROOT, HpcComponentInstallerService
from services.hpc_link_client import HpcLinkClient
from services.native_pipeline_system import NativePipelineSystemService


MANIFEST = {
    "metadata": {
        "name": "example_validator",
        "label": "Example Validator",
        "version": "1.0.0",
        "description": "Validate example assets.",
    },
    "inputs": [{"name": "input_file", "type": "file_path", "required": True}],
    "outputs": [{"name": "report", "type": "file_path"}],
    "execution": {
        "profiles": [
            {
                "id": "hpc_singularity",
                "adapter": "hpc_link",
                "handler": "generic_singularity_component",
                "runtime": "singularity",
                "image": "",
                "entrypoint": ["python", "/app/component.py"],
            }
        ]
    },
    "compatibility": {"playground": {"enabled": True}},
}

LOCAL_CONTAINER_MANIFEST = {
    "metadata": {
        "name": "local_profiler",
        "label": "Local Profiler",
        "version": "1.0.0",
        "description": "Profile assets in a local Docker container.",
    },
    "inputs": [{"name": "input_file", "type": "file_path", "required": True}],
    "outputs": [{"name": "report", "type": "file_path"}],
    "execution": {
        "profiles": [
            {
                "id": "local_docker",
                "adapter": "container_cli",
                "runtime": "docker",
                "image": "example/local-profiler:1.0.0",
                "entrypoint": ["python", "/app/component.py"],
            }
        ]
    },
    "compatibility": {"playground": {"enabled": True}},
}

LOCAL_CONTAINER_MANIFEST_WITH_TEST = {
    **LOCAL_CONTAINER_MANIFEST,
    "install": {
        "strategies": [
            {
                "id": "local_container",
                "runtime": "docker",
                "profile": "local_docker",
                "image": "example/local-profiler:1.0.0",
            }
        ],
        "test": {
            "files": [{"name": "sample.glb", "content_base64": "SGVsbG8="}],
            "inputs": {"input_file": "sample.glb"},
            "parameters": {"strict": False},
        },
    },
}

DUAL_STRATEGY_MANIFEST = {
    "metadata": {
        "name": "dual_component",
        "label": "Dual Component",
        "version": "1.0.0",
        "description": "Installable locally and on HPC.",
    },
    "inputs": [{"name": "input_file", "type": "file_path", "required": True}],
    "outputs": [{"name": "report", "type": "file_path"}],
    "execution": {
        "profiles": [
            {
                "id": "local_docker",
                "adapter": "container_cli",
                "runtime": "docker",
                "image": "example/dual-component:1.0.0",
                "entrypoint": ["python", "/app/component.py"],
            },
            {
                "id": "hpc_singularity",
                "adapter": "hpc_link",
                "handler": "generic_singularity_component",
                "runtime": "singularity",
                "image": "",
                "entrypoint": ["python", "/app/component.py"],
            },
        ]
    },
    "install": {
        "strategies": [
            {"id": "local_container", "runtime": "docker", "profile": "local_docker", "image": "example/dual-component:1.0.0"},
            {"id": "hpc_sif", "runtime": "singularity", "profile": "hpc_singularity"},
        ]
    },
    "compatibility": {"playground": {"enabled": True}},
}


@pytest.fixture()
def flask_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()

    class FakeHpcClient:
        def __init__(self):
            self.posts = []
            self.validate_response = {"success": True, "checks": {"singularity": {"success": True}}}

        def post(self, path, payload, timeout=None):
            self.posts.append((path, payload, timeout))
            if path.endswith("/validate-install"):
                response = dict(self.validate_response)
                if payload.get("sif_sha256"):
                    checks = dict(response.get("checks") or {})
                    checks["sif_checksum"] = {
                        "success": True,
                        "expected_sha256": payload["sif_sha256"],
                        "actual_sha256": payload["sif_sha256"],
                    }
                    response["checks"] = checks
                return response
            if path.endswith("/install"):
                return {
                    "success": True,
                    "sif_remote_path": "/work/apps/webhdp/components/example_validator/1.0.0/component.sif",
                    "sif_sha256": "b" * 64,
                    "remote_install_dir": "/work/apps/webhdp/components/example_validator/1.0.0",
                    "checks": {"singularity": {"success": True}},
                    "logs": {"install": {"exit_code": 0}},
                }
            raise AssertionError(f"Unexpected path {path}")

    fake_client = FakeHpcClient()

    class FakeAllocationService:
        def client(self):
            return fake_client

    app.hpc_allocation_service = FakeAllocationService()
    app.fake_hpc_client = fake_client
    app.component_index_service = ComponentIndexService()
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_validate_accepts_hpc_link_singularity_profile(flask_app):
    service = HpcComponentInstallerService()

    result = service.validate_install_payload(
        {"manifest": MANIFEST, "sif_source": "/work/components/example.sif"}
    )

    assert result["valid"] is True
    assert result["component_key"] == "example_validator"
    assert result["profile"]["handler"] == "generic_singularity_component"
    assert result["checks"]["hpc_link"]["success"] is True
    assert flask_app.fake_hpc_client.posts[-1][2] > 900


def test_validate_rejects_missing_sif_source(flask_app):
    service = HpcComponentInstallerService()

    with pytest.raises(ValidationError):
        service.validate_install_payload({"manifest": MANIFEST})


def test_validate_rejects_unsafe_remote_sif_path(flask_app):
    service = HpcComponentInstallerService()

    with pytest.raises(ValidationError):
        service.validate_install_payload({"manifest": MANIFEST, "sif_source": "../component.sif"})


def test_validate_rejects_private_sif_urls_before_forwarding(flask_app):
    service = HpcComponentInstallerService()
    sources = (
        "https://zenodo.org/files/component.sif?download=1&token=private-value",
        "https://user:private-value@zenodo.org/files/component.sif",
        "https://zenodo.org/files/component.sif#private-value",
        "https://zenodo.org/files/component.sif;token=private-value",
    )
    for source in sources:
        with pytest.raises(ValidationError) as exc:
            service.validate_install_payload({"manifest": MANIFEST, "sif_source": source})
        assert "private-value" not in str(exc.value)
    assert not flask_app.fake_hpc_client.posts
    for source in ("https://example.org/component.sif", "https://zenodo.org/files/component.sif?download=1"):
        assert service.validate_install_payload({"manifest": MANIFEST, "sif_source": source})["sif"]["sif_source"] == source


def test_validate_allows_existing_component_version_for_new_strategy(flask_app):
    definition = ComponentDefinition(
        key="example_validator",
        name="Example Validator",
        source_type="hpc_installed",
    )
    db.session.add(definition)
    db.session.flush()
    db.session.add(
        ComponentVersion(
            component_definition_id=definition.id,
            version="1.0.0",
            manifest_json="{}",
            manifest_hash="abc",
        )
    )
    db.session.commit()

    service = HpcComponentInstallerService()
    result = service.validate_install_payload({"manifest": MANIFEST, "sif_source": "/work/components/example.sif"})

    assert result["registered"] is True
    assert result["duplicate"] is False


def test_install_posts_to_hpc_link_and_imports_component(flask_app):
    user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()

    result = service.install_component(
        {"manifest": MANIFEST, "sif_source": "/work/components/example.sif"},
        user=user,
    )

    assert result["installation"]["status"] == "installed"
    assert result["component"]["key"] == "example_validator"
    assert result["component"]["profiles"][0]["adapter"] == "hpc_link"
    posted_paths = [call[0] for call in flask_app.fake_hpc_client.posts]
    assert "/api/apps/webhdp/components/validate-install" in posted_paths
    assert "/api/apps/webhdp/components/install" in posted_paths


def test_install_requires_successful_hpc_link_validation(flask_app):
    flask_app.fake_hpc_client.validate_response = {
        "success": False,
        "error": "SIF source not reachable",
    }
    user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()

    with pytest.raises(ValidationError, match="HPC-Link validation did not confirm install readiness"):
        service.install_component(
            {"manifest": MANIFEST, "sif_source": "/work/components/example.sif"},
            user=user,
        )

    posted_paths = [call[0] for call in flask_app.fake_hpc_client.posts]
    assert "/api/apps/webhdp/components/validate-install" in posted_paths
    assert "/api/apps/webhdp/components/install" not in posted_paths


def test_validate_rejects_duplicate_install_for_same_strategy(flask_app):
    user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()
    service.install_component(
        {"manifest": MANIFEST, "sif_source": "/work/components/example.sif"},
        user=user,
    )

    with pytest.raises(ValidationError, match="already installed for this strategy"):
        service.validate_install_payload({"manifest": MANIFEST, "sif_source": "/work/components/example.sif"})


@patch("services.hpc_component_installer_service.shutil.which", return_value="/usr/bin/docker")
@patch("services.hpc_component_installer_service.subprocess.run")
def test_validate_accepts_local_container_profile(mock_run, _mock_which, flask_app):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["docker", "image", "inspect"],
        returncode=0,
        stdout=json.dumps([{"Id": "sha256:" + "a" * 64}]),
        stderr="",
    )
    service = HpcComponentInstallerService()

    result = service.validate_install_payload(
        {
            "manifest": LOCAL_CONTAINER_MANIFEST,
            "install_strategy": "local_container",
            "container_image": "example/local-profiler:1.0.0",
        }
    )

    assert result["valid"] is True
    assert result["install_strategy"] == "local_container"
    assert result["profile"]["adapter"] == "container_cli"
    assert result["checks"]["local_container"]["success"] is True
    assert result["checks"]["local_container"]["policy"]["success"] is True
    mock_run.assert_called_once()


@patch("services.hpc_component_installer_service.shutil.which", return_value="/usr/bin/docker")
@patch("services.hpc_component_installer_service.subprocess.run")
def test_validate_rejects_local_container_image_outside_allowlist(mock_run, _mock_which, flask_app):
    flask_app.config["WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST"] = "ghcr.io/hdp-components/*"
    service = HpcComponentInstallerService()

    result = service.validate_install_payload(
        {
            "manifest": LOCAL_CONTAINER_MANIFEST,
            "install_strategy": "local_container",
            "container_image": "example/local-profiler:1.0.0",
        }
    )

    assert result["checks"]["local_container"]["success"] is False
    assert "allowlist" in result["checks"]["local_container"]["error"]
    mock_run.assert_not_called()


@patch("services.hpc_component_installer_service.shutil.which", return_value="/usr/bin/docker")
@patch("services.hpc_component_installer_service.subprocess.run")
def test_install_local_container_imports_component_without_hpc_link(mock_run, _mock_which, flask_app):
    image_id = "sha256:" + "a" * 64
    retention_tag = "webhdp-component-runtime:sha256-" + "a" * 64

    def docker_before_registration(command, **kwargs):
        assert ComponentDefinition.query.filter_by(key="local_profiler").first() is None
        return subprocess.CompletedProcess(
            args=command, returncode=0,
            stdout=json.dumps([{"Id": image_id}]) if command[2] == "inspect" else "", stderr="",
        )

    mock_run.side_effect = docker_before_registration
    user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()

    result = service.install_component(
        {
            "manifest": LOCAL_CONTAINER_MANIFEST,
            "install_strategy": "local_container",
            "container_image": "example/local-profiler:1.0.0",
        },
        user=user,
    )

    assert result["installation"]["status"] == "installed"
    assert result["installation"]["install_strategy"] == "local_container"
    assert result["installation"]["container_image"] == "example/local-profiler:1.0.0"
    assert result["component"]["source_type"] == "local_container_installed"
    assert result["component"]["profiles"][0]["adapter"] == "container_cli"
    assert result["installation"]["manifest"]["execution"]["profiles"][0]["image"] == image_id
    assert result["installation"]["checks"]["image_retention"] == {
        "success": True, "image_id": image_id, "retention_tag": retention_tag,
    }
    assert [call.args[0] for call in mock_run.call_args_list] == [
        ["/usr/bin/docker", "image", "inspect", "example/local-profiler:1.0.0"],
        ["/usr/bin/docker", "image", "tag", image_id, retention_tag],
        ["/usr/bin/docker", "image", "inspect", retention_tag],
    ]
    assert flask_app.fake_hpc_client.posts == []


@patch("services.hpc_component_installer_service.shutil.which", return_value="/usr/bin/docker")
@patch("services.hpc_component_installer_service.subprocess.run")
@pytest.mark.parametrize("failure", ["tag_rejected", "tag_timeout", "retained_id_mismatch", "retained_tag_missing", "invalid_image_id"])
def test_local_image_retention_failure_never_registers_component(mock_run, _mock_which, flask_app, failure):
    image_id = "sha256:" + "a" * 64
    inspected_id = "invalid-image-id" if failure == "invalid_image_id" else image_id
    responses = [subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps([{"Id": inspected_id}]), stderr="")]
    if failure == "tag_rejected":
        responses.append(subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="tag denied"))
    elif failure == "tag_timeout":
        responses.append(subprocess.TimeoutExpired(cmd="docker image tag", timeout=30))
    elif failure != "invalid_image_id":
        responses.append(subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""))
        responses.append(subprocess.CompletedProcess(
            args=[], returncode=1 if failure == "retained_tag_missing" else 0,
            stdout=json.dumps([{"Id": "sha256:" + "b" * 64}]), stderr="",
        ))
    mock_run.side_effect = responses
    user = User(email="retention@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()

    with pytest.raises(ValidationError, match="preserve|verification failed|valid immutable image ID"):
        HpcComponentInstallerService().install_component(
            {"manifest": LOCAL_CONTAINER_MANIFEST, "install_strategy": "local_container",
             "container_image": "example/local-profiler:1.0.0"}, user=user,
        )

    assert ComponentDefinition.query.filter_by(key="local_profiler").first() is None
    assert ComponentVersion.query.count() == 0
    failed = HpcComponentInstallation.query.one()
    assert failed.status == "failed"
    assert failed.component_version_id is None
    assert "image_retention" not in json.loads(failed.checks_json)
    assert mock_run.call_count == len(responses)
    assert flask_app.fake_hpc_client.posts == []


@patch("services.hpc_component_installer_service.shutil.which", return_value="/usr/bin/docker")
@patch("services.hpc_component_installer_service.subprocess.run")
@pytest.mark.parametrize("required_output", [False, True])
def test_local_container_installation_runs_manifest_smoke_test(mock_run, _mock_which, flask_app, required_output):
    mock_run.side_effect = [
        subprocess.CompletedProcess(args=["docker", "image", "inspect"], returncode=0, stdout=json.dumps([{"Id": "sha256:" + "a" * 64}]), stderr=""),
        subprocess.CompletedProcess(args=["docker", "image", "tag"], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(args=["docker", "image", "inspect"], returncode=0, stdout=json.dumps([{"Id": "sha256:" + "a" * 64}]), stderr=""),
        subprocess.CompletedProcess(args=["docker", "image", "inspect"], returncode=0, stdout=json.dumps([{"Id": "sha256:" + "a" * 64}]), stderr=""),
        subprocess.CompletedProcess(args=["docker", "run"], returncode=0, stdout='{"success": true}', stderr=""),
    ]
    user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()
    manifest = {
        **LOCAL_CONTAINER_MANIFEST_WITH_TEST,
        "outputs": [{"name": "report", "type": "file_path", "required": required_output}],
    }
    install_result = service.install_component(
        {
            "manifest": manifest,
            "install_strategy": "local_container",
            "container_image": "example/local-profiler:1.0.0",
        },
        user=user,
    )

    result = service.test_installation(install_result["installation"]["installation_id"])

    assert result["test"]["success"] is not required_output
    if required_output:
        assert "File output 'report' must name a file under /outputs." in result["test"]["error"]
    assert result["test"]["phase"] == "smoke_test"
    docker_run = mock_run.call_args_list[-1].args[0]
    assert docker_run[:4] == ["/usr/bin/docker", "run", "--rm", "--network"]
    assert "none" in docker_run
    assert "WEBHDP_COMPONENT_REQUEST=/tmp/webhdp/request.json" in docker_run
    assert "WEBHDP_COMPONENT_KEY=local_profiler" in docker_run
    assert "sha256:" + "a" * 64 in docker_run


@patch("services.hpc_component_installer_service.shutil.which", return_value="/usr/bin/docker")
@patch("services.hpc_component_installer_service.subprocess.run")
def test_same_component_version_can_accumulate_local_and_hpc_profiles(mock_run, _mock_which, flask_app):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["docker", "image", "inspect"],
        returncode=0,
        stdout=json.dumps([{"Id": "sha256:" + "a" * 64}]),
        stderr="",
    )
    user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()

    local_result = service.install_component(
        {
            "manifest": DUAL_STRATEGY_MANIFEST,
            "install_strategy": "local_container",
            "container_image": "example/dual-component:1.0.0",
        },
        user=user,
    )
    hpc_result = service.install_component(
        {
            "manifest": DUAL_STRATEGY_MANIFEST,
            "install_strategy": "hpc_sif",
            "sif_source": "/work/components/dual_component.sif",
        },
        user=user,
    )

    assert local_result["component"]["key"] == "dual_component"
    assert hpc_result["installation"]["install_strategy"] == "hpc_sif"
    assert hpc_result["component"]["source_type"] == "multi_strategy_installed"
    adapters = {profile["adapter"] for profile in hpc_result["component"]["profiles"]}
    assert adapters == {"container_cli", "hpc_link"}


def test_catalog_lists_local_hpc_installable_components(flask_app):
    service = HpcComponentInstallerService()

    catalog = service.list_available_catalog()
    keys = {item["component_key"] for item in catalog["components"]}

    assert "gltf_validator" in keys
    assert "zenodo_upload" not in keys
    assert "fast_renderer" not in keys
    gltf = next(item for item in catalog["components"] if item["component_key"] == "gltf_validator")
    assert gltf["installable"] is True
    assert gltf["profile"]["handler"] == "generic_singularity_component"
    assert gltf["has_smoke_test"] is True
    assert "manifest_text" in gltf


def test_catalog_lists_local_container_installable_components(flask_app):
    service = HpcComponentInstallerService()

    catalog = service.list_available_catalog(install_strategy="local_container")
    keys = {item["component_key"] for item in catalog["components"]}

    assert "gltf_validator" in keys
    gltf = next(item for item in catalog["components"] if item["component_key"] == "gltf_validator")
    assert gltf["install_strategy"] == "local_container"
    assert gltf["profile"]["adapter"] == "container_cli"
    assert gltf["profile"]["runtime"] == "docker"
    assert gltf["distribution_tier"] == "external_installable"
    assert gltf["has_smoke_test"] is True


def test_catalog_reports_malformed_manifests_without_failing(flask_app, tmp_path):
    good_dir = tmp_path / "good"
    bad_dir = tmp_path / "bad"
    good_dir.mkdir()
    bad_dir.mkdir()
    (good_dir / "component.yaml").write_text(
        """
metadata:
  name: local_validator
  version: "1.0.0"
execution:
  profiles:
    - id: hpc_singularity
      adapter: hpc_link
      handler: generic_singularity_component
      runtime: singularity
      image: ""
      entrypoint: [python, /app/component.py]
""",
        encoding="utf-8",
    )
    (bad_dir / "component.yaml").write_text("metadata: [", encoding="utf-8")

    service = HpcComponentInstallerService()
    catalog = service.list_available_catalog(tmp_path)

    assert [item["component_key"] for item in catalog["components"]] == ["local_validator"]
    assert catalog["summary"]["installable"] == 1
    assert catalog["summary"]["warnings"]
    assert "bad/component.yaml" in catalog["summary"]["warnings"][0]["source_path"]


def test_remote_component_index_lists_local_docker_entry(flask_app, tmp_path):
    manifest_text = yaml.safe_dump(LOCAL_CONTAINER_MANIFEST)
    manifest_path = tmp_path / "component.yaml"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "webhdp.component-index.v1",
                "components": [
                    {
                        "component_key": "local_profiler",
                        "version": "1.0.0",
                        "label": "Indexed Local Profiler",
                        "trust_level": "community-reviewed",
                        "manifest": {
                            "url": str(manifest_path),
                            "sha256": hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
                        },
                        "source": {
                            "url": "https://github.com/example/local-profiler",
                            "tag": "v1.0.0",
                            "commit": "abc123",
                        },
                        "zenodo": {"doi": "10.5281/zenodo.123"},
                        "artifacts": {
                            "docker": {
                                "image": "ghcr.io/hdp-components/local-profiler@sha256:abc",
                                "digest": "sha256:abc",
                                "sbom_url": "https://example.org/sbom.json",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)
    service = HpcComponentInstallerService()

    catalog = service.list_available_catalog(install_strategy="local_container", source="remote")

    assert catalog["summary"]["source"] == "remote"
    assert catalog["summary"]["warnings"] == []
    assert len(catalog["components"]) == 1
    entry = catalog["components"][0]
    assert entry["catalog_source"] == "remote_index"
    assert entry["trust_level"] == "community-reviewed"
    assert entry["git"]["tag"] == "v1.0.0"
    assert entry["zenodo"]["doi"] == "10.5281/zenodo.123"
    assert entry["container_image"] == "ghcr.io/hdp-components/local-profiler@sha256:abc"
    assert entry["docker_digest"] == "sha256:abc"
    assert entry["manifest_sha256"]


def test_remote_component_index_reports_manifest_sha_mismatch(flask_app, tmp_path):
    manifest_path = tmp_path / "component.yaml"
    manifest_path.write_text(yaml.safe_dump(LOCAL_CONTAINER_MANIFEST), encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "webhdp.component-index.v1",
                "components": [
                    {
                        "component_key": "local_profiler",
                        "version": "1.0.0",
                        "manifest": {"url": str(manifest_path), "sha256": "0" * 64},
                        "artifacts": {"docker": {"image": "example/local-profiler:1.0.0"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)
    service = HpcComponentInstallerService()

    catalog = service.list_available_catalog(install_strategy="local_container", source="remote")

    assert catalog["components"] == []
    assert "SHA-256 mismatch" in catalog["summary"]["warnings"][0]["message"]


def test_remote_component_index_reports_unsupported_schema(flask_app, tmp_path):
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"schema": "not-webhdp", "components": []}), encoding="utf-8")
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)

    result = flask_app.component_index_service.list_index_entries(refresh=True)

    assert result["components"] == []
    assert "Unsupported component index schema" in result["summary"]["warnings"][0]["message"]


def test_component_index_schema_and_example_fixture_are_loadable(flask_app):
    schema_path = REPO_ROOT / "docs" / "schemas" / "webhdp_component_index_v1.schema.json"
    fixture_path = REPO_ROOT / "docs" / "examples" / "component-index" / "index.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(fixture_path)

    result = flask_app.component_index_service.list_index_entries(refresh=True)

    assert schema["properties"]["schema"]["const"] == "webhdp.component-index.v1"
    assert fixture["schema"] == "webhdp.component-index.v1"
    assert result["summary"]["warnings"] == []
    assert result["components"][0]["component_key"] == "example_remote_validator"


def test_remote_component_index_uses_cache_for_configured_source(flask_app, tmp_path):
    manifest_text = yaml.safe_dump(LOCAL_CONTAINER_MANIFEST)
    manifest_path = tmp_path / "component.yaml"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "webhdp.component-index.v1",
                "components": [
                    {
                        "component_key": "local_profiler",
                        "version": "1.0.0",
                        "manifest": {"url": str(manifest_path)},
                        "artifacts": {"docker": {"image": "example/local-profiler:1.0.0"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)
    first = flask_app.component_index_service.list_index_entries(refresh=True)
    index_path.unlink()

    second = flask_app.component_index_service.list_index_entries()

    assert first["components"][0]["component_key"] == "local_profiler"
    assert second["components"][0]["component_key"] == "local_profiler"


def test_remote_component_index_enforces_min_trust_policy(flask_app, tmp_path):
    manifest_text = yaml.safe_dump(LOCAL_CONTAINER_MANIFEST)
    manifest_path = tmp_path / "component.yaml"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "webhdp.component-index.v1",
                "components": [
                    {
                        "component_key": "local_profiler",
                        "version": "1.0.0",
                        "trust_level": "experimental",
                        "manifest": {"url": str(manifest_path)},
                        "artifacts": {"docker": {"image": "example/local-profiler:1.0.0"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)
    flask_app.config["WEBHDP_COMPONENT_INDEX_MIN_TRUST"] = "community-reviewed"

    result = flask_app.component_index_service.list_index_entries(refresh=True)

    assert result["components"] == []
    assert result["summary"]["min_trust_level"] == "community-reviewed"
    assert "below configured minimum" in result["summary"]["warnings"][0]["message"]


def test_remote_component_index_enforces_webhdp_compatibility(flask_app, tmp_path):
    manifest_text = yaml.safe_dump(LOCAL_CONTAINER_MANIFEST)
    manifest_path = tmp_path / "component.yaml"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "webhdp.component-index.v1",
                "components": [
                    {
                        "component_key": "local_profiler",
                        "version": "1.0.0",
                        "trust_level": "trusted",
                        "compatibility": {"webhdp_min": "9.0.0"},
                        "manifest": {"url": str(manifest_path)},
                        "artifacts": {"docker": {"image": "example/local-profiler:1.0.0"}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)
    flask_app.config["WEBHDP_VERSION"] = "1.0.0"

    result = flask_app.component_index_service.list_index_entries(refresh=True)

    assert result["components"] == []
    assert "not compatible with WebHDP 1.0.0" in result["summary"]["warnings"][0]["message"]


def test_remote_component_index_normalizes_release_metadata_and_diagnostics(flask_app, tmp_path):
    manifest_text = yaml.safe_dump(LOCAL_CONTAINER_MANIFEST)
    manifest_path = tmp_path / "component.yaml"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "webhdp.component-index.v1",
                "components": [
                    {
                        "component_key": "local_profiler",
                        "version": "1.0.0",
                        "trust_level": "trusted",
                        "compatibility": {"webhdp_min": "0.1.0", "webhdp_max": "2.0.0"},
                        "manifest": {"url": str(manifest_path)},
                        "release": {
                            "url": "https://codeberg.org/example/local-profiler/releases/v1.0.0",
                            "tag": "v1.0.0",
                            "assets": [
                                {
                                    "name": "component.sif",
                                    "url": "https://example.org/releases/component.sif",
                                    "media_type": "application/vnd.sylabs.sif",
                                }
                            ],
                        },
                        "artifacts": {
                            "docker": {
                                "image": "example/local-profiler:1.0.0",
                                "sbom_url": "https://example.org/sbom.json",
                                "provenance_url": "https://example.org/provenance.intoto.jsonl",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)
    flask_app.config["WEBHDP_VERSION"] = "1.0.0"

    result = flask_app.component_index_service.list_index_entries(refresh=True)
    diagnostics = flask_app.component_index_service.diagnostics()

    entry = result["components"][0]
    assert entry["release"]["tag"] == "v1.0.0"
    assert entry["release"]["assets"][0]["name"] == "component.sif"
    assert entry["compatibility"]["status"]["compatible"] is True
    assert entry["artifacts"]["docker"]["sbom_url"] == "https://example.org/sbom.json"
    assert diagnostics["schema"] == "webhdp.component-index.v1"
    assert diagnostics["sources"][0]["cached"] is True
    assert diagnostics["sources"][0]["component_count"] == 1


def test_remote_component_index_rejects_non_https_provenance_url(flask_app, tmp_path):
    manifest_text = yaml.safe_dump(LOCAL_CONTAINER_MANIFEST)
    manifest_path = tmp_path / "component.yaml"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "schema": "webhdp.component-index.v1",
                "components": [
                    {
                        "component_key": "local_profiler",
                        "version": "1.0.0",
                        "manifest": {"url": str(manifest_path)},
                        "artifacts": {
                            "docker": {
                                "image": "example/local-profiler:1.0.0",
                                "provenance_url": "http://example.org/provenance.json",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flask_app.config["WEBHDP_COMPONENT_INDEX_SOURCES"] = str(index_path)

    result = flask_app.component_index_service.list_index_entries(refresh=True)

    assert result["components"] == []
    assert "provenance_url must use HTTPS" in result["summary"]["warnings"][0]["message"]


def test_validate_and_install_persist_index_catalog_metadata(flask_app):
    user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()
    catalog_ref = {
        "source": "/catalog/index.json",
        "component_key": "example_validator",
        "version": "1.0.0",
        "manifest_url": "/catalog/component.yaml",
    }
    sif_sha256 = "a" * 64

    result = service.install_component(
        {
            "manifest": MANIFEST,
            "sif_source": "/work/components/example.sif",
            "sif_sha256": sif_sha256,
            "catalog_ref": catalog_ref,
            "catalog_source": "remote_index",
            "trust_level": "trusted",
            "git": {"url": "https://github.com/example/component", "tag": "v1.0.0"},
            "zenodo": {"concept_doi": "10.5281/zenodo.456"},
        },
        user=user,
    )

    installation = result["installation"]
    assert installation["catalog_ref"] == catalog_ref
    assert installation["trust_level"] == "trusted"
    assert installation["sif_sha256"] == sif_sha256
    assert installation["checks"]["catalog"]["git"]["tag"] == "v1.0.0"
    validate_payload = flask_app.fake_hpc_client.posts[0][1]
    install_payload = flask_app.fake_hpc_client.posts[1][1]
    assert validate_payload["sif_sha256"] == sif_sha256
    assert install_payload["sif_sha256"] == sif_sha256


@pytest.mark.skipif(
    not os.environ.get("HPC_LINK_BASE_URL") or not os.environ.get("HPC_LINK_ACCEPTANCE_SIF_SOURCE"),
    reason="Set HPC_LINK_BASE_URL and HPC_LINK_ACCEPTANCE_SIF_SOURCE to run the real HPC-Link SIF acceptance test",
)
def test_hpc_link_acceptance_installs_prebuilt_sif_and_runs_smoke_test():
    """Opt-in acceptance test against a live HPC-Link adapter and real prebuilt SIF."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()

    class RealHpcAllocationService:
        def client(self):
            return HpcLinkClient(
                base_url=os.environ["HPC_LINK_BASE_URL"],
                token=os.environ.get("HPC_LINK_API_KEY"),
            )

    app.hpc_allocation_service = RealHpcAllocationService()
    timeout_seconds = float(os.environ.get("HPC_LINK_ACCEPTANCE_TIMEOUT_SECONDS", "7200"))

    with app.app_context():
        db.create_all()
        manifest_path = REPO_ROOT / "external_code" / "gltf_validator" / "component.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest["metadata"]["version"] = os.environ.get(
            "HPC_LINK_ACCEPTANCE_COMPONENT_VERSION",
            f"1.0.0-acceptance.{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        )
        user = User(email="acceptance-admin@example.com", role=UserRole.ADMIN, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        service = HpcComponentInstallerService()
        install_result = service.install_component(
            {
                "manifest": manifest,
                "sif_source": os.environ["HPC_LINK_ACCEPTANCE_SIF_SOURCE"],
                "timeout_seconds": timeout_seconds,
            },
            user=user,
        )
        installation = install_result["installation"]

        assert installation["status"] == "installed"
        assert installation["remote_install_dir"]
        assert installation["sif_remote_path"].endswith(".sif")

        smoke_result = service.test_installation(
            installation["installation_id"],
            {"timeout_seconds": timeout_seconds},
        )

        assert smoke_result["test"]["success"] is True
        assert smoke_result["installation"]["last_tested_at"]

        db.session.remove()
        db.drop_all()


@patch("services.hpc_component_installer_service.shutil.which", return_value="/usr/bin/docker")
@patch("services.hpc_component_installer_service.subprocess.run")
def test_install_retry_is_idempotent_and_missing_smoke_test_is_skipped(mock_run, _which, flask_app):
    from uuid import uuid4
    from services.registry_lock import OperationConflict
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps([{"Id": "sha256:" + "a" * 64}]), stderr="")
    user = User(email="retry@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()
    payload = {"request_id": str(uuid4()), "manifest": LOCAL_CONTAINER_MANIFEST, "install_strategy": "local_container", "container_image": "example/local-profiler:1.0.0"}
    first = service.install_component(payload, user=user)
    retry = service.install_component(payload, user=user)
    assert first["installation"]["installation_id"] == retry["installation"]["installation_id"]
    assert retry["reused"] is True
    assert mock_run.call_count == 3
    with pytest.raises(OperationConflict):
        service.install_component({**payload, "container_image": "different:tag"}, user=user)
    result = service.test_installation(first["installation"]["installation_id"])
    assert result["test"]["status"] == "skipped"
    assert result["test"]["success"] is None
    assert result["test"]["readiness_confirmed"] is True


def test_interrupted_remote_install_reconciles_without_reposting(flask_app):
    from uuid import uuid4
    from exceptions import APITimeoutError
    from unittest.mock import Mock
    user = User(email="interrupted@example.com", role=UserRole.ADMIN, is_verified=True)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    service = HpcComponentInstallerService()
    payload = {"request_id": str(uuid4()), "manifest": MANIFEST, "sif_source": "/work/source.sif"}
    original_post = flask_app.fake_hpc_client.post
    def interrupted(path, body, timeout=None):
        if path.endswith('/install'):
            raise APITimeoutError('Connection interrupted')
        return original_post(path, body, timeout)
    flask_app.fake_hpc_client.post = Mock(side_effect=interrupted)
    with pytest.raises(APITimeoutError):
        service.install_component(payload, user=user)
    row = service.get_installation(payload['request_id'])
    assert row.status == 'unknown'
    flask_app.fake_hpc_client.get = Mock(return_value={"request_id": row.public_id, "manifest_hash": row.manifest_hash, "sif_sha256": "b" * 64, "sif_remote_path": "/work/installed/component.sif", "remote_install_dir": "/work/installed"})
    flask_app.fake_hpc_client.get.return_value["request_id"] = "another-request"
    service.reconcile_installation(row)
    assert row.status == 'unknown'
    flask_app.fake_hpc_client.get.return_value["request_id"] = row.public_id
    service.reconcile_installation(row)
    assert row.status == 'installed'
    retry = service.install_component(payload, user=user)
    assert retry['reused'] is True
    assert flask_app.fake_hpc_client.post.call_count == 2


@pytest.mark.parametrize("component,recipe", [
    ("image_metadata_extractor", "zenodo_image_metadata_extractor"),
    ("historic_prepare", "historic_prepare_images"),
])
def test_install_profile_merge_seeds_recipes_immediately_and_preserves_pins(flask_app, component, recipe):
    from copy import deepcopy
    from services.registry_lock import OperationConflict

    flask_app.config.update(WEBHDP_DEPLOYMENT_MODE="local", WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    native = flask_app.native_pipeline_service
    source = REPO_ROOT / "external_code" / component
    raw = yaml.safe_load((source / "component.yaml").read_text())
    imported = native.import_component_from_manifest(raw)
    assert PipelineDefinition.query.filter_by(identifier=recipe).first() is None
    installed = deepcopy(imported["manifest"])
    for profile in installed["execution"]["profiles"]:
        if profile.get("runtime") == "docker":
            profile["image"] = "sha256:" + "a" * 64
    arguments = {"component_key": component, "version": raw["metadata"]["version"],
                 "source_path": str(source), "source_type": "local_container_installed"}
    installer = HpcComponentInstallerService()
    installer._register_installed_component(installed, **arguments)
    assert PipelineDefinition.query.filter_by(identifier=recipe).first() is not None
    saved = native.get_pipeline(recipe)
    edited = native.create_pipeline_version_from_config(recipe, {**saved["config"], "name": "Operator recipe"})
    count = PipelineVersion.query.count()
    installer._register_installed_component(installed, **arguments)
    current = native.get_pipeline(recipe)
    assert current["active_version"] == edited["active_version"]
    assert current["config"]["name"] == "Operator recipe"
    assert PipelineVersion.query.count() == count
    changed = deepcopy(installed)
    for profile in changed["execution"]["profiles"]:
        if profile.get("runtime") == "docker":
            profile["image"] = "sha256:" + "b" * 64
    with pytest.raises(OperationConflict, match="saved pipeline"):
        installer._register_installed_component(changed, **arguments)
    assert native.get_pipeline(recipe)["active_version"] == edited["active_version"]
