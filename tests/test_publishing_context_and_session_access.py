import pytest
pytest.importorskip("flask_sqlalchemy")
pytest.importorskip("cryptography.fernet")
from flask import Flask

from database.database import db
from database.models import (
    Institution,
    InstitutionMembership,
    InstitutionRole,
    InstitutionZenodoCommunity,
    Session as DBSession,
    User,
    UserRole,
)
from services.publishing_context_service import PublishingContextService
from services.session_access_service import get_accessible_sessions
from services.zenodo_credential_service import ZenodoCredentialService


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "publishing-context-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_publishing_context_resolves_user_then_institution_then_system(app, monkeypatch):
    credential_service = ZenodoCredentialService()
    publishing_context_service = PublishingContextService()

    with app.app_context():
        user = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.flush()

        institution = Institution(name="Example Museum", slug="example-museum", created_by_user_id=user.id)
        db.session.add(institution)
        db.session.flush()
        db.session.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=user.id,
                role=InstitutionRole.OWNER,
            )
        )
        db.session.add_all(
            [
                InstitutionZenodoCommunity(
                    institution_id=institution.id,
                    identifier="shared-secondary",
                    enabled=True,
                    sort_order=0,
                ),
                InstitutionZenodoCommunity(
                    institution_id=institution.id,
                    identifier="shared-primary",
                    enabled=True,
                    is_primary_submission=True,
                    is_moderation_default=True,
                    sort_order=50,
                ),
            ]
        )
        session_row = DBSession(
            user_id=user.id,
            institution_id=institution.id,
            session_dir="/tmp/example-session",
            hdpc_path="/tmp/example-session/session.hdpc",
            status="active",
            sharing_scope="institution",
            credential_preference="user",
            publishing_user_id=user.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=True,
        )
        db.session.add(session_row)
        db.session.commit()

        credential_service.upsert_credential(
            owner_type="user",
            owner_id=user.id,
            environment="sandbox",
            token="user-sandbox-token",
            actor_user_id=user.id,
        )
        credential_service.upsert_credential(
            owner_type="institution",
            owner_id=institution.id,
            environment="sandbox",
            token="institution-sandbox-token",
            actor_user_id=user.id,
        )

        token_context = publishing_context_service.resolve_token_for_session(session_row, "sandbox")
        assert token_context["source"] == "user"
        assert token_context["token"] == "user-sandbox-token"
        description = publishing_context_service.describe_session(session_row)
        assert description["primary_submission_community"] == "shared-primary"
        assert description["moderation_default_communities"] == ["shared-primary"]
        assert description["default_communities"] == ["shared-primary", "shared-secondary"]

        credential_service.delete_credential(
            owner_type="user",
            owner_id=user.id,
            environment="sandbox",
            actor_user_id=user.id,
        )
        token_context = publishing_context_service.resolve_token_for_session(session_row, "sandbox")
        assert token_context["source"] == "institution"
        assert token_context["token"] == "institution-sandbox-token"

        credential_service.delete_credential(
            owner_type="institution",
            owner_id=institution.id,
            environment="sandbox",
            actor_user_id=user.id,
        )
        monkeypatch.setenv("ZENODO_SANDBOX_API_KEY", "system-sandbox-token")
        token_context = publishing_context_service.resolve_token_for_session(session_row, "sandbox")
        assert token_context["source"] == "system"
        assert token_context["token"] == "system-sandbox-token"


def test_publishing_context_resolves_active_shared_user_credential(app):
    credential_service = ZenodoCredentialService()
    publishing_context_service = PublishingContextService()

    with app.app_context():
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        recipient = User(email="recipient@example.com", role=UserRole.USER, is_verified=True)
        recipient.set_password("password123")
        db.session.add_all([owner, recipient])
        db.session.flush()

        session_row = DBSession(
            user_id=recipient.id,
            session_dir="/tmp/shared-session",
            hdpc_path="/tmp/shared-session/session.hdpc",
            status="active",
            credential_preference="user",
            publishing_user_id=recipient.id,
            default_zenodo_environment="sandbox",
        )
        db.session.add(session_row)
        db.session.commit()

        credential = credential_service.create_credential(
            user_id=owner.id,
            environment="sandbox",
            token="owner-shared-token",
            name="Owner shared sandbox",
            actor_user_id=owner.id,
        )
        share = credential_service.share_credential(
            credential_id=credential.id,
            owner_user_id=owner.id,
            recipient_email=recipient.email,
        )
        credential_service.respond_to_share(share_id=share.id, user_id=recipient.id, status="accepted")
        credential_service.set_active_credential(
            user_id=recipient.id,
            environment="sandbox",
            credential_id=credential.id,
        )

        token_context = publishing_context_service.resolve_token_for_session(session_row, "sandbox")
        assert token_context["source"] == "user"
        assert token_context["shared"] is True
        assert token_context["selected_by_user_id"] == recipient.id
        assert token_context["owner_id"] == owner.id
        assert token_context["token"] == "owner-shared-token"

        description = publishing_context_service.describe_session(session_row)
        assert description["effective_credential_source"] == "user"


