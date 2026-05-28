# routes/__init__.py
from flask import Blueprint


def register_routes(app):
    """Register all route blueprints"""
    from .admin_routes import admin_bp
    from .auth_routes import auth_bp
    from .institution_routes import institution_bp
    from .metadata_routes import metadata_bp
    from .pipeline_routes import pipeline_bp
    from .session_routes import session_bp
    from .submission_routes import submission_bp
    from .setup_routes import setup_bp
    from .msf_routes import msf_bp
    from .edm_routes import edm_bp
    from .docs_routes import docs_bp
    from .developer_routes import developer_bp
    from .tools_routes import tools_bp
    from .dataset_routes import dataset_bp
    from .issues_routes import issues_bp
    from .notification_routes import notifications_bp
    from .pipeline_v2_routes import pipeline_v2_bp
    from .hpc_link_routes import hpc_link_bp
    from .hpc_resource_request_routes import hpc_resource_request_bp
    from .public_routes import public_bp
    from .profile_routes import profile_bp

    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(institution_bp, url_prefix="/api/v1/institutions")
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")
    app.register_blueprint(metadata_bp, url_prefix="/api/v1/metadata")
    app.register_blueprint(pipeline_bp, url_prefix="/api/v1/pipelines")
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(submission_bp, url_prefix="/api/v1/submissions")
    app.register_blueprint(setup_bp, url_prefix="/api/v1/setup")
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")
    app.register_blueprint(edm_bp, url_prefix="/api/v1/edm")
    app.register_blueprint(docs_bp, url_prefix="/api/v1/docs")
    app.register_blueprint(developer_bp, url_prefix="/api/v1/developer")
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")
    app.register_blueprint(dataset_bp, url_prefix="/api/v1/datasets")
    app.register_blueprint(issues_bp, url_prefix="/api/v1/issues")
    app.register_blueprint(notifications_bp, url_prefix="/api/v1/notifications")
    app.register_blueprint(hpc_link_bp, url_prefix="/api/v1/hpc-link")
    app.register_blueprint(hpc_resource_request_bp, url_prefix="/api/v1/hpc-resource-requests")
    app.register_blueprint(public_bp, url_prefix="/api/v1")
    app.register_blueprint(profile_bp, url_prefix="/api/v1/profiles")
    app.register_blueprint(pipeline_v2_bp, url_prefix="/api/v2")

    from .template_routes import template_bp
    app.register_blueprint(template_bp, url_prefix="/api/v1/templates")

    from .cloud_test_routes import cloud_test_bp
    app.register_blueprint(cloud_test_bp, url_prefix="/api/v1/admin/cloud")
