import os
import shutil
import logging
import requests
import secrets
from functools import wraps
from flask import Blueprint, request, current_app, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request

from api_utils import APIResponse
from database.database import db
from database.models import SystemConfig, User, UserRole
from services.fast_renderer_service import FastRendererService

logger = logging.getLogger(__name__)
setup_bp = Blueprint("setup", __name__)


def _setup_completed() -> bool:
    config = db.session.get(SystemConfig, "setup_completed")
    return bool(config and config.value == "true")


def _configured_setup_token() -> str:
    return str(current_app.config.get("SETUP_BOOTSTRAP_TOKEN") or os.environ.get("SETUP_BOOTSTRAP_TOKEN") or "").strip()


def _request_setup_token() -> str:
    return str(
        request.headers.get("X-Setup-Token")
        or request.headers.get("X-Bootstrap-Token")
        or request.args.get("setup_token")
        or ""
    ).strip()


def _has_valid_setup_token() -> bool:
    configured = _configured_setup_token()
    provided = _request_setup_token()
    return bool(configured and provided and secrets.compare_digest(configured, provided))


def _has_admin_jwt() -> bool:
    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
    except Exception:
        return False
    if not user_id:
        return False
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return False
    return bool(user and user.role == UserRole.ADMIN)


def require_setup_authorization(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if _has_admin_jwt():
            return func(*args, **kwargs)
        if not _setup_completed() and _has_valid_setup_token():
            return func(*args, **kwargs)
        return APIResponse.forbidden("Setup authorization required")

    return wrapper

@setup_bp.route("/status", methods=["GET"])
def get_status():
    """Check if the system is initialized."""
    return APIResponse.success(data={"initialized": _setup_completed(), "core_only": os.environ.get("WEBHDP_CORE_ONLY", "false").lower() == "true"})

@setup_bp.route("/reset", methods=["POST"])
@jwt_required()
def reset_system():
    """Reset system to uninitialized state (Admin only)."""
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)

    if not user or user.role != UserRole.ADMIN:
        return APIResponse.forbidden("Admin privileges required")

    config = db.session.get(SystemConfig, "setup_completed")
    if config:
        config.value = "false"
    else:
        db.session.add(SystemConfig(key="setup_completed", value="false"))

    db.session.commit()
    logger.warning(f"System reset initiated by admin {user.email}")
    return APIResponse.success(message="System reset successfully")

def _check_zenodo_connectivity(key, sandbox=True):
    """Helper to check Zenodo connectivity using an API key."""
    if not key:
        return "Not Configured"

    base_url = "https://sandbox.zenodo.org/api" if sandbox else "https://zenodo.org/api"
    headers = {"Authorization": f"Bearer {key}"}

    try:
        # We use the 'depositions' endpoint with a limit of 1 to minimize load.
        # A 200 OK means the token is valid and has access.
        resp = requests.get(
            f"{base_url}/deposit/depositions",
            headers=headers,
            params={"size": 1},
            timeout=10
        )

        if resp.status_code == 200:
            return "Reachable"
        elif resp.status_code == 401 or resp.status_code == 403:
            return "Invalid Key"
        else:
            return f"Error: {resp.status_code}"

    except Exception as e:
        return f"Unreachable: {str(e)}"

@setup_bp.route("/check", methods=["POST"])
@require_setup_authorization
def check_system():
    """Perform system checks (Blender connectivity and Zenodo reachability)."""
    from services.hdp_component_policy import local_hdp_component_execution_allowed
    from services.setup_guidance_service import build_admin_setup_guidance

    renderer_enabled = current_app.config.get("ENABLE_RENDERER", True)

    if renderer_enabled and local_hdp_component_execution_allowed(current_app):
        fast_renderer = current_app.fast_renderer_service
        blender_status = fast_renderer.check_health()
    else:
        logger.info("Renderer local health check skipped.")
        blender_status = False

    # Zenodo Checks
    sandbox_key = os.environ.get("ZENODO_SANDBOX_API_KEY")
    prod_key = os.environ.get("ZENODO_API_KEY")

    zenodo_sandbox_status = _check_zenodo_connectivity(sandbox_key, sandbox=True)
    zenodo_production_status = _check_zenodo_connectivity(prod_key, sandbox=False)
    guidance = build_admin_setup_guidance(
        current_app,
        runtime_checks={
            "fast_renderer": blender_status,
        },
    )

    return APIResponse.success(data={
        "blender_reachable": blender_status,
        "renderer_enabled": renderer_enabled,
        "renderer_hpc_required": renderer_enabled and not local_hdp_component_execution_allowed(current_app),
        "project_runtime": "native_hdpc",
        "zenodo_sandbox_status": zenodo_sandbox_status,
        "zenodo_production_status": zenodo_production_status,
        "setup_guidance": guidance,
        "deployment_mode": guidance["deployment_mode"],
        "deployment_class": guidance["deployment_class"],
        "deployment_label": guidance["deployment_label"],
        "storage_mode": guidance["storage_mode"],
        "local_hdp_components_allowed": guidance["local_hdp_components_allowed"],
    })


