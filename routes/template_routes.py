from flask import Blueprint, request, current_app, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database.models import LodTemplate, User, UserRole, LodStandard
from database.database import db
from database.lod_template_bootstrap import ensure_default_lod_templates
from api_utils import APIResponse
from services.user_service import UserService
import logging

template_bp = Blueprint("templates", __name__, url_prefix="/templates")
logger = logging.getLogger(__name__)

def check_admin_access():
    user_id = get_jwt_identity()
    user = UserService().get_by_id(user_id)
    if user.role != UserRole.ADMIN:
        return False
    return True

@template_bp.route("", methods=["GET"])
@jwt_required()
def list_templates():
    """List all templates (accessible to all authenticated users)"""
    try:
        ensure_default_lod_templates()
        templates = LodTemplate.query.all()
        return APIResponse.success(data={"templates": [t.to_dict() for t in templates]})
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        return APIResponse.error("Failed to list templates", 500)

@template_bp.route("/<int:template_id>", methods=["GET"])
@jwt_required()
def get_template(template_id):
    """Get a specific template"""
    try:
        template = db.session.get(LodTemplate, template_id)
        if not template:
            return APIResponse.not_found("Template not found")
        return APIResponse.success(data={"template": template.to_dict()})
    except Exception as e:
        logger.error(f"Failed to get template: {e}")
        return APIResponse.error("Failed to retrieve template", 500)

