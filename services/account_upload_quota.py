"""Reserve per-account capacity before persisting source uploads."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4
import zipfile

from flask import current_app, g
from sqlalchemy import func, or_

from database.database import db
from database.models import AccountUploadReservation, File, Session, User, UserRole
from exceptions import AppException, ResourceNotFoundError
from services.registry_lock import OperationConflict, registry_lock

SOURCE_LIMIT_BYTES = 50 * 1024**3
ACTIVE_LIMIT = 3
STREAM_LIMIT_BYTES = 50 * 1024**3
STREAM_WINDOW = timedelta(days=1)
RECEIVING_LEASE = timedelta(hours=6)
PENDING_SESSIONS = ("queued", "uploading")


class UploadQuotaError(AppException):
    def __init__(self, code, message, status, usage):
        super().__init__(message, {"usage": usage})
        self.status_code = status
        self.error_code = code


def upload_size(upload):
    if upload is None or not upload.filename:
        return 0
    upload.seek(0, 2)
    try:
        return upload.tell()
    finally:
        upload.seek(0)


def batch_input_size(archive, spreadsheet):
    size = upload_size(archive)
    if size:
        try:
            with zipfile.ZipFile(archive.stream) as zipped:
                size = archive_input_size(zipped, size)
        except zipfile.BadZipFile:
            # The route supplies the normal ZIP validation error.
            pass
        finally:
            archive.seek(0)
    return size + upload_size(spreadsheet)


def archive_input_size(archive, compressed_bytes):
    return max(compressed_bytes, sum(entry.file_size for entry in archive.infolist()))


def _policy(user):
    cfg = current_app.config
    unlimited = user.role == UserRole.ADMIN
    return {
        "limit_bytes": None if unlimited else int(cfg.get("ACCOUNT_UPLOAD_STORAGE_BYTES", SOURCE_LIMIT_BYTES)),
        "active_limit": None if unlimited else int(cfg.get("ACCOUNT_UPLOAD_MAX_ACTIVE", ACTIVE_LIMIT)),
        "stream_limit_bytes": None if unlimited else int(cfg.get("ACCOUNT_UPLOAD_STREAM_DAILY_BYTES", STREAM_LIMIT_BYTES)),
        "request_limit_bytes": cfg.get("MAX_CONTENT_LENGTH"),
    }


def upload_usage(user, now=None):
    now = now or datetime.utcnow()
    receiving_cutoff = now - RECEIVING_LEASE
    stream_cutoff = now - STREAM_WINDOW
    reservations = db.session.query(AccountUploadReservation).filter_by(user_id=user.id)
    tracked_sessions = reservations.with_entities(AccountUploadReservation.session_id).filter(AccountUploadReservation.session_id.is_not(None))
    receiving = reservations.filter(AccountUploadReservation.finished_at.is_(None), AccountUploadReservation.started_at >= receiving_cutoff)
    receiving_sessions = receiving.with_entities(AccountUploadReservation.session_id).filter(AccountUploadReservation.session_id.is_not(None))
    recorded = reservations.filter(AccountUploadReservation.kind == "session", or_(
        AccountUploadReservation.session_id.is_not(None),
        AccountUploadReservation.finished_at.is_(None) & (AccountUploadReservation.started_at >= receiving_cutoff),
    )).with_entities(func.coalesce(func.sum(AccountUploadReservation.size_bytes), 0)).scalar()
    legacy = db.session.query(func.coalesce(func.sum(File.size), 0)).join(Session).filter(
        Session.user_id == user.id, Session.id.not_in(tracked_sessions),
    ).scalar()
    pending = db.session.query(Session).filter(
        Session.user_id == user.id, Session.status.in_(PENDING_SESSIONS),
        func.coalesce(Session.updated_at, Session.created_at) >= receiving_cutoff,
        Session.id.not_in(receiving_sessions),
    ).count()
    stream_bytes = reservations.filter(AccountUploadReservation.kind == "stream", or_(
        AccountUploadReservation.finished_at >= stream_cutoff,
        AccountUploadReservation.finished_at.is_(None) & (AccountUploadReservation.started_at >= receiving_cutoff),
    )).with_entities(func.coalesce(func.sum(AccountUploadReservation.size_bytes), 0)).scalar()
    return {**_policy(user), "used_bytes": int(recorded + legacy), "active": receiving.count() + pending,
            "stream_bytes_last_24_hours": int(stream_bytes)}


@contextmanager
def admit_upload(user_id, size, *, kind="session"):
    """Serialize admission across API workers, without locking while the file is processed."""
    now = datetime.utcnow()
    lock_name = f"account-upload-quota:{user_id}"
    try:
        with registry_lock(lock_name):
            user = db.session.get(User, user_id)
            if user is None:
                raise ResourceNotFoundError("Account not found.")
            usage = upload_usage(user, now)
            if usage["active_limit"] is not None and usage["active"] >= usage["active_limit"]:
                raise UploadQuotaError("UPLOAD_CONCURRENCY_QUOTA", "Wait for one of your current uploads to finish before starting another.", 429, usage)
            if kind == "stream":
                limit = usage["stream_limit_bytes"]
                if limit is not None and usage["stream_bytes_last_24_hours"] + size > limit:
                    raise UploadQuotaError("UPLOAD_STREAM_QUOTA", "This upload exceeds your 24-hour cloud transfer limit.", 413, usage)
            elif kind == "session" and usage["limit_bytes"] is not None and usage["used_bytes"] + size > usage["limit_bytes"]:
                raise UploadQuotaError("UPLOAD_STORAGE_QUOTA", "This upload exceeds your account's source storage limit.", 413, usage)
            db.session.query(AccountUploadReservation).filter(
                AccountUploadReservation.user_id == user_id, AccountUploadReservation.session_id.is_(None),
                or_(AccountUploadReservation.finished_at < now - STREAM_WINDOW,
                    AccountUploadReservation.finished_at.is_(None) & (AccountUploadReservation.started_at < now - RECEIVING_LEASE)),
            ).delete(synchronize_session=False)
            reservation = AccountUploadReservation(id=uuid4().hex, user_id=user_id, kind=kind, size_bytes=size, started_at=now)
            db.session.add(reservation)
            reservation_id = reservation.id
            db.session.commit()
    except OperationConflict as exc:
        raise UploadQuotaError("UPLOAD_CONCURRENCY_QUOTA", "Another upload for your account is being admitted. Try again shortly.", 429, {}) from exc

    g.account_upload_reservation_id = reservation_id
    try:
        yield reservation_id
    except Exception:
        db.session.rollback()
        raise
    finally:
        g.pop("account_upload_reservation_id", None)
        reservation = db.session.get(AccountUploadReservation, reservation_id)
        if reservation and reservation.finished_at is None:
            if reservation.session_id is None:
                db.session.delete(reservation)
            else:
                reservation.finished_at = datetime.utcnow()
            db.session.commit()


def attach_upload_to_session(session):
    reservation_id = getattr(g, "account_upload_reservation_id", None)
    if reservation_id:
        db.session.flush()
        reservation = db.session.get(AccountUploadReservation, reservation_id)
        if reservation:
            if reservation.user_id != session.user_id:
                raise ValueError("Upload reservation belongs to another account")
            reservation.session_id = session.id


def reserve_cloud_batch_expansion(user_id, size):
    """Increase this request's source reservation before any ZIP members are written."""
    try:
        with registry_lock(f"account-upload-quota:{user_id}"):
            now = datetime.utcnow()
            reservation_id = getattr(g, "account_upload_reservation_id", None)
            reservation = db.session.get(AccountUploadReservation, reservation_id) if reservation_id else None
            if (not reservation or reservation.user_id != user_id or reservation.kind != "session"
                    or reservation.finished_at or reservation.started_at < now - RECEIVING_LEASE):
                raise UploadQuotaError("UPLOAD_RESERVATION_EXPIRED", "Start a new upload to reserve storage for this archive.", 409, {})
            increase = size - reservation.size_bytes
            if increase <= 0:
                return
            usage = upload_usage(db.session.get(User, user_id), now)
            if usage["limit_bytes"] is not None and usage["used_bytes"] + increase > usage["limit_bytes"]:
                raise UploadQuotaError("UPLOAD_STORAGE_QUOTA", "This archive exceeds your account's source storage limit when extracted.", 413, usage)
            reservation.size_bytes = size
            db.session.commit()
    except OperationConflict as exc:
        raise UploadQuotaError("UPLOAD_CONCURRENCY_QUOTA", "Another upload for your account is being admitted. Try again shortly.", 429, {}) from exc


def finish_stream_upload(reservation_id):
    reservation = db.session.get(AccountUploadReservation, reservation_id)
    reservation.finished_at = datetime.utcnow()
    db.session.commit()
