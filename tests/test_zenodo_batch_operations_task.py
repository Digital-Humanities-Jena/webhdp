import os
import sys
import tempfile
import types
from types import SimpleNamespace

from flask import Flask

sys.modules.setdefault(
    "celery_app",
    types.SimpleNamespace(celery=types.SimpleNamespace(task=lambda *args, **kwargs: (lambda fn: fn))),
)

import tasks
from database.database import db
from database.models import Session as DBSession, User, UserRole
import pytest


class _DummyTaskSelf:
    def __init__(self):
        self.request = SimpleNamespace(id="zenodo-community-task-1")
        self.states = []

    def update_state(self, state=None, meta=None):
        self.states.append({"state": state, "meta": meta})


@pytest.mark.parametrize('completed,failed,skipped,severity', [
    (2, 0, 0, 'success'), (1, 1, 0, 'warning'), (0, 2, 0, 'error'), (0, 0, 2, 'warning'),
])
def test_session_batch_notification_matches_item_outcomes(monkeypatch, tmp_path, completed, failed, skipped, severity):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    app.project_service = object()
    notices = []
    monkeypatch.setattr(tasks, 'record_session_batch_task_launch', lambda **kw: None)
    monkeypatch.setattr(tasks, 'update_session_batch_task_entry', lambda *a, **kw: None)
    monkeypatch.setattr(tasks, 'notify_user', lambda **kw: notices.append(kw))
    monkeypatch.setattr(tasks.publishing_context_service, 'resolve_token_for_session', lambda *a, **kw: {'token': 'test-token'})
    monkeypatch.setattr(tasks, 'execute_session_batch_operation', lambda **kw: {
        'status': 'completed_with_errors' if failed else 'completed',
        'summary': {'completed': completed, 'failed': failed, 'skipped': skipped},
    })
    with app.app_context():
        db.create_all()
        user = User(email='batch@example.com', password_hash='test-only-hash', is_verified=True)
        db.session.add(user)
        db.session.flush()
        row = DBSession(user_id=user.id, session_dir=str(tmp_path), hdpc_path=str(tmp_path / 'project.hdpc'))
        db.session.add(row)
        db.session.commit()
        tasks.execute_session_batch_operation_task(_DummyTaskSelf(), session_id=row.id,
            operation_type='upload_files', target_ids=[1, 2], requested_by_user_id=user.id)
        assert notices[0]['severity'] == severity
        assert f'{completed} completed, {failed} failed, {skipped} skipped' in notices[0]['body']
        assert notices[0]['action_url'] == f'/sessions/{row.id}/records'
        db.session.remove()
        db.drop_all()


def test_zenodo_batch_community_operation_uses_local_hdpc_without_remote_load(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    temp_dir = tempfile.TemporaryDirectory()
    hdpc_path = os.path.join(temp_dir.name, "session.hdpc")
    open(hdpc_path, "a", encoding="utf-8").close()

    captured = {"calls": [], "history": [], "resolved": []}

    class StubProjectService:
        def append_community_to_record(self, **kwargs):
            captured["calls"].append(kwargs)
            return {
                "success": True,
                "result": {
                    "status": "succeeded",
                    "message": "ok",
                    "communities_after": ["omega"],
                    "rate_limited_waits": 0,
                },
            }

    monkeypatch.setattr(tasks, "update_task_entry", lambda task_id, **kwargs: captured["history"].append((task_id, kwargs)))
    monkeypatch.setattr(
        tasks.publishing_context_service,
        "resolve_token_for_session",
        lambda session_row, environment, **kwargs: captured["resolved"].append((session_row.id, environment, kwargs))
        or {"source": "institution", "token": "resolved-production-token"},
    )
    app.project_service = StubProjectService()

    with app.app_context():
        db.create_all()
        user = User(email="batch@example.com", role=UserRole.ADMIN, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        session_row = DBSession(user_id=user.id, session_dir=temp_dir.name, hdpc_path=hdpc_path, status="completed")
        db.session.add(session_row)
        db.session.commit()

        task_self = _DummyTaskSelf()
        result = tasks.execute_zenodo_batch_community_operation(
            task_self,
            operation="append_if_missing",
            remove_mode=None,
            community_identifier="omega",
            requested_by_user_id=user.id,
            selected_records=[
                {
                    "session_id": session_row.id,
                    "local_record_id": 5,
                    "record_title": "Record A",
                    "record_status": "published",
                    "zenodo_record_id": "9005",
                    "is_sandbox": False,
                    "communities_normalized": [],
                    "operation_eligibility": {
                        "append_if_missing": {
                            "eligible": True,
                            "reason": "",
                            "mode": "published_edit_publish",
                        }
                    },
                }
            ],
        )

        assert result["summary"]["succeeded"] == 1
        assert captured["resolved"] == [
            (session_row.id, "production", {"actor_user_id": user.id, "require_credential": True})
        ]
        assert captured["calls"] == [
            {
                "local_record_id": 5,
                "community_identifier": "omega",
                "hdpc_path": hdpc_path,
                "access_token": "resolved-production-token",
            }
        ]

    temp_dir.cleanup()
