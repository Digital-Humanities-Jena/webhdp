from pathlib import Path

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import User, UserRole
from middleware import setup_error_handlers
from routes.admin_routes import admin_bp


def _make_app(db_path: Path, backup_dir: Path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["BACKUP_LOCAL_DIR"] = str(backup_dir)
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    return app


def test_admin_backup_routes_create_status_list_and_prune(tmp_path, monkeypatch):
    db_path = tmp_path / "instance" / "hdp_web.db"
    backup_dir = tmp_path / "backups"
    db_path.parent.mkdir(parents=True)
    backup_dir.mkdir()
    (tmp_path / "hdp-shared" / "sessions").mkdir(parents=True)
    (tmp_path / "local_input").mkdir()
    (tmp_path / "local_output").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "admin-backup-secret-" + "z" * 32)

    app = _make_app(db_path, backup_dir)
    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    client = app.test_client()

    create_response = client.post(
        "/api/v1/admin/backups",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "backup_type": "route-test",
            "provider": "local",
            "include_credentials": False,
            "encrypt": True,
            "output_dir": str(backup_dir),
        },
    )
    assert create_response.status_code == 201
    archive_path = Path(create_response.get_json()["data"]["archive_path"])
    assert archive_path.exists()

    status_response = client.get(
        f"/api/v1/admin/backups/status?output_dir={backup_dir}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_response.status_code == 200
    assert status_response.get_json()["data"]["backup_count"] == 1

    list_response = client.get(
        f"/api/v1/admin/backups?output_dir={backup_dir}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    assert len(list_response.get_json()["data"]["backups"]) == 1

    prune_response = client.post(
        "/api/v1/admin/backups/prune",
        headers={"Authorization": f"Bearer {token}"},
        json={"provider": "local", "output_dir": str(backup_dir), "retention_days": 1, "dry_run": True},
    )
    assert prune_response.status_code == 200
    assert prune_response.get_json()["data"]["dry_run"] is True
