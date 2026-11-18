"""Versioned WebHDP-Link HTTP contract with an independent authorization boundary."""
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from database.database import db
from database.models import User, UserRole
from database.webhdp_link_models import LinkArtifact, LinkClient, LinkPublication, LinkRun, LinkToken, LinkUpload
from services import webhdp_link_service as link
from services.model_publication_accounts import is_demo
from services.registry_lock import OperationConflict

webhdp_link_bp = Blueprint('webhdp_link', __name__)


def problem(code, detail, status):
    response = jsonify({'type': f'urn:webhdp:link:problem:{code}', 'title': code.replace('_', ' ').capitalize(),
                        'status': status, 'detail': detail, 'code': code,
                        'instance': request.path})
    if request.path.startswith('/api/v1/link/oauth/'):
        payload = response.get_json()
        payload.update(error=code, error_description=detail)
        response = jsonify(payload)
    response.status_code = status
    response.content_type = 'application/problem+json'
    if status == 401:
        response.headers['WWW-Authenticate'] = 'Bearer realm="WebHDP-Link", error="invalid_token"'
    if status == 429:
        response.headers['Retry-After'] = '10'
    return response


def frontend_origin():
    value = current_app.config.get('FRONTEND_URL') or request.host_url.rstrip('/')
    return link.origin_of(value)


def allowed_origin(origin):
    if origin == frontend_origin() or origin == request.host_url.rstrip('/'):
        return True
    if request.path.startswith(('/api/v1/link/admin/', '/api/v1/link/jobs', '/api/v1/link/grants')) or request.path == '/api/v1/link/oauth/authorize':
        return False
    return any(origin in link.client_config(row).get('origins', []) for row in LinkClient.query.filter_by(enabled=True).all())


@webhdp_link_bp.before_request
def enforce_link_boundary():
    request.max_content_length = 65536
    request.max_form_memory_size = 131072
    request.max_form_parts = 8
    origin = request.headers.get('Origin')
    if origin and not allowed_origin(origin):
        return problem('origin_denied', 'This origin is not registered for WebHDP-Link.', 403)
    if request.method == 'OPTIONS':
        requested_headers = {x.strip().lower() for x in request.headers.get('Access-Control-Request-Headers', '').split(',') if x.strip()}
        if requested_headers - {'authorization', 'content-type', 'idempotency-key'}:
            return problem('origin_denied', 'The preflight requests an unsupported header.', 403)
        if request.headers.get('Access-Control-Request-Method', 'GET') not in {'GET', 'POST', 'PATCH', 'DELETE'}:
            return problem('origin_denied', 'The preflight requests an unsupported method.', 403)
        return '', 204


@webhdp_link_bp.after_request
def link_response_headers(response):
    # Global middleware may reject a request before this blueprint is entered.
    # Normalize its envelope without forwarding internal paths or diagnostics.
    if response.status_code >= 400 and response.mimetype != 'application/problem+json':
        response = problem('request_failed', 'The request could not be completed. Check authorization, request size and service availability.', response.status_code)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
    response.headers.pop('Access-Control-Allow-Credentials', None)
    origin = request.headers.get('Origin')
    if origin and allowed_origin(origin):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, Idempotency-Key'
        response.headers['Access-Control-Expose-Headers'] = 'Location, Retry-After, Content-Disposition, ETag'
        response.headers['Access-Control-Max-Age'] = '600'
    return response


@webhdp_link_bp.errorhandler(Exception)
def handle_error(exc):
    db.session.rollback()
    if isinstance(exc, link.LinkError):
        return problem(exc.code, exc.detail, exc.status)
    if isinstance(exc, OperationConflict):
        return problem('operation_in_progress', 'Another operation is in progress. Retry using the same idempotency key.', 409)
    if isinstance(exc, IntegrityError):
        return problem('conflict', 'This operation conflicts with an existing resource.', 409)
    if isinstance(exc, HTTPException):
        return problem('invalid_request', 'The request body, method or resource is invalid.', exc.code or 400)
    current_app.logger.exception('WebHDP-Link request failed')
    return problem('internal_error', 'The server could not complete the request. Contact the WebHDP maintainer.', 500)


def body():
    value = request.get_json()
    link.fail(not isinstance(value, dict), 'invalid_request', 'Expected a JSON object.')
    try:
        link.dumps(value)
    except (TypeError, ValueError):
        raise link.LinkError('invalid_request', 'JSON values must be finite and serializable.')
    return value


