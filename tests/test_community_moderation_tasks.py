import sys
import types
from types import SimpleNamespace

from flask import Flask

sys.modules.setdefault(
    "celery_app",
    types.SimpleNamespace(celery=types.SimpleNamespace(task=lambda *args, **kwargs: (lambda fn: fn))),
)

import tasks
from database.database import db
from database.models import User, UserRole
from services.community_moderation_sweep_service import CommunityModerationSweepService


class _DummyTaskSelf:
    def __init__(self):
        self.request = SimpleNamespace(id="community-task-1")
        self.states = []

    def update_state(self, state=None, meta=None):
        self.states.append({"state": state, "meta": meta})


def test_community_moderation_task_accepts_requests_with_note(monkeypatch):
    app = Flask(__name__)
    captured = {"calls": [], "history": []}

    def _mock_perform(request_id, action, *, note=None, wait_callback=None):
        captured["calls"].append({"request_id": request_id, "action": action, "note": note})
        if wait_callback:
            wait_callback("retry_after", 1, response=None)
        return {
            "request_id": request_id,
            "status": "accepted" if action == "accept" else "declined",
            "updated": "2026-03-26T10:00:00+00:00",
        }

    monkeypatch.setattr(tasks.zenodo_moderation_service, "perform_request_action", _mock_perform)
    monkeypatch.setattr(
        tasks,
        "update_community_moderation_task_entry",
        lambda task_id, **kwargs: captured["history"].append((task_id, kwargs)),
    )

    task_self = _DummyTaskSelf()
    with app.app_context():
        result = tasks._execute_community_moderation_batch_impl(
            task_self,
            action="accept",
            community_identifier="3d-big-data-space",
            note="Approved.",
            selected_requests=[
                {"request_id": "req-1", "title": "Alpha", "type": "community-submission"},
                {"request_id": "req-2", "title": "Beta", "type": "community-submission"},
            ],
        )

    assert [item["request_id"] for item in captured["calls"]] == ["req-1", "req-2"]
    assert all(item["note"] == "Approved." for item in captured["calls"])
    assert result["summary"]["accepted"] == 2
    assert result["summary"]["failed"] == 0
    assert result["summary"]["rate_limited_waits"] == 2


def test_community_moderation_task_declines_without_note(monkeypatch):
    app = Flask(__name__)
    captured = {"calls": []}

    def _mock_perform(request_id, action, *, note=None, wait_callback=None):
        captured["calls"].append({"request_id": request_id, "action": action, "note": note})
        return {
            "request_id": request_id,
            "status": "declined",
            "updated": "2026-03-26T10:00:00+00:00",
        }

    monkeypatch.setattr(tasks.zenodo_moderation_service, "perform_request_action", _mock_perform)
    monkeypatch.setattr(tasks, "update_community_moderation_task_entry", lambda *args, **kwargs: None)

    task_self = _DummyTaskSelf()
    with app.app_context():
        result = tasks._execute_community_moderation_batch_impl(
            task_self,
            action="decline",
            community_identifier="3d-big-data-space",
            note="",
            selected_requests=[{"request_id": "req-9", "title": "Gamma", "type": "inclusion-request"}],
        )

    assert captured["calls"] == [{"request_id": "req-9", "action": "decline", "note": ""}]
    assert result["summary"]["declined"] == 1
    assert result["summary"]["failed"] == 0


def _sweep_summary(community_identifier="3dbigdataspace"):
    return {
        "community": {
            "id": "community-1",
            "slug": community_identifier,
            "title": "3D Big Data Space",
            "identifier_used": community_identifier,
            "links": {},
        },
        "status": "submitted",
        "request_type": None,
        "total": 2,
        "preview": [
            {
                "request_id": "req-1",
                "number": "1",
                "title": "Alpha",
                "type": "inclusion-request",
                "status": "submitted",
                "topic_record": "record-1",
                "is_open": True,
                "links": {"actions": {"accept": "a", "decline": "d"}},
            }
        ],
        "preview_count": 1,
        "preview_actionable_count": 1,
        "action": "accept",
        "api_key_context": {"configured": True},
    }


