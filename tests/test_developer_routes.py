import unittest

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import User, UserRole
from routes.developer_routes import developer_bp


class TestDeveloperRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "jwt-test-secret"
        self.app.config["ENABLE_RENDERER"] = True
        self.app.config["ENABLE_USDZ_CONVERSION"] = False
        self.app.config["ENABLE_LOCAL_EDM_VALIDATION"] = True
        self.app.config["LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR"] = True
        self.app.config["NOTIFICATION_SSE_ENABLED"] = False
        self.app.config["BACKUP_ENABLED"] = False
        self.app.config["STORAGE_MODE"] = "local"
        self.app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"

        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(developer_bp, url_prefix="/developer")

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _create_user(self, email, role=UserRole.USER, capabilities=None):
        with self.app.app_context():
            user = User(email=email, role=role)
            user.set_password("password")
            if capabilities:
                user.set_capabilities(capabilities)
            db.session.add(user)
            db.session.commit()
            token = create_access_token(identity=str(user.id))
            return user.id, {"Authorization": f"Bearer {token}"}

    def test_developer_status_requires_auth(self):
        with self.app.test_client() as client:
            response = client.get("/developer/status")

        self.assertEqual(response.status_code, 401)

    def test_developer_status_rejects_regular_user(self):
        _, headers = self._create_user("user@example.com")

        with self.app.test_client() as client:
            response = client.get("/developer/status", headers=headers)

        self.assertEqual(response.status_code, 403)

    def test_developer_status_allows_developer_capability(self):
        _, headers = self._create_user("developer@example.com", capabilities=["developer_access"])

        with self.app.test_client() as client:
            response = client.get("/developer/status", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        data = payload["data"]
        self.assertTrue(data["developer_mode"])
        self.assertEqual(data["runtime"]["storage_mode"], "local")
        self.assertIn("make doctor", [item["command"] for item in data["commands"]])
        self.assertIn("make docs-check", [item["command"] for item in data["commands"]])
        self.assertIn("make devcontainer-check", [item["command"] for item in data["commands"]])
        self.assertIn("make golden-workflow", [item["command"] for item in data["commands"]])
        self.assertTrue(any(doc["path"] == "/docs/developer-onboarding" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/devcontainer" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/first-pr-walkthrough" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/developer-troubleshooting" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/contributor-architecture-map" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/developer-glossary" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/pr-scope-examples" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/known-development-warnings" for doc in data["docs"]))
        self.assertTrue(any(doc["path"] == "/docs/golden-workflow" for doc in data["docs"]))
        self.assertNotIn("SQLALCHEMY_DATABASE_URI", data["runtime"])

    def test_developer_status_allows_admin(self):
        _, headers = self._create_user("admin@example.com", role=UserRole.ADMIN)

        with self.app.test_client() as client:
            response = client.get("/developer/status", headers=headers)

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
