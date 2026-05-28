import logging
import os

from flask import Blueprint, jsonify, request

from api_utils import APIResponse
from services.public_oembed_service import (
    PublicRecordError,
    build_oembed_response,
    build_public_record,
    parse_public_record_url,
)

logger = logging.getLogger(__name__)
public_bp = Blueprint("public", __name__)


def _public_base_url() -> str:
    configured = (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("FRONTEND_URL")
        or request.host_url
    )
    return str(configured or "").strip().rstrip("/")


@public_bp.route("/public/records/<environment>/<zenodo_record_id>", methods=["GET"])
def get_public_record(environment, zenodo_record_id):
    try:
        record = build_public_record(
            environment,
            zenodo_record_id,
            public_base_url=_public_base_url(),
        )
    except PublicRecordError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Failed to build public record payload: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve public record")

    if record is None:
        return APIResponse.not_found("Published public Zenodo record was not found")
    return APIResponse.success(data=record)


@public_bp.route("/oembed", methods=["GET"])
def get_oembed():
    requested_format = str(request.args.get("format") or "json").strip().lower()
    if requested_format not in {"", "json"}:
        return jsonify({"error": "Only JSON oEmbed responses are supported"}), 501

    target_url = request.args.get("url")
    if not target_url:
        return jsonify({"error": "url is required"}), 400

    try:
        environment, record_id = parse_public_record_url(target_url)
        record = build_public_record(
            environment,
            record_id,
            public_base_url=_public_base_url(),
        )
        if record is None:
            return jsonify({"error": "Published public Zenodo record was not found"}), 404
        return jsonify(
            build_oembed_response(
                record,
                maxwidth=request.args.get("maxwidth"),
                maxheight=request.args.get("maxheight"),
            )
        )
    except PublicRecordError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to build oEmbed response: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to build oEmbed response"}), 500
