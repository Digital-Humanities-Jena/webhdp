import pytest
from flask import Flask
from sqlalchemy.exc import IntegrityError

from database.database import db
from database.models import Institution, User, UserRole


@pytest.fixture()
def constraint_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'profile-constraints.db'}")
    monkeypatch.setenv("SECRET_KEY", "profile-constraints-secret")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'profile-constraints.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "profile-constraints-secret"
    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_profile_visibility_check_constraints_reject_public_values(constraint_app):
    with constraint_app.app_context():
        user = User(email="public@example.com", role=UserRole.USER, profile_visibility="public")
        user.set_password("password123")
        db.session.add(user)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()

        institution = Institution(name="Public Museum", slug="public-museum", profile_visibility="public")
        db.session.add(institution)

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()


def test_profile_visibility_check_constraints_accept_private_and_internal_values(constraint_app):
    with constraint_app.app_context():
        user = User(email="internal@example.com", role=UserRole.USER, profile_visibility="internal")
        user.set_password("password123")
        institution = Institution(name="Private Museum", slug="private-museum", profile_visibility="private")
        db.session.add_all([user, institution])
        db.session.commit()

        assert user.id is not None
        assert institution.id is not None
