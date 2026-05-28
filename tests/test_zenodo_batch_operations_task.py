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


class _DummyTaskSelf:
    def __init__(self):
        self.request = SimpleNamespace(id="zenodo-community-task-1")
        self.states = []

    def update_state(self, state=None, meta=None):
        self.states.append({"state": state, "meta": meta})


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
        lambda session_row, environment: captured["resolved"].append((session_row.id, environment))
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
        assert captured["resolved"] == [(session_row.id, "production")]
        assert captured["calls"] == [
            {
                "local_record_id": 5,
                "community_identifier": "omega",
                "hdpc_path": hdpc_path,
                "access_token": "resolved-production-token",
            }
        ]

    temp_dir.cleanup()
