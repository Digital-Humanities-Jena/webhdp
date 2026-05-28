from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import HpcAllocation, HpcLinkConfig, Notification, Session as DBSession, User, UserRole
from middleware import setup_error_handlers
from routes.admin_routes import admin_bp
from services.hpc_allocation_service import HpcAllocationService
from services.user_service import UserService


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "admin-monitor-test"
    app.config["JWT_SECRET_KEY"] = "admin-monitor-jwt"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.hpc_allocation_service = HpcAllocationService()
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    return app


def _seed(app):
    with app.app_context():
        db.create_all()
        user = User(email="runner@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        db.session.add_all([user, admin])
        db.session.flush()
        session = DBSession(
            user_id=user.id,
            session_dir="/tmp/monitor-session",
            hdpc_path="/tmp/monitor-session/session.hdpc",
            status="processing",
        )
        db.session.add(session)
        db.session.flush()
        allocation = HpcAllocation(
            user_id=user.id,
            session_id=session.id,
            purpose="workflow",
            status="running",
            requested_partition="partition-b",
            requested_gpu_count=1,
            requested_duration_minutes=30,
            node_name="gpu-01",
        )
        db.session.add(allocation)
        db.session.commit()
        return {
            "user_id": user.id,
            "admin_id": admin.id,
            "session_id": session.id,
            "allocation_id": allocation.public_id,
            "admin_headers": {"Authorization": f"Bearer {create_access_token(identity=str(admin.id))}"},
            "user_headers": {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"},
        }


def test_hpc_config_default_global_limit_is_three():
    app = _make_app()
    with app.app_context():
        db.create_all()
        config = app.hpc_allocation_service.get_or_create_config()
        assert config.max_active_allocations == 3
        assert app.hpc_allocation_service.serialize_config(config)["max_active_allocations"] == 3
        db.session.remove()
        db.drop_all()


def test_admin_monitoring_lists_and_terminates_sessions_and_allocations():
    app = _make_app()
    seeded = _seed(app)
    client = app.test_client()

    response = client.get("/api/v1/admin/session-monitoring", headers=seeded["admin_headers"])
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["summary"]["global_hpc_limit"] == 3
    assert payload["sessions"][0]["id"] == seeded["session_id"]
    assert payload["allocations"][0]["allocation_id"] == seeded["allocation_id"]

    forbidden = client.get("/api/v1/admin/session-monitoring", headers=seeded["user_headers"])
    assert forbidden.status_code == 403

    terminated = client.post(
        f"/api/v1/admin/session-monitoring/allocations/{seeded['allocation_id']}/terminate",
        headers=seeded["admin_headers"],
    )
    assert terminated.status_code == 200
    assert terminated.get_json()["data"]["allocation"]["status"] == "released"

    terminated_session = client.post(
        f"/api/v1/admin/session-monitoring/sessions/{seeded['session_id']}/terminate",
        headers=seeded["admin_headers"],
    )
    assert terminated_session.status_code == 200
    assert terminated_session.get_json()["data"]["session"]["status"] == "cancelled"

    with app.app_context():
        allocation = HpcAllocation.query.filter_by(public_id=seeded["allocation_id"]).first()
        session = db.session.get(DBSession, seeded["session_id"])
        assert allocation.status == "released"
        assert session.status == "cancelled"
        db.session.remove()
        db.drop_all()


def test_admin_is_notified_when_new_user_registers():
    app = _make_app()
    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        db.session.add(admin)
        db.session.commit()

        user = UserService().create_user("new-user@example.com", "password123", UserRole.USER)
        notification = Notification.query.filter_by(
            recipient_user_id=admin.id,
            notification_type="admin.user_registered",
        ).first()
        assert notification is not None
        assert notification.action_url == f"/profiles/users/{user.slug}"
        db.session.remove()
        db.drop_all()
