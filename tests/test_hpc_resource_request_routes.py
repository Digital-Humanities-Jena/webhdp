from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import HpcResourceRequest, Notification, User, UserRole
from middleware import setup_error_handlers
from routes.admin_routes import admin_bp
from routes.hpc_resource_request_routes import hpc_resource_request_bp
from services.hpc_allocation_service import HpcAllocationService
from services.user_service import UserService


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "hpc-request-test"
    app.config["JWT_SECRET_KEY"] = "hpc-request-jwt"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(hpc_resource_request_bp, url_prefix="/api/v1/hpc-resource-requests")
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    return app


def _seed_users(app):
    with app.app_context():
        db.create_all()
        user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        db.session.add_all([user, admin])
        db.session.commit()
        return {
            "user_id": user.id,
            "admin_id": admin.id,
            "user_headers": {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"},
            "admin_headers": {"Authorization": f"Bearer {create_access_token(identity=str(admin.id))}"},
        }


def test_hpc_resource_request_validation_and_duplicate_pending():
    app = _make_app()
    seeded = _seed_users(app)
    client = app.test_client()

    invalid = client.post(
        "/api/v1/hpc-resource-requests",
        json={"full_name": "", "affiliation": "Institute", "use_cases": ["3D Models"]},
        headers=seeded["user_headers"],
    )
    assert invalid.status_code == 400

    created = client.post(
        "/api/v1/hpc-resource-requests",
        json={"full_name": "Ada Lovelace", "affiliation": "Analytical Institute", "use_cases": ["3D Models", "Documents"]},
        headers=seeded["user_headers"],
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["request"]["status"] == "pending"

    duplicate = client.post(
        "/api/v1/hpc-resource-requests",
        json={"full_name": "Ada Lovelace", "affiliation": "Analytical Institute", "use_cases": ["Documents"]},
        headers=seeded["user_headers"],
    )
    assert duplicate.status_code == 400

    with app.app_context():
        user = db.session.get(User, seeded["user_id"])
        assert user.full_name == "Ada Lovelace"
        assert user.affiliation == "Analytical Institute"
        admin_notification = Notification.query.filter_by(
            recipient_user_id=seeded["admin_id"],
            notification_type="hpc.request_submitted",
        ).one()
        assert admin_notification.title == "HPC access requested"
        assert admin_notification.action_url == "/admin/hpc-access"
        assert admin_notification.entity_type == "hpc_resource_request"
        db.session.remove()
        db.drop_all()


def test_new_normal_users_require_onboarding_but_admins_do_not():
    app = _make_app()
    with app.app_context():
        db.create_all()
        user = UserService().create_user("new-user@example.com", "password123", UserRole.USER)
        admin = UserService().create_user("new-admin@example.com", "password123", UserRole.ADMIN)
        assert user.onboarding_required is True
        assert admin.onboarding_required is False
        db.session.remove()
        db.drop_all()


def test_admin_approval_grants_hpc_capability_and_overview_lists_access():
    app = _make_app()
    seeded = _seed_users(app)
    client = app.test_client()
    created = client.post(
        "/api/v1/hpc-resource-requests",
        json={"full_name": "Grace Hopper", "affiliation": "Navy", "use_cases": ["Historical Data"]},
        headers=seeded["user_headers"],
    )
    request_id = created.get_json()["data"]["request"]["id"]

    approved = client.post(
        f"/api/v1/admin/hpc-resource-requests/{request_id}/approve",
        json={"comment": "Approved"},
        headers=seeded["admin_headers"],
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["request"]["status"] == "approved"

    overview = client.get("/api/v1/admin/hpc-access-users", headers=seeded["admin_headers"])
    assert overview.status_code == 200
    emails = {user["email"]: user for user in overview.get_json()["data"]["users"]}
    assert emails["user@example.com"]["hpc_access_source"] == "explicit"
    assert emails["admin@example.com"]["hpc_access_source"] == "implicit_admin"

    with app.app_context():
        user = db.session.get(User, seeded["user_id"])
        assert user.has_capability("hpc_link_access")
        assert HpcAllocationService.user_can_allocate(user, purpose="workflow") is True
        user_notification = Notification.query.filter_by(
            recipient_user_id=seeded["user_id"],
            notification_type="hpc.request_approved",
        ).one()
        assert user_notification.title == "HPC access approved"
        admin_notification = Notification.query.filter_by(
            recipient_user_id=seeded["admin_id"],
            notification_type="hpc.access_granted",
        ).one()
        assert admin_notification.title == "HPC access granted"
        assert admin_notification.action_url == "/admin/hpc-access"
        db.session.remove()
        db.drop_all()


def test_admin_rejection_preserves_no_hpc_access_and_allows_resubmission():
    app = _make_app()
    seeded = _seed_users(app)
    client = app.test_client()
    created = client.post(
        "/api/v1/hpc-resource-requests",
        json={"full_name": "Mary Somerville", "affiliation": "Royal Society", "use_cases": ["Documents"]},
        headers=seeded["user_headers"],
    )
    request_id = created.get_json()["data"]["request"]["id"]

    rejected = client.post(
        f"/api/v1/admin/hpc-resource-requests/{request_id}/reject",
        json={"comment": "Need more detail"},
        headers=seeded["admin_headers"],
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["data"]["request"]["status"] == "rejected"

    resubmitted = client.post(
        "/api/v1/hpc-resource-requests",
        json={"full_name": "Mary Somerville", "affiliation": "Royal Society", "use_cases": ["Documents"], "notes": "More detail"},
        headers=seeded["user_headers"],
    )
    assert resubmitted.status_code == 201

    with app.app_context():
        user = db.session.get(User, seeded["user_id"])
        assert not user.has_capability("hpc_link_access")
        assert HpcResourceRequest.query.count() == 2
        db.session.remove()
        db.drop_all()


def test_non_admin_cannot_call_admin_hpc_request_routes():
    app = _make_app()
    seeded = _seed_users(app)
    response = app.test_client().get("/api/v1/admin/hpc-resource-requests", headers=seeded["user_headers"])
    assert response.status_code == 403
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_direct_hpc_capability_grant_notifies_admins():
    app = _make_app()
    seeded = _seed_users(app)
    client = app.test_client()

    response = client.put(
        f"/api/v1/admin/users/{seeded['user_id']}/capabilities",
        json={"capabilities": ["hpc_link_access"]},
        headers=seeded["admin_headers"],
    )
    assert response.status_code == 200

    with app.app_context():
        notification = Notification.query.filter_by(
            recipient_user_id=seeded["admin_id"],
            notification_type="hpc.access_granted",
        ).one()
        assert notification.entity_type == "user"
        assert notification.entity_id == str(seeded["user_id"])
        assert notification.action_url == "/admin/hpc-access"
        db.session.remove()
        db.drop_all()


def test_revoke_removes_explicit_hpc_access_but_not_admin_implicit_access():
    app = _make_app()
    seeded = _seed_users(app)
    client = app.test_client()
    with app.app_context():
        user = db.session.get(User, seeded["user_id"])
        user.set_capabilities(["hpc_link_access"])
        db.session.commit()

    revoked = client.post(
        f"/api/v1/admin/hpc-access-users/{seeded['user_id']}/revoke",
        headers=seeded["admin_headers"],
    )
    assert revoked.status_code == 200
    admin_revoke = client.post(
        f"/api/v1/admin/hpc-access-users/{seeded['admin_id']}/revoke",
        headers=seeded["admin_headers"],
    )
    assert admin_revoke.status_code == 403

    with app.app_context():
        user = db.session.get(User, seeded["user_id"])
        assert not user.has_capability("hpc_link_access")
        db.session.remove()
        db.drop_all()