def test_community_moderation_sweep_repeated_page_one(monkeypatch):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        user = User(email="mod@example.com", role=UserRole.MODERATOR, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        monkeypatch.setattr(tasks.zenodo_moderation_service, "summarize_community_requests", lambda *args, **kwargs: _sweep_summary())
        service = CommunityModerationSweepService()
        plan = service.build_plan(community_identifier="3dbigdataspace", action="accept")
        job = service.create_job(
            user=user,
            community_identifier="3dbigdataspace",
            action="accept",
            expected_plan_checksum=plan["plan_checksum"],
            confirmation_text=plan["confirmation_text"],
        )

        pages = [
            {
                "total": 2,
                "requests": [
                    {
                        "request_id": "req-1",
                        "number": "1",
                        "title": "Alpha",
                        "type": "inclusion-request",
                        "status": "submitted",
                        "topic_record": "record-1",
                        "is_open": True,
                        "links": {"actions": {"accept": "a", "decline": "d"}},
                    }
                ],
            },
            {
                "total": 1,
                "requests": [
                    {
                        "request_id": "req-2",
                        "number": "2",
                        "title": "Beta",
                        "type": "inclusion-request",
                        "status": "submitted",
                        "topic_record": "record-2",
                        "is_open": True,
                        "links": {"actions": {"accept": "a", "decline": "d"}},
                    }
                ],
            },
            {"total": 0, "requests": []},
        ]
        calls = []

        def _fetch_page(*args, **kwargs):
            calls.append(kwargs.get("page"))
            return pages.pop(0)

        monkeypatch.setattr(tasks.zenodo_moderation_service, "fetch_community_request_page", _fetch_page)
        monkeypatch.setattr(
            tasks.zenodo_moderation_service,
            "perform_request_action",
            lambda request_id, action, **kwargs: {"request_id": request_id, "status": "accepted", "is_open": False},
        )

        result = tasks.execute_community_moderation_sweep(_DummyTaskSelf(), job_id=job.public_id)

    assert calls == [1, 1, 1]
    assert result["summary"]["accepted"] == 2
    assert result["state"] == "SUCCESS"


def test_community_moderation_sweep_cancels_after_current_request(monkeypatch):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        user = User(email="mod2@example.com", role=UserRole.MODERATOR, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        monkeypatch.setattr(tasks.zenodo_moderation_service, "summarize_community_requests", lambda *args, **kwargs: _sweep_summary())
        service = CommunityModerationSweepService()
        plan = service.build_plan(community_identifier="3dbigdataspace", action="accept")
        job = service.create_job(
            user=user,
            community_identifier="3dbigdataspace",
            action="accept",
            expected_plan_checksum=plan["plan_checksum"],
            confirmation_text=plan["confirmation_text"],
        )

        monkeypatch.setattr(
            tasks.zenodo_moderation_service,
            "fetch_community_request_page",
            lambda *args, **kwargs: {
                "total": 1,
                "requests": [
                    {
                        "request_id": "req-1",
                        "number": "1",
                        "title": "Alpha",
                        "type": "inclusion-request",
                        "status": "submitted",
                        "topic_record": "record-1",
                        "is_open": True,
                        "links": {"actions": {"accept": "a", "decline": "d"}},
                    }
                ],
            },
        )

        def _perform(request_id, action, **kwargs):
            service.request_cancel(job)
            return {"request_id": request_id, "status": "accepted", "is_open": False}

        monkeypatch.setattr(tasks.zenodo_moderation_service, "perform_request_action", _perform)

        result = tasks.execute_community_moderation_sweep(_DummyTaskSelf(), job_id=job.public_id)

    assert result["state"] == "CANCELLED"
    assert result["summary"]["accepted"] == 1