def test_describe_sessions_batches_sources_and_community_policy(app, monkeypatch):
    credential_service = ZenodoCredentialService()
    publishing_context_service = PublishingContextService()

    with app.app_context():
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        db.session.add(owner)
        db.session.flush()

        institution = Institution(name="Example Museum", slug="example-museum", created_by_user_id=owner.id)
        db.session.add(institution)
        db.session.flush()
        db.session.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=owner.id,
                role=InstitutionRole.OWNER,
            )
        )
        db.session.add_all(
            [
                InstitutionZenodoCommunity(
                    institution_id=institution.id,
                    identifier="shared-secondary",
                    enabled=True,
                    sort_order=0,
                ),
                InstitutionZenodoCommunity(
                    institution_id=institution.id,
                    identifier="shared-primary",
                    enabled=True,
                    is_primary_submission=True,
                    is_moderation_default=True,
                    sort_order=50,
                ),
            ]
        )
        db.session.flush()

        credential_service.upsert_credential(
            owner_type="user",
            owner_id=owner.id,
            environment="sandbox",
            token="user-sandbox-token",
            actor_user_id=owner.id,
        )
        credential_service.upsert_credential(
            owner_type="institution",
            owner_id=institution.id,
            environment="sandbox",
            token="institution-sandbox-token",
            actor_user_id=owner.id,
        )
        monkeypatch.setenv("ZENODO_API_KEY", "system-production-token")

        user_session = DBSession(
            user_id=owner.id,
            institution_id=institution.id,
            session_dir="/tmp/user-session",
            hdpc_path="/tmp/user-session/session.hdpc",
            status="active",
            sharing_scope="institution",
            credential_preference="user",
            publishing_user_id=owner.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=True,
        )
        institution_session = DBSession(
            user_id=owner.id,
            institution_id=institution.id,
            session_dir="/tmp/institution-session",
            hdpc_path="/tmp/institution-session/session.hdpc",
            status="active",
            sharing_scope="institution",
            credential_preference="institution",
            publishing_user_id=owner.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=True,
        )
        system_session = DBSession(
            user_id=owner.id,
            session_dir="/tmp/system-session",
            hdpc_path="/tmp/system-session/session.hdpc",
            status="active",
            sharing_scope="private",
            credential_preference="user",
            publishing_user_id=owner.id,
            default_zenodo_environment="production",
            use_institution_default_communities=False,
        )
        db.session.add_all([user_session, institution_session, system_session])
        db.session.commit()

        descriptions = publishing_context_service.describe_sessions(
            [user_session, institution_session, system_session]
        )

        assert descriptions[user_session.id]["effective_credential_source"] == "user"
        assert descriptions[institution_session.id]["effective_credential_source"] == "institution"
        assert descriptions[system_session.id]["effective_credential_source"] == "system"
        assert descriptions[user_session.id]["default_communities"] == ["shared-primary", "shared-secondary"]
        assert descriptions[institution_session.id]["moderation_default_communities"] == ["shared-primary"]
        assert descriptions[system_session.id]["default_communities"] == []


def test_get_accessible_sessions_separates_personal_and_institution_scopes(app):
    with app.app_context():
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        colleague = User(email="colleague@example.com", role=UserRole.USER, is_verified=True)
        colleague.set_password("password123")
        db.session.add_all([owner, colleague])
        db.session.flush()

        institution = Institution(name="Shared Lab", slug="shared-lab", created_by_user_id=owner.id)
        db.session.add(institution)
        db.session.flush()
        db.session.add_all(
            [
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=owner.id,
                    role=InstitutionRole.MANAGER,
                ),
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=colleague.id,
                    role=InstitutionRole.READER,
                ),
            ]
        )
        db.session.flush()

        personal_session = DBSession(
            user_id=owner.id,
            session_dir="/tmp/personal",
            hdpc_path="/tmp/personal/session.hdpc",
            status="active",
            institution_id=None,
            sharing_scope="private",
        )
        owner_institution_session = DBSession(
            user_id=owner.id,
            institution_id=institution.id,
            session_dir="/tmp/owner-institution",
            hdpc_path="/tmp/owner-institution/session.hdpc",
            status="active",
            sharing_scope="private",
        )
        shared_institution_session = DBSession(
            user_id=colleague.id,
            institution_id=institution.id,
            session_dir="/tmp/shared-institution",
            hdpc_path="/tmp/shared-institution/session.hdpc",
            status="active",
            sharing_scope="institution",
        )
        private_peer_session = DBSession(
            user_id=colleague.id,
            institution_id=institution.id,
            session_dir="/tmp/private-peer",
            hdpc_path="/tmp/private-peer/session.hdpc",
            status="active",
            sharing_scope="private",
        )
        db.session.add_all(
            [
                personal_session,
                owner_institution_session,
                shared_institution_session,
                private_peer_session,
            ]
        )
        db.session.commit()

        personal_scope_ids = {row.id for row in get_accessible_sessions(owner, scope="personal")}
        institution_scope_ids = {row.id for row in get_accessible_sessions(owner, scope="institution")}
        all_scope_ids = {row.id for row in get_accessible_sessions(owner, scope="all")}

        assert personal_scope_ids == {personal_session.id}
        assert institution_scope_ids == {owner_institution_session.id, shared_institution_session.id}
        assert all_scope_ids == {personal_session.id, owner_institution_session.id, shared_institution_session.id}
