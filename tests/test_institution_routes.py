from concurrent.futures import ThreadPoolExecutor

import pytest
pytest.importorskip("flask_jwt_extended")
pytest.importorskip("cryptography.fernet")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import AuditEvent, Institution, InstitutionMembership, InstitutionRole, Session, User, UserRole
from middleware import setup_error_handlers
from routes.institution_routes import institution_bp
from services.audit_service import record_audit_event
from services.institution_service import InstitutionService, institution_membership_lock
from services.zenodo_credential_service import ZenodoCredentialService


@pytest.fixture()
def institution_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "institution-test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "institution-test-jwt"

    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(institution_bp, url_prefix="/api/v1/institutions")

    with app.app_context():
        db.create_all()
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        manager = User(email="manager@example.com", role=UserRole.USER, is_verified=True)
        manager.set_password("password123")
        reader = User(email="reader@example.com", role=UserRole.USER, is_verified=True)
        reader.set_password("password123")
        moderator = User(email="moderator@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        visitor = User(email="visitor@example.com", role=UserRole.USER, is_verified=True)
        visitor.set_password("password123")
        db.session.add_all([owner, manager, reader, moderator, admin, visitor])
        db.session.flush()

        institution = Institution(
            name="Museum Network",
            slug="museum-network",
            created_by_user_id=owner.id,
        )
        db.session.add(institution)
        db.session.flush()

        db.session.add_all(
            [
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=owner.id,
                    role=InstitutionRole.OWNER,
                ),
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=manager.id,
                    role=InstitutionRole.MANAGER,
                ),
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=reader.id,
                    role=InstitutionRole.READER,
                ),
            ]
        )
        reader.default_institution_id = institution.id
        db.session.commit()

        credential_service = ZenodoCredentialService()
        credential_service.upsert_credential(
            owner_type="institution",
            owner_id=institution.id,
            environment="sandbox",
            token="sandbox-secret-token",
            actor_user_id=owner.id,
        )

        with app.app_context():
            owner_token = create_access_token(identity=str(owner.id))
            manager_token = create_access_token(identity=str(manager.id))
            reader_token = create_access_token(identity=str(reader.id))
            moderator_token = create_access_token(identity=str(moderator.id))
            admin_token = create_access_token(identity=str(admin.id))
            visitor_token = create_access_token(identity=str(visitor.id))

        yield {
            "app": app,
            "client": app.test_client(),
            "institution_id": institution.id,
            "owner_id": owner.id,
            "manager_id": manager.id,
            "reader_id": reader.id,
            "visitor_id": visitor.id,
            "owner_headers": {"Authorization": f"Bearer {owner_token}"},
            "manager_headers": {"Authorization": f"Bearer {manager_token}"},
            "reader_headers": {"Authorization": f"Bearer {reader_token}"},
            "moderator_headers": {"Authorization": f"Bearer {moderator_token}"},
            "admin_headers": {"Authorization": f"Bearer {admin_token}"},
            "visitor_headers": {"Authorization": f"Bearer {visitor_token}"},
        }

        db.session.remove()
        db.drop_all()