@setup_bp.route("/guidance", methods=["GET"])
@require_setup_authorization
def get_setup_guidance():
    """Return mode-aware setup guidance during first-run bootstrap."""
    from services.setup_guidance_service import build_admin_setup_guidance

    return APIResponse.success(data=build_admin_setup_guidance(current_app))

@setup_bp.route("/test-render", methods=["POST"])
@require_setup_authorization
def run_test_render():
    """Run a test render using the test model."""
    try:
        from services.hdp_component_policy import hpc_required_message, local_hdp_component_execution_allowed

        if not current_app.config.get("ENABLE_RENDERER", True):
            logger.info("Test render skipped: Renderer is disabled.")
            return APIResponse.success(data={
                "success": True,
                "images": [],
                "status": "skipped_disabled"
            })
        if not local_hdp_component_execution_allowed(current_app):
            return APIResponse.validation_error(
                hpc_required_message("fast_renderer"),
                details={"hpc_required": True, "local_execution_allowed": False},
            )

        fast_renderer = current_app.fast_renderer_service
        session_manager = current_app.session_manager # Access session manager

        # 1. Create a temporary session
        # We use the session manager to ensure we get a valid shared path
        hdpc_path, data_out_path, uploads_path, session_dir = session_manager.create_session_dirs()

        # 2. Locate test model
        # Assume it's in the app root
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source_model_path = os.path.join(app_root, "test_model.glb")

        if not os.path.exists(source_model_path):
            return APIResponse.server_error("Test model not found on server")

        # 3. Copy to session uploads
        target_model_path = os.path.join(uploads_path, "test_model.glb")
        shutil.copy(source_model_path, target_model_path)

        # 4. Trigger Render
        logger.info(f"Starting test render for {target_model_path}")

        # Request only 2 images for testing
        test_angles = [0, 90]
        options = {"custom_angles": test_angles}

        result = fast_renderer.render(target_model_path, data_out_path, options=options)

        if not result.get("success"):
            return APIResponse.server_error(f"Render failed: {result.get('error')}")

        # 5. List generated files
        # Fast renderer creates a subdir based on stem 'test_model'
        render_output_dir = os.path.join(data_out_path, "test_model")
        generated_images = []

        if os.path.exists(render_output_dir):
            for f in os.listdir(render_output_dir):
                if f.endswith(".png"):
                    import base64
                    with open(os.path.join(render_output_dir, f), "rb") as img_file:
                        b64 = base64.b64encode(img_file.read()).decode('utf-8')
                        generated_images.append({
                            "filename": f,
                            "data": f"data:image/png;base64,{b64}"
                        })

        return APIResponse.success(data={
            "success": True,
            "images": generated_images
        })

    except Exception as e:
        logger.error(f"Test render failed: {e}", exc_info=True)
        return APIResponse.server_error(str(e))

@setup_bp.route("/create-admin", methods=["POST"])
@require_setup_authorization
def create_admin():
    """Create the initial admin user."""
    data = request.json or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return APIResponse.validation_error("Email and password required")

    # Check if admin already exists?
    # Usually setup is run once. But we might want to allow this if setup is not complete.
    config = db.session.get(SystemConfig, "setup_completed")
    if config and config.value == "true":
        return APIResponse.validation_error("Setup already completed")

    try:
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            # If user exists, update to admin and set password
            existing_user.role = UserRole.ADMIN
            existing_user.set_password(password)
            existing_user.is_verified = True
            existing_user.verification_token = None
        else:
            new_user = User(
                email=email,
                role=UserRole.ADMIN,
                is_verified=True,
                verification_token=None
            )
            new_user.set_password(password)
            db.session.add(new_user)

        db.session.commit()
        return APIResponse.success(message="Admin user created")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to create admin: {e}")
        return APIResponse.server_error(f"Failed to create admin: {str(e)}")

@setup_bp.route("/complete", methods=["POST"])
@require_setup_authorization
def complete_setup():
    """Mark setup as completed."""
    # This might also receive config data to save

    config = db.session.get(SystemConfig, "setup_completed")
    if not config:
        config = SystemConfig(key="setup_completed", value="true")
        db.session.add(config)
    else:
        config.value = "true"

    db.session.commit()
    return APIResponse.success(message="Setup completed")
