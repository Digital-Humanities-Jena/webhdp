from flask import Flask

from services.hdp_component_policy import (
    DEPLOYMENT_CLASS_SERVER,
    DEPLOYMENT_CLASS_WORKSTATION_LOCAL,
    component_runtime_status,
    default_component_runtime_keys,
    hpc_only_component,
    hpc_required_component,
    local_hdp_component_execution_allowed,
    webhdp_deployment_class,
)


class _HealthService:
    def __init__(self, healthy=True):
        self.healthy = healthy

    def check_health(self):
        return self.healthy


def _app(*, mode="server", allow_local=False, renderer_healthy=True, usdz_healthy=True):
    app = Flask(__name__)
    app.config["WEBHDP_DEPLOYMENT_MODE"] = mode
    app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = allow_local
    app.config["ENABLE_RENDERER"] = True
    app.config["ENABLE_USDZ_CONVERSION"] = True
    app.fast_renderer_service = _HealthService(renderer_healthy)
    app.any_to_usdz_service = _HealthService(usdz_healthy)
    return app


def test_server_deployment_requires_hpc_for_compute_components():
    app = _app(mode="server", allow_local=False)

    assert webhdp_deployment_class(app) == DEPLOYMENT_CLASS_SERVER
    assert local_hdp_component_execution_allowed(app) is False

    status = component_runtime_status("fast_renderer", app)

    assert status["status"] == "hpc_required"
    assert status["allocation_required"] is True
    assert status["local_execution_allowed"] is False


def test_workstation_local_allows_healthy_local_compute_components():
    app = _app(mode="local", allow_local=True, renderer_healthy=True)

    assert webhdp_deployment_class(app) == DEPLOYMENT_CLASS_WORKSTATION_LOCAL
    assert local_hdp_component_execution_allowed(app) is True

    status = component_runtime_status("fast_renderer", app)

    assert status["status"] == "local_allowed"
    assert status["allocation_required"] is False
    assert status["local_healthy"] is True


def test_workstation_local_reports_unavailable_when_local_service_is_down():
    app = _app(mode="local", allow_local=True, renderer_healthy=False)

    status = component_runtime_status("fast_renderer", app)

    assert status["status"] == "unavailable"
    assert status["allocation_required"] is False
    assert "not reachable" in status["message"]


def test_disabled_component_reports_disabled_before_runtime_selection():
    app = _app(mode="local", allow_local=True, renderer_healthy=True)
    app.config["ENABLE_RENDERER"] = False

    status = component_runtime_status("fast_renderer", app)

    assert status["status"] == "disabled"
    assert status["enabled"] is False


def test_hpc_only_component_reports_hpc_only_status():
    app = _app(mode="local", allow_local=True)

    status = component_runtime_status("gltf_validator", app, hpc_only=True)

    assert status["status"] == "hpc_only"
    assert status["hpc_only"] is True
    assert status["hpc_required"] is True
    assert status["allocation_required"] is True
    assert "HPC-only" in status["message"]


def test_manifest_component_with_hpc_and_local_profiles_requires_compute_but_is_not_hpc_only():
    assert hpc_required_component("gltf_validator") is True
    assert hpc_only_component("gltf_validator") is False
    assert "gltf_validator" in default_component_runtime_keys()


def test_workstation_local_can_fallback_to_active_hpc_allocation_when_local_service_down():
    app = _app(mode="local", allow_local=True, renderer_healthy=False)

    status = component_runtime_status("fast_renderer", app, active_hpc_allocation=True)

    assert status["status"] == "hpc_required"
    assert status["active_hpc_allocation"] is True
    assert status["allocation_required"] is False
    assert "active HPC-Link allocation" in status["message"]