def user_required(admin=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                verify_jwt_in_request()
                user = db.session.get(User, int(get_jwt_identity()))
            except Exception:
                raise link.LinkError('invalid_token', 'Sign in to WebHDP to continue.', 401)
            link.require_user(user)
            link.fail(admin and user.role != UserRole.ADMIN, 'access_denied', 'WebHDP administrator access is required.', 403)
            g.link_user = user
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def bearer(scope):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            g.link_token, g.link_client, g.link_user = link.authenticate(scope)
            link.fail(is_demo(g.link_user), 'access_denied', 'This account is limited to the model publication demonstration.', 403)
            if request.path == '/api/v1/link/uploads' and request.method == 'POST':
                # Set before request.files triggers Werkzeug multipart spooling.
                request.max_content_length = link.client_config(g.link_client)['max_upload_bytes'] + 16384
                if request.content_length is not None and request.content_length > request.max_content_length:
                    raise link.LinkError('upload_too_large', 'The multipart upload exceeds the application file quota.', 413)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def get_row(model, key, label):
    row = db.session.get(model, key)
    link.fail(row is None, 'not_found', f'{label} not found.', 404)
    return row


@webhdp_link_bp.get('/discovery')
def discovery():
    base = link.issuer()
    return jsonify({'name': 'WebHDP-Link', 'version': '1.0', 'issuer': base,
                    'authorization_endpoint': str(current_app.config.get('FRONTEND_URL') or request.host_url).rstrip('/') + '/link/authorize',
                    'token_endpoint': base + '/oauth/token', 'revocation_endpoint': base + '/oauth/revoke',
                    'api_base': base, 'openapi_url': base + '/openapi.json',
                    'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code'],
                    'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none'],
                    'scopes_supported': list(link.SCOPES), 'authorization_response_iss_parameter_supported': True,
                    'features': {'uploads': 'multipart', 'status': 'polling', 'cancellation': 'between_components',
                                 'queue': 'durable', 'parameters': 'json-schema-2020-12', 'webhooks': False, 'remote_url_import': False}})


@webhdp_link_bp.get('/openapi.json')
def openapi():
    from services.webhdp_link_openapi import document
    return jsonify(document(link.public_base()))


@webhdp_link_bp.get('/oauth/request')
def consent_request():
    link.fail(any(len(request.args.getlist(key)) != 1 for key in request.args), 'invalid_request', 'OAuth parameters cannot be repeated.')
    client, details = link.authorization_request(request.args)
    return jsonify({'client': {'id': client.id, 'name': client.name}, 'redirect_uri': details['redirect_uri'],
                    'scope': details['scope'], 'expires_in': 3600,
                    'pipelines': [link.serialize_publication(x) for x in link.available_publications(client)]})


@webhdp_link_bp.post('/oauth/authorize')
@user_required()
def authorize():
    return jsonify(link.authorize(body(), g.link_user))


@webhdp_link_bp.post('/oauth/token')
def token():
    link.fail(request.mimetype != 'application/x-www-form-urlencoded', 'invalid_request', 'Token exchange requires application/x-www-form-urlencoded.')
    link.fail(any(len(request.form.getlist(key)) != 1 for key in request.form), 'invalid_request', 'OAuth parameters cannot be repeated.')
    return jsonify(link.exchange_code(request.form))


@webhdp_link_bp.post('/oauth/revoke')
def revoke():
    link.fail(request.mimetype != 'application/x-www-form-urlencoded', 'invalid_request', 'Revocation requires application/x-www-form-urlencoded.')
    raw = request.form.get('token', '')
    if len(raw) < 300:
        row = LinkToken.query.filter_by(token_hash=link.digest(raw)).first()
        if row:
            origin = request.headers.get('Origin')
            link.fail(origin and (row.service or origin != row.origin), 'origin_denied', 'The token does not belong to this origin.', 403)
            row.revoked = True
            db.session.commit()
    return '', 200


@webhdp_link_bp.get('/pipelines')
@bearer('pipelines:read')
def pipelines():
    return jsonify({'pipelines': [link.serialize_publication(x) for x in link.available_publications(g.link_client, g.link_token)]})


@webhdp_link_bp.get('/pipelines/<pipeline_id>')
@bearer('pipelines:read')
def pipeline(pipeline_id):
    row = next((x for x in link.available_publications(g.link_client, g.link_token) if x.id == pipeline_id), None)
    link.fail(row is None, 'pipeline_not_found', 'The pipeline is unavailable to this authorization.', 404)
    return jsonify(link.serialize_publication(row))