def test_institution_detail_redacts_credentials_for_reader(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    reader_response = client.get(
        f"/api/v1/institutions/{institution_id}",
        headers=institution_app["reader_headers"],
    )
    assert reader_response.status_code == 200
    reader_payload = reader_response.get_json()["data"]["institution"]
    assert "zenodo_credentials" not in reader_payload

    manager_response = client.get(
        f"/api/v1/institutions/{institution_id}",
        headers=institution_app["manager_headers"],
    )
    assert manager_response.status_code == 200
    manager_payload = manager_response.get_json()["data"]["institution"]
    assert manager_payload["zenodo_credentials"]["sandbox"]["masked_preview"]

    reader_credential_response = client.get(
        f"/api/v1/institutions/{institution_id}/zenodo-credentials/sandbox",
        headers=institution_app["reader_headers"],
    )
    assert reader_credential_response.status_code == 404


def test_existing_affiliation_and_workspace_membership_are_separate(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]
    visitor = institution_app["visitor_headers"]
    institution = db.session.get(Institution, institution_id)
    institution.profile_visibility = "internal"
    db.session.commit()

    suggestions = client.get(
        "/api/v1/institutions/suggestions?q=Museum",
        headers=visitor,
    )
    assert suggestions.status_code == 200
    assert suggestions.get_json()["data"]["institutions"][0]["name"] == "Museum Network"

    response = client.post(
        "/api/v1/institutions/affiliation",
        headers=visitor,
        json={"institution_id": institution_id},
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["institution"]["name"] == "Museum Network"
    assert payload["membership"] is None and payload["memberships"] == []
    assert client.get(f"/api/v1/institutions/{institution_id}", headers=visitor).status_code == 404
    manager = institution_app["manager_headers"]
    denied = client.post(f"/api/v1/institutions/{institution_id}/memberships", headers=manager,
                          json={"user_id": institution_app["visitor_id"], "role": "reader"})
    assert denied.status_code == 409
    assert denied.json["error"]["code"] == "INSTITUTION_INVITATION_REQUIRED"
    denied_put = client.put(f"/api/v1/institutions/{institution_id}/memberships/{institution_app['visitor_id']}",
                            headers=manager, json={"role": "reader"})
    assert denied_put.status_code == 404
    manager_id = institution_app["manager_id"]
    InstitutionService().upsert_membership(institution_id, institution_app["visitor_id"], "reader",
                                           actor=db.session.get(User, manager_id))
    selected = client.post("/api/v1/institutions/affiliation", headers=visitor, json={"name": "Museum Network"})
    assert selected.get_json()["data"]["membership"]["role"] == "reader"
    assert client.get(f"/api/v1/institutions/{institution_id}", headers=visitor).status_code == 200

    with institution_app["app"].app_context():
        stored_visitor = db.session.get(User, institution_app["visitor_id"])
        assert stored_visitor.default_institution_id == institution_id
        assert stored_visitor.affiliation == "Museum Network"


def test_private_institution_is_hidden_from_nonmembers(institution_app):
    client = institution_app["client"]
    headers = institution_app["visitor_headers"]
    response = client.get("/api/v1/institutions/suggestions?q=Museum", headers=headers)
    assert response.get_json()["data"]["institutions"] == []
    assert client.post("/api/v1/institutions/affiliation", headers=headers,
                       json={"institution_id": institution_app["institution_id"]}).status_code == 404
    text_only = client.post("/api/v1/institutions/affiliation", headers=headers, json={"name": "Museum Network"})
    assert text_only.status_code == 200
    assert text_only.json["data"]["institution"] is None
    assert text_only.json["data"]["user"]["affiliation"] == "Museum Network"


def test_institution_manager_cannot_grant_or_modify_owner_membership(institution_app):
    client = institution_app["client"]
    base = f'/api/v1/institutions/{institution_app["institution_id"]}/memberships'
    owner_path = f'{base}/{institution_app["owner_id"]}'
    manager = institution_app["manager_headers"]
    owner = institution_app["owner_headers"]
    assert client.put(f'{base}/{institution_app["manager_id"]}', headers=manager, json={"role": "owner"}).status_code == 403
    assert client.put(owner_path, headers=manager, json={"role": "manager"}).status_code == 403
    assert client.delete(owner_path, headers=manager).status_code == 403
    promoted = client.put(f'{base}/{institution_app["reader_id"]}', headers=owner, json={"role": "owner"})
    assert promoted.status_code == 200
    assert "user" not in promoted.json["data"]["membership"]


def test_affiliation_never_creates_an_institution(institution_app):
    client = institution_app["client"]

    for claimant in ("visitor_headers", "moderator_headers", "admin_headers"):
        affiliation = client.post(
            "/api/v1/institutions/affiliation",
            headers=institution_app[claimant],
            json={"name": "Museum Networks", "confirm_create": True},
        )
        assert affiliation.status_code == 200
        assert affiliation.json["data"]["created"] is False
        assert affiliation.json["data"]["user"]["affiliation"] == "Museum Networks"
        assert affiliation.json["data"]["membership"] is None

    with institution_app["app"].app_context():
        assert Institution.query.filter_by(name="Museum Networks").first() is None


def test_institution_roster_respects_visibilities_and_never_exposes_account_settings(institution_app):
    owner = db.session.get(User, institution_app["owner_id"])
    owner.display_name = "Private owner"
    owner.mfa_enabled = True
    owner.bio = "Private biography"
    owner.show_email = True
    manager = db.session.get(User, institution_app["manager_id"])
    manager.display_name = "Visible manager"
    manager.profile_visibility = "internal"
    manager.show_email = False
    db.session.commit()
    client = institution_app["client"]
    base = f'/api/v1/institutions/{institution_app["institution_id"]}'

    for path in (base, f"{base}/memberships"):
        response = client.get(path, headers=institution_app["reader_headers"])
        assert response.status_code == 200
        data = response.json["data"]
        rows = data.get("institution", data)["memberships"]
        identities = {row["user_id"]: row["user"] for row in rows}
        assert identities[owner.id] == {"id": owner.id}
        assert identities[manager.id] == {"id": manager.id, "display_name": "Visible manager", "full_name": None}
        assert identities[institution_app["reader_id"]]["email"].startswith("reader@")
        assert all("capabilities" not in identity and "mfa_enabled" not in identity for identity in identities.values())

    manager.show_email = True
    db.session.commit()
    roster = client.get(f"{base}/memberships", headers=institution_app["reader_headers"]).json["data"]["memberships"]
    assert next(row["user"]["email"] for row in roster if row["user_id"] == manager.id) == manager.email


def test_unicode_name_matching_and_admin_control_of_official_names(institution_app):
    client = institution_app["client"]
    admin = institution_app["admin_headers"]
    created = client.post("/api/v1/institutions", headers=admin,
                          json={"name": "Friedrich-Schiller-Universität Jena", "profile_visibility": "internal"})
    assert created.status_code == 201
    workspace = created.json["data"]["institution"]
    variant = "FRIEDRICH SCHILLER UNIVERSITA\u0308T JENA"
    duplicate = client.post("/api/v1/institutions", headers=admin, json={"name": variant})
    assert duplicate.status_code == 400
    affiliation = client.post("/api/v1/institutions/affiliation", headers=institution_app["visitor_headers"],
                              json={"name": variant})
    assert affiliation.json["data"]["institution"]["id"] == workspace["id"]
    assert affiliation.json["data"]["membership"] is None
    another = client.post("/api/v1/institutions", headers=admin, json={"name": "国立博物館"})
    assert another.status_code == 201
    denied = client.put(f'/api/v1/institutions/{institution_app["institution_id"]}', headers=institution_app["manager_headers"],
                        json={"name": "Renamed without approval"})
    assert denied.status_code == 403


def test_workspace_request_requires_approval_and_only_exposes_own_requests(institution_app):
    client = institution_app["client"]
    base = "/api/v1/institutions/workspace-requests"
    visitor = institution_app["visitor_headers"]
    other = institution_app["reader_headers"]
    admin = institution_app["admin_headers"]

    response = client.post(base, headers=visitor, json={"name": "Musée des Arts", "reason": "Project workspace"})
    assert response.status_code == 201
    pending = response.json["data"]["request"]
    assert pending["status"] == "pending" and pending["institution_id"] is None
    assert "requester" not in pending
    duplicate = client.post(base, headers=visitor, json={"name": "MUSE\u0301E-DES-ARTS"})
    assert duplicate.status_code == 409
    assert client.get(base, headers=other).json["data"]["requests"] == []
    assert client.get(f"{base}?all=true", headers=other).status_code == 403
    assert client.get("/api/v1/institutions", headers=visitor).json["data"]["institutions"] == []

    admin_list = client.get(f"{base}?all=true&status=pending", headers=admin).json["data"]["requests"]
    assert len(admin_list) == 1
    assert admin_list[0]["requester"]["id"] == institution_app["visitor_id"]
    path = f'{base}/{pending["id"]}/decision'
    assert client.patch(path, headers=other, json={"decision": "approve"}).status_code == 403
    approved = client.patch(path, headers=admin, json={"decision": "approve", "note": "Institution confirmed"})
    assert approved.status_code == 200
    row = approved.json["data"]["request"]
    assert row["status"] == "approved" and row["review_note"] == "Institution confirmed"
    assert client.patch(path, headers=admin, json={"decision": "reject"}).status_code == 409
    owner_workspace = client.get(f'/api/v1/institutions/{row["institution_id"]}', headers=visitor)
    assert owner_workspace.status_code == 200
    workspace = owner_workspace.json["data"]["institution"]
    assert workspace["profile_visibility"] == "private"
    assert [(m["user_id"], m["role"]) for m in workspace["memberships"]] == [(institution_app["visitor_id"], "owner")]
    assert client.get(f'/api/v1/institutions/{workspace["id"]}', headers=other).status_code == 404
    assert AuditEvent.query.filter_by(institution_id=workspace["id"], event_type="institution_workspace_request_approved").count() == 1


def test_private_name_request_does_not_reveal_existing_workspace(institution_app):
    client = institution_app["client"]
    base = "/api/v1/institutions/workspace-requests"
    visitor = institution_app["visitor_headers"]
    admin = institution_app["admin_headers"]
    response = client.post(base, headers=visitor, json={"name": "Museum Network"})
    assert response.status_code == 201
    path = f'{base}/{response.json["data"]["request"]["id"]}/decision'
    assert client.patch(path, headers=admin, json={"decision": "approve"}).status_code == 400
    assert client.get(base, headers=visitor).json["data"]["requests"][0]["status"] == "pending"
    rejected = client.patch(path, headers=admin, json={"decision": "reject", "note": "Contact your workspace coordinator."})
    assert rejected.status_code == 200
    assert client.get(base, headers=visitor).json["data"]["requests"][0]["status"] == "rejected"


def test_workspace_decision_rolls_back_institution_if_audit_fails(institution_app, monkeypatch):
    client = institution_app["client"]
    base = "/api/v1/institutions/workspace-requests"
    visitor = institution_app["visitor_headers"]
    pending = client.post(base, headers=visitor, json={"name": "Archive Society"}).json["data"]["request"]

    def fail_audit(**_):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr("services.institution_workspace_request_service.record_audit_event", fail_audit)
    result = client.patch(f'{base}/{pending["id"]}/decision', headers=institution_app["admin_headers"],
                          json={"decision": "approve"})
    assert result.status_code == 500
    assert Institution.query.filter_by(name="Archive Society").first() is None
    requests = client.get(base, headers=visitor).json["data"]["requests"]
    assert requests[0]["status"] == "pending"


def test_membership_rolls_back_when_its_audit_write_fails(institution_app, monkeypatch):
    def fail_audit(**_):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr("services.institution_service.record_audit_event", fail_audit)
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]
    reader_id = institution_app["reader_id"]
    response = client.put(f"/api/v1/institutions/{institution_id}/memberships/{reader_id}",
                          headers=institution_app["manager_headers"], json={"role": "curator"})
    assert response.status_code == 500
    assert InstitutionService().get_membership(institution_id, reader_id).role == InstitutionRole.READER


def test_concurrent_membership_writers_share_the_last_owner_lock(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]
    owner = institution_app["owner_headers"]
    manager = institution_app["manager_headers"]
    membership_path = f"/api/v1/institutions/{institution_id}/memberships"
    owner_path = f'{membership_path}/{institution_app["owner_id"]}'
    manager_path = f'{membership_path}/{institution_app["manager_id"]}'
    assert client.put(manager_path, headers=owner, json={"role": "owner"}).status_code == 200

    def demote_previous_owner():
        return institution_app["app"].test_client().put(owner_path, headers=manager, json={"role": "manager"}).status_code

    with institution_membership_lock(institution_id), ThreadPoolExecutor() as worker:
        assert worker.submit(demote_previous_owner).result(timeout=5) == 409
        assert client.put(manager_path, headers=owner, json={"role": "manager"}).status_code == 200

    assert client.put(owner_path, headers=manager, json={"role": "manager"}).status_code == 403
    assert client.put(owner_path, headers=owner, json={"role": "manager"}).status_code == 400


def test_institution_membership_protects_last_owner_and_clears_default_institution(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]
    owner_id = institution_app["owner_id"]
    reader_id = institution_app["reader_id"]

    demote_response = client.put(
        f"/api/v1/institutions/{institution_id}/memberships/{owner_id}",
        headers=institution_app["owner_headers"],
        json={"role": "manager"},
    )
    assert demote_response.status_code == 400
    assert demote_response.get_json()["error"]["code"] == "VALIDATION_ERROR"

    remove_response = client.delete(
        f"/api/v1/institutions/{institution_id}/memberships/{reader_id}",
        headers=institution_app["owner_headers"],
    )
    assert remove_response.status_code == 200

    with institution_app["app"].app_context():
        reader = db.session.get(User, reader_id)
        assert reader.default_institution_id is None


def test_institution_audit_events_require_manager_access(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    reader_response = client.get(
        f"/api/v1/institutions/{institution_id}/audit-events",
        headers=institution_app["reader_headers"],
    )
    assert reader_response.status_code == 404

    manager_response = client.get(
        f"/api/v1/institutions/{institution_id}/audit-events",
        headers=institution_app["manager_headers"],
    )
    assert manager_response.status_code == 200
    payload = manager_response.get_json()["data"]
    assert payload["pagination"]["total"] >= 1
    assert any(event["event_type"] == "zenodo_credential_created" for event in payload["audit_events"])


def test_institution_audit_keeps_another_members_private_sessions_hidden(institution_app):
    institution_id = institution_app["institution_id"]
    owner_id = institution_app["owner_id"]
    manager_id = institution_app["manager_id"]
    scopes = [("private", owner_id), ("institution", owner_id), ("private", manager_id)]
    session_ids = []
    for index, (scope, user_id) in enumerate(scopes):
        session = Session(user_id=user_id, institution_id=institution_id, sharing_scope=scope,
                          session_dir=f"/tmp/audit-{index}", hdpc_path=f"/tmp/audit-{index}/test.hdpc")
        db.session.add(session)
        db.session.flush()
        session_ids.append(session.id)
        record_audit_event(actor_user_id=user_id, institution_id=institution_id, session_id=session.id,
                           event_type="test_session_change", entity_type="session", entity_id=session.id)
    db.session.commit()

    client = institution_app["client"]
    url = f"/api/v1/institutions/{institution_id}/audit-events?event_type=test_session_change"
    manager_response = client.get(url, headers=institution_app["manager_headers"])
    assert manager_response.status_code == 200
    manager_payload = manager_response.json["data"]
    assert manager_payload["pagination"]["total"] == 2
    assert {event["session_id"] for event in manager_payload["audit_events"]} == set(session_ids[1:])
    assert next(event["actor"] for event in manager_payload["audit_events"] if event["session_id"] == session_ids[1]) == {"id": owner_id}
    admin_response = client.get(url, headers=institution_app["admin_headers"])
    assert admin_response.status_code == 200
    assert admin_response.json["data"]["pagination"]["total"] == 3


def test_primary_submission_community_is_unique_and_policy_is_resolved(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    first_response = client.post(
        f"/api/v1/institutions/{institution_id}/communities",
        headers=institution_app["manager_headers"],
        json={
            "identifier": "alpha",
            "enabled": True,
            "is_primary_submission": True,
            "sort_order": 0,
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        f"/api/v1/institutions/{institution_id}/communities",
        headers=institution_app["manager_headers"],
        json={
            "identifier": "beta",
            "enabled": True,
            "is_primary_submission": True,
            "is_moderation_default": True,
            "sort_order": 100,
        },
    )
    assert second_response.status_code == 201

    detail_response = client.get(
        f"/api/v1/institutions/{institution_id}",
        headers=institution_app["manager_headers"],
    )
    assert detail_response.status_code == 200
    institution_payload = detail_response.get_json()["data"]["institution"]
    by_identifier = {item["identifier"]: item for item in institution_payload["communities"]}

    assert by_identifier["alpha"]["is_primary_submission"] is False
    assert by_identifier["beta"]["is_primary_submission"] is True
    assert institution_payload["community_policy"]["primary_submission_community"] == "beta"
    assert institution_payload["community_policy"]["moderation_default_communities"] == ["beta"]
    assert institution_payload["community_policy"]["default_communities"] == ["beta", "alpha"]


def test_moderator_can_list_all_institutions_with_summary_only(institution_app):
    client = institution_app["client"]

    response = client.get(
        "/api/v1/institutions?all=true",
        headers=institution_app["moderator_headers"],
    )

    assert response.status_code == 200
    institutions = response.get_json()["data"]["institutions"]
    assert len(institutions) == 1
    assert institutions[0]["name"] == "Museum Network"
    assert institutions[0]["member_count"] == 3
    assert institutions[0]["role"] is None
    assert "memberships" not in institutions[0]
    assert "communities" not in institutions[0]
    assert "zenodo_credentials" not in institutions[0]


def test_admin_can_list_all_institutions_with_summary_only(institution_app):
    client = institution_app["client"]

    response = client.get(
        "/api/v1/institutions?all=true",
        headers=institution_app["admin_headers"],
    )

    assert response.status_code == 200
    institutions = response.get_json()["data"]["institutions"]
    assert len(institutions) == 1
    assert institutions[0]["name"] == "Museum Network"
    assert institutions[0]["member_count"] == 3
    assert institutions[0]["role"] is None
    assert "memberships" not in institutions[0]
    assert "communities" not in institutions[0]
    assert "zenodo_credentials" not in institutions[0]


def test_manager_can_validate_institution_credential_with_live_write_report(monkeypatch, institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    class _Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    monkeypatch.setattr("services.zenodo_credential_service.requests.get", lambda *args, **kwargs: _Response(200, []))
    monkeypatch.setattr("services.zenodo_credential_service.requests.post", lambda *args, **kwargs: _Response(403, {"message": "Missing deposit:write"}))

    response = client.post(
        f"/api/v1/institutions/{institution_id}/zenodo-credentials/sandbox/validate",
        headers=institution_app["manager_headers"],
    )

    assert response.status_code == 200
    credential = response.get_json()["data"]["credential"]
    assert credential["validation_mode"] == "live_write_cleanup"
    assert credential["validation_status"] == "invalid"
    assert credential["recommended_scopes"] == ["deposit:write", "deposit:actions"]
    assert credential["validation_report"]["capabilities"]["deposit_read"]["status"] == "verified"
    assert credential["validation_report"]["capabilities"]["draft_create"]["status"] == "invalid"


def test_reader_cannot_validate_institution_credential(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    response = client.post(
        f"/api/v1/institutions/{institution_id}/zenodo-credentials/sandbox/validate",
        headers=institution_app["reader_headers"],
    )

    assert response.status_code == 404
