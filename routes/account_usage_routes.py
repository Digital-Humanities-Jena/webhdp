"""Current account resource usage and admission limits."""

from flask import Blueprint
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import User
from exceptions import ResourceNotFoundError, SecurityError
from services import model_publication_queue
from services.account_upload_quota import upload_usage
from services.model_publication_accounts import is_demo
from services.native_run_quota import native_run_usage

account_usage_bp = Blueprint("account_usage", __name__)


@account_usage_bp.after_request
def keep_usage_private(response):
    response.cache_control.private = True
    response.cache_control.no_store = True
    return response


@account_usage_bp.get("/usage")
@jwt_required()
def get_usage():
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        raise ResourceNotFoundError("Account not found.")
    if is_demo(user):
        raise SecurityError("Account usage is available with your own WebHDP account.")
    return APIResponse.success({
        "uploads": upload_usage(user),
        "model_publication": model_publication_queue.account_usage(model_publication_queue.root(), user.id),
        "native_processing": native_run_usage(user),
    })