@webhdp_link_bp.post('/uploads')
@bearer('uploads:write')
def upload():
    link.fail(len(request.files) != 1 or len(request.files.getlist('file')) != 1, 'invalid_upload', 'Provide exactly one multipart file field named file.')
    row = link.accept_upload(request.files.get('file'), g.link_token, g.link_client)
    return jsonify(link.serialize_upload(row)), 201


@webhdp_link_bp.delete('/uploads/<upload_id>')
@bearer('uploads:write')
def delete_upload(upload_id):
    import shutil
    row = LinkUpload.query.filter_by(id=upload_id, client_id=g.link_client.id, user_id=g.link_user.id).first()
    link.fail(row is None, 'upload_not_found', 'The upload is unavailable to this authorization.', 404)
    with link.registry_lock('link-submit:' + g.link_client.id), link.registry_lock('link-storage:' + g.link_client.id):
        for run in LinkRun.query.filter_by(client_id=g.link_client.id).filter(LinkRun.status.in_(['queued', 'running'])).all():
            link.fail(upload_id in link.loads(run.request_json)['inputs'], 'upload_in_use', 'The upload belongs to an active run.', 409)
        path = link.upload_path(row)
        db.session.delete(row)
        db.session.commit()
        shutil.rmtree(path.parent, ignore_errors=True)
    return '', 204


@webhdp_link_bp.post('/runs')
@bearer('runs:write')
def create_run():
    row, reused = link.submit_run(body(), g.link_token, g.link_client, request.headers.get('Idempotency-Key'))
    response = jsonify({**link.serialize_run(row), 'reused': reused})
    response.status_code = 202
    response.headers['Location'] = f'/api/v1/link/runs/{row.id}'
    response.headers['Retry-After'] = '2'
    return response


@webhdp_link_bp.get('/runs')
@bearer('runs:read')
def runs():
    ids = set(link.loads(g.link_token.pipeline_ids_json, [])) & set(link.client_config(g.link_client)['pipeline_ids'])
    rows = LinkRun.query.filter_by(client_id=g.link_client.id, user_id=g.link_user.id).filter(LinkRun.publication_id.in_(ids)).order_by(LinkRun.created_at.desc()).limit(100).all()
    return jsonify({'runs': [link.serialize_run(row) for row in rows]})


@webhdp_link_bp.get('/runs/<run_id>')
@bearer('runs:read')
def run(run_id):
    response = jsonify(link.serialize_run(link.require_run(run_id, g.link_token)))
    response.headers['Retry-After'] = '2'
    return response


@webhdp_link_bp.post('/runs/<run_id>/cancel')
@bearer('runs:write')
def cancel(run_id):
    return jsonify(link.serialize_run(link.cancel_run(link.require_run(run_id, g.link_token))))


@webhdp_link_bp.get('/runs/<run_id>/artifacts/<artifact_id>')
@bearer('artifacts:read')
def artifact(run_id, artifact_id):
    row = link.require_run(run_id, g.link_token)
    artifact = LinkArtifact.query.filter_by(id=artifact_id, run_id=row.id).first()
    link.fail(artifact is None, 'artifact_not_found', 'The artifact is unavailable to this authorization.', 404)
    path = link.artifact_path(row, artifact)
    response = send_file(path, as_attachment=True, download_name=artifact.name, mimetype=artifact.media_type, conditional=True, etag=artifact.sha256)
    return response


@webhdp_link_bp.get('/admin/clients')
@user_required(admin=True)
def admin_clients():
    return jsonify({'clients': [link.serialize_client(x) for x in LinkClient.query.order_by(LinkClient.name).all()]})


@webhdp_link_bp.post('/admin/clients')
@user_required(admin=True)
def admin_create_client():
    return jsonify(link.serialize_client(link.save_client(body()))), 201


@webhdp_link_bp.patch('/admin/clients/<client_id>')
@user_required(admin=True)
def admin_update_client(client_id):
    return jsonify(link.serialize_client(link.save_client(body(), get_row(LinkClient, client_id, 'Application'))))


@webhdp_link_bp.get('/admin/publications')
@user_required(admin=True)
def admin_publications():
    return jsonify({'publications': [link.serialize_publication(x, admin=True) for x in LinkPublication.query.order_by(LinkPublication.name).all()]})


@webhdp_link_bp.post('/admin/publications')
@user_required(admin=True)
def admin_create_publication():
    return jsonify(link.serialize_publication(link.save_publication(body()), admin=True)), 201