@template_bp.route("", methods=["POST"])
@jwt_required()
def create_template():
    """Create a new template (Admin only)"""
    if not check_admin_access():
        return APIResponse.forbidden("Admin access required")

    data = request.get_json()
    if not data or 'name' not in data or 'content' not in data:
        return APIResponse.validation_error("Name and Content are required")

    try:
        template = LodTemplate(
            name=data['name'],
            description=data.get('description'),
            standard=LodStandard(data.get('standard', 'edm')),
            format=data.get('format', 'xml'),
            content=data['content'],
            is_default=data.get('is_default', False)
        )

        # If set as default, unset others? Not strictly required by spec but good practice
        # For now, let's keep it simple.

        db.session.add(template)
        db.session.commit()
        return APIResponse.created(data={"template": template.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to create template: {e}")
        return APIResponse.error("Failed to create template", 500)

@template_bp.route("/<int:template_id>", methods=["PUT"])
@jwt_required()
def update_template(template_id):
    """Update a template (Admin only)"""
    if not check_admin_access():
        return APIResponse.forbidden("Admin access required")

    data = request.get_json()
    try:
        template = db.session.get(LodTemplate, template_id)
        if not template:
            return APIResponse.not_found("Template not found")

        if 'name' in data:
            template.name = data['name']
        if 'description' in data:
            template.description = data.get('description')
        if 'content' in data:
            template.content = data['content']
        if 'is_default' in data:
            template.is_default = data['is_default']
        if 'standard' in data:
            template.standard = LodStandard(data['standard'])
        if 'format' in data:
            template.format = data['format']

        template.updated_at = db.session.query(db.func.now()).scalar() # Force update time? or rely on onupdate

        db.session.commit()
        return APIResponse.success(data={"template": template.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update template: {e}")
        return APIResponse.error("Failed to update template", 500)

@template_bp.route("/<int:template_id>", methods=["DELETE"])
@jwt_required()
def delete_template(template_id):
    """Delete a template (Admin only)"""
    if not check_admin_access():
        return APIResponse.forbidden("Admin access required")

    try:
        template = db.session.get(LodTemplate, template_id)
        if not template:
            return APIResponse.not_found("Template not found")

        db.session.delete(template)
        db.session.commit()
        return APIResponse.success(message="Template deleted successfully")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete template: {e}")
        return APIResponse.error("Failed to delete template", 500)

@template_bp.route("/preview", methods=["POST"])
@jwt_required()
def preview_template():
    """Preview a template rendering with provided metadata"""
    # This endpoint can be used by admins (with dummy data) or users (with real draft data)
    data = request.get_json() or {}
    if not data or 'template_id' not in data:
        # Allow checking via raw content too for Admin Editor?
        if 'content' in data:
             if not check_admin_access():
                 return APIResponse.forbidden("Admin access required")
             # Preview raw content (Admin Editor)
             content = data['content']
             metadata = data.get('metadata', {})
             zenodo = data.get('zenodo', {})
             main_file = data.get("main_file") or {
                 "key": data.get("main_file_key") or "sample_model.glb",
                 "filename": data.get("main_file_key") or "sample_model.glb",
                 "content_url": "https://zenodo.org/api/records/12345/files/sample_model.glb/content",
                 "url": "https://zenodo.org/api/records/12345/files/sample_model.glb/content",
                 "viewer_url": "",
                 "mime_type": "model/gltf-binary",
                 "format": "model/gltf-binary",
                 "content_type": "3D",
                 "edm_type": "3D",
                 "is_3d": True,
                 "size": 0,
             }

             try:
                 # Manually render with all helpers
                 import jinja2
                 from services.edm_service import DotDict

                 helpers = current_app.edm_service._get_template_helpers()

                 env = jinja2.Environment(autoescape=True)
                 jinja_template = env.from_string(content)
                 rendered = jinja_template.render(
                     metadata=DotDict(metadata) if isinstance(metadata, dict) else metadata,
                     zenodo=DotDict(zenodo) if isinstance(zenodo, dict) else zenodo,
                     helpers=helpers,
                     main_file=DotDict(main_file) if isinstance(main_file, dict) else main_file,
                     thumbnail_file=None,
                     thumbnail_files=[],
                     additional_thumbnail_files=[],
                 )
                 prepared = current_app.edm_service.prepare_rendered_edm_with_report(rendered, metadata)
                 return APIResponse.success(data={"xml": prepared["content"], "adjustments": prepared["adjustments"]})
             except jinja2.TemplateSyntaxError as e:
                 return APIResponse.validation_error(f"Template syntax error at line {e.lineno}: {e.message}")
             except jinja2.UndefinedError as e:
                 return APIResponse.validation_error(f"Undefined variable: {str(e)}")
             except Exception as e:
                 return APIResponse.validation_error(f"Template rendering failed: {str(e)}")

        return APIResponse.validation_error("template_id or content is required")

    template_id = data['template_id']
    metadata = data.get('metadata', {})
    zenodo = data.get('zenodo', {}) # Mock zenodo record
    main_file_key = data.get('main_file_key')

    try:
        rendered = current_app.edm_service.render_template(template_id, metadata, zenodo, main_file_key=main_file_key)
        if rendered is None:
             return APIResponse.not_found("Template not found or empty")
        prepared = current_app.edm_service.prepare_rendered_edm_with_report(rendered, metadata)
        return APIResponse.success(data={"xml": prepared["content"], "adjustments": prepared["adjustments"]})
    except ValueError as e:
        return APIResponse.validation_error(str(e))
    except Exception as e:
        return APIResponse.error(f"Preview failed: {str(e)}", 500)


@template_bp.route("/validate", methods=["POST"])
@jwt_required()
def validate_xml():
    """Validate XML content against EDM schema requirements"""
    data = request.get_json()

    if not data or 'xml' not in data:
        return APIResponse.validation_error("xml content is required")

    xml_content = data['xml']

    try:
        validation = current_app.edm_service.validate_edm_document(
            xml_content,
            metadata=data.get("metadata") or {},
            include_remote=current_app.config.get(
                "LOCAL_EDM_VALIDATOR_REQUIRED",
                False,
            ) or current_app.config.get(
                "ENABLE_LOCAL_EDM_VALIDATION",
                current_app.config.get("ENABLE_METIS_VALIDATION", True),
            ),
        )
        return APIResponse.success(data=validation)
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return APIResponse.error(f"Validation failed: {str(e)}", 500)
