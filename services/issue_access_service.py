from __future__ import annotations

from database.models import Issue, User, UserRole


EDITABLE_REPORTER_STATUSES = {"new", "needs_info"}


def _direct_capability_set(user: User | None) -> set[str]:
    if not user:
        return set()
    return {str(item or "").strip().lower() for item in (user.capabilities or []) if str(item or "").strip()}


def has_developer_access(user: User | None) -> bool:
    return "developer_access" in _direct_capability_set(user)


def can_view_issue_queue(user: User | None) -> bool:
    if not user:
        return False
    if user.role in {UserRole.ADMIN, UserRole.MODERATOR}:
        return True
    return has_developer_access(user)


def can_edit_issue_internal_fields(user: User | None) -> bool:
    return can_view_issue_queue(user)


def can_assign_issues(user: User | None) -> bool:
    return can_view_issue_queue(user)


def is_issue_reporter(issue: Issue | None, user: User | None) -> bool:
    return bool(issue and user and int(issue.reporter_user_id) == int(user.id))


def reporter_can_edit_issue(issue: Issue | None, user: User | None) -> bool:
    return bool(is_issue_reporter(issue, user) and str(getattr(issue, "status", "") or "").strip().lower() in EDITABLE_REPORTER_STATUSES)


def can_view_issue(issue: Issue | None, user: User | None) -> bool:
    if not issue or not user:
        return False
    if can_view_issue_queue(user):
        return True
    return is_issue_reporter(issue, user)


def can_comment_on_issue(issue: Issue | None, user: User | None, *, is_internal: bool = False) -> bool:
    if not can_view_issue(issue, user):
        return False
    if is_internal:
        return can_edit_issue_internal_fields(user)
    return True
