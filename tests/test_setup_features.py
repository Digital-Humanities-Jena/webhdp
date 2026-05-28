import unittest
from unittest.mock import MagicMock, patch
from flask import Flask
from flask_jwt_extended import JWTManager
from routes.setup_routes import setup_bp
from database.database import db
from database.models import User, UserRole, SystemConfig
import os

class TestSetupFeatures(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_key'
        self.app.config['JWT_SECRET_KEY'] = 'jwt_test_key'
        self.app.config['SETUP_BOOTSTRAP_TOKEN'] = 'setup-test-token'
        self.app.config['WEBHDP_DEPLOYMENT_MODE'] = 'local'
        self.app.config['WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS'] = True

        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(setup_bp, url_prefix='/setup')

        # Mock services
        self.app.fast_renderer_service = MagicMock()
        self.app.fast_renderer_service.check_health.return_value = True
        self.app.session_manager = MagicMock()
        self.app.session_manager.create_session_dirs.return_value = ("/tmp/hdpc", "/tmp/out", "/tmp/uploads", "/tmp/session")

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_create_admin(self):
        with self.app.test_client() as client:
            headers = {"X-Setup-Token": "setup-test-token"}
            # 1. Create Admin
            resp = client.post('/setup/create-admin', json={
                "email": "admin@example.com",
                "password": "securepassword"
            }, headers=headers)
            self.assertEqual(resp.status_code, 200)

            with self.app.app_context():
                user = User.query.filter_by(email="admin@example.com").first()
                self.assertIsNotNone(user)
                self.assertEqual(user.role, UserRole.ADMIN)
                self.assertTrue(user.check_password("securepassword"))

            # 2. Try creating again (should succeed/update)
            resp = client.post('/setup/create-admin', json={
                "email": "admin@example.com",
                "password": "newpassword"
            }, headers=headers)
            self.assertEqual(resp.status_code, 200)

            # 3. Bootstrap token must not authorize setup routes after setup is complete
            with self.app.app_context():
                db.session.add(SystemConfig(key="setup_completed", value="true"))
                db.session.commit()

            resp = client.post('/setup/create-admin', json={
                "email": "other@example.com",
                "password": "pass"
            }, headers=headers)
            self.assertEqual(resp.status_code, 403)

    def test_create_admin_requires_setup_authorization(self):
        with self.app.test_client() as client:
            resp = client.post('/setup/create-admin', json={
                "email": "admin@example.com",
                "password": "securepassword"
            })
            self.assertEqual(resp.status_code, 403)

    def test_create_admin_accepts_setup_token_query_param(self):
        with self.app.test_client() as client:
            resp = client.post('/setup/create-admin?setup_token=setup-test-token', json={
                "email": "admin@example.com",
                "password": "securepassword"
            })
            self.assertEqual(resp.status_code, 200)

    @patch('routes.setup_routes.requests.get')
    @patch.dict(os.environ, {"ZENODO_API_KEY": "prod_key", "ZENODO_SANDBOX_API_KEY": "sandbox_key"})
    def test_check_system_zenodo(self, mock_get):
        # Mock Zenodo Responses
        def side_effect(url, **kwargs):
            if "sandbox.zenodo.org" in url:
                # Sandbox success
                m = MagicMock()
                m.status_code = 200
                return m
            elif "zenodo.org" in url:
                # Prod failure
                m = MagicMock()
                m.status_code = 401
                return m
            return MagicMock(status_code=404)

        mock_get.side_effect = side_effect

        with self.app.test_client() as client:
            resp = client.post('/setup/check', headers={"X-Setup-Token": "setup-test-token"})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()['data']

            self.assertTrue(data['blender_reachable'])
            self.assertEqual(data['project_runtime'], "native_hdpc")
            self.assertNotIn('hdp_api_reachable', data)
            self.assertEqual(data['zenodo_sandbox_status'], "Reachable")
            self.assertEqual(data['zenodo_production_status'], "Invalid Key")

    @patch('routes.setup_routes.os.path.exists')
    @patch('routes.setup_routes.shutil.copy')
    @patch('routes.setup_routes.os.listdir')
    def test_run_test_render(self, mock_listdir, mock_copy, mock_exists):
        # Setup mocks
        mock_exists.return_value = True
        mock_listdir.return_value = []
        self.app.fast_renderer_service.render.return_value = {"success": True}

        with self.app.test_client() as client:
            resp = client.post('/setup/test-render', headers={"X-Setup-Token": "setup-test-token"})
            self.assertEqual(resp.status_code, 200)

            # Verify render was called with custom_angles
            call_args = self.app.fast_renderer_service.render.call_args
            _, kwargs = call_args
            options = kwargs.get('options', {})
            self.assertIn('custom_angles', options)
            self.assertEqual(len(options['custom_angles']), 2)

if __name__ == '__main__':
    unittest.main()