@webhdp_link_bp.patch('/admin/publications/<publication_id>')
@user_required(admin=True)
def admin_update_publication(publication_id):
    return jsonify(link.serialize_publication(link.save_publication(body(), get_row(LinkPublication, publication_id, 'Publication')), admin=True))


@webhdp_link_bp.get('/admin/pipeline-options')
@user_required(admin=True)
def admin_pipeline_options():
    return jsonify({'pipelines': link.pipeline_options()})


@webhdp_link_bp.post('/admin/clients/<client_id>/tokens')
@user_required(admin=True)
def admin_create_token(client_id):
    data = link.object_payload(body(), {'user_id', 'scope', 'expires_in'})
    user_id = link.bounded_int(data.get('user_id', g.link_user.id), 'user_id', 1, 2**31 - 1)
    user = get_row(User, user_id, 'User')
    link.fail(is_demo(user), 'access_denied', 'Demonstration accounts cannot authorize applications.', 403)
    return jsonify(link.issue_token(get_row(LinkClient, client_id, 'Application'), user, scope=data.get('scope'), expires_in=data.get('expires_in', 3600), service=True)), 201


@webhdp_link_bp.get('/admin/tokens')
@user_required(admin=True)
def admin_tokens():
    return jsonify({'tokens': [link.serialize_token(x) for x in LinkToken.query.order_by(LinkToken.created_at.desc()).limit(200).all()]})


@webhdp_link_bp.delete('/admin/tokens/<token_id>')
@user_required(admin=True)
def admin_revoke_token(token_id):
    row = get_row(LinkToken, token_id, 'Token')
    row.revoked = True
    db.session.commit()
    return '', 204


@webhdp_link_bp.get('/admin/runs')
@user_required(admin=True)
def admin_runs():
    return jsonify({'runs': [link.serialize_run(x, admin=True) for x in LinkRun.query.order_by(LinkRun.created_at.desc()).limit(100).all()]})


@webhdp_link_bp.post('/admin/runs/<run_id>/cancel')
@user_required(admin=True)
def admin_cancel(run_id):
    return jsonify(link.serialize_run(link.cancel_run(get_row(LinkRun, run_id, 'Run')), admin=True))


@webhdp_link_bp.get('/grants')
@user_required()
def grants():
    return jsonify({'grants': [{**link.serialize_token(row), 'client_name': db.session.get(LinkClient, row.client_id).name}
                               for row in LinkToken.query.filter_by(user_id=g.link_user.id).order_by(LinkToken.created_at.desc()).limit(200).all()]})


@webhdp_link_bp.delete('/grants/<token_id>')
@user_required()
def revoke_grant(token_id):
    row = LinkToken.query.filter_by(id=token_id, user_id=g.link_user.id).first()
    link.fail(row is None, 'not_found', 'This authorization does not belong to your account.', 404)
    row.revoked = True
    db.session.commit()
    return '', 204



def owned_job(run_id):
    row = LinkRun.query.filter_by(id=run_id, user_id=g.link_user.id).first()
    link.fail(row is None, 'run_not_found', 'This processing job does not belong to your account.', 404)
    return row


def job_payload(row):
    return {**link.serialize_run(row), 'client_id': row.client_id, 'client_name': db.session.get(LinkClient, row.client_id).name}


@webhdp_link_bp.get('/jobs')
@user_required()
def jobs():
    return jsonify({'jobs': [job_payload(row) for row in LinkRun.query.filter_by(user_id=g.link_user.id).order_by(LinkRun.created_at.desc()).limit(100).all()]})


@webhdp_link_bp.get('/jobs/<run_id>')
@user_required()
def job(run_id):
    return jsonify(job_payload(owned_job(run_id)))


@webhdp_link_bp.post('/jobs/<run_id>/cancel')
@user_required()
def cancel_job(run_id):
    return jsonify(job_payload(link.cancel_run(owned_job(run_id))))


@webhdp_link_bp.get('/jobs/<run_id>/artifacts/<artifact_id>')
@user_required()
def job_artifact(run_id, artifact_id):
    row = owned_job(run_id)
    artifact = LinkArtifact.query.filter_by(id=artifact_id, run_id=row.id).first()
    link.fail(artifact is None, 'artifact_not_found', 'The artifact does not belong to this job.', 404)
    return send_file(link.artifact_path(row, artifact), as_attachment=True, download_name=artifact.name,
                     mimetype=artifact.media_type, conditional=True, etag=artifact.sha256)
