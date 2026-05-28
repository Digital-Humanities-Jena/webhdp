"""Persistent authentication and user policy storage."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class AuthenticatedUser:
    """Authenticated principal resolved from token or API key."""

    user_id: int
    username: str
    is_admin: bool
    invited: bool
    is_active: bool
    allowed_partitions: list[str]
    allowed_gpu_types: list[str]
    max_duration_minutes: int
    max_gpu_count: int
    last_login: str | None = None


class AuthStore:
    """SQLite-backed store for users and allocation policies."""

    _iterations = 210_000

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """Create schema if needed."""
        db_file = Path(self._db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    invited INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    allowed_partitions TEXT NOT NULL DEFAULT '[]',
                    allowed_gpu_types TEXT NOT NULL DEFAULT '[]',
                    max_duration_minutes INTEGER NOT NULL DEFAULT 30,
                    max_gpu_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login TEXT
                )
                """
            )
            conn.commit()

    def ensure_admin_user(self, username: str, password: str) -> None:
        """Upsert the admin account."""
        normalized = username.strip().lower()
        if not normalized:
            raise ValueError("admin username cannot be empty")
        if not password:
            raise ValueError("admin password cannot be empty")

        pw_hash, pw_salt = self._hash_password(password)
        now = self._now_iso()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?",
                (normalized,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, password_salt = ?, is_admin = 1,
                        invited = 1, is_active = 1, updated_at = ?
                    WHERE username = ?
                    """,
                    (pw_hash, pw_salt, now, normalized),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users (
                        username, password_hash, password_salt, is_admin, invited,
                        is_active, allowed_partitions, allowed_gpu_types,
                        max_duration_minutes, max_gpu_count, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, 1, 1, '[]', '[]', 10080, 16, ?, ?)
                    """,
                    (normalized, pw_hash, pw_salt, now, now),
                )
            conn.commit()

    def create_invited_user(
        self,
        username: str,
        password: str,
        allowed_partitions: list[str],
        allowed_gpu_types: list[str],
        max_duration_minutes: int,
        max_gpu_count: int,
        is_active: bool = True,
    ) -> AuthenticatedUser:
        """Create one invited user with policy constraints."""
        normalized = username.strip().lower()
        if not normalized:
            raise ValueError("username cannot be empty")
        if not password:
            raise ValueError("password cannot be empty")
        if max_duration_minutes < 1:
            raise ValueError("max_duration_minutes must be >= 1")
        if max_gpu_count < 1:
            raise ValueError("max_gpu_count must be >= 1")

        pw_hash, pw_salt = self._hash_password(password)
        now = self._now_iso()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    username, password_hash, password_salt, is_admin, invited,
                    is_active, allowed_partitions, allowed_gpu_types,
                    max_duration_minutes, max_gpu_count, created_at, updated_at
                ) VALUES (?, ?, ?, 0, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized,
                    pw_hash,
                    pw_salt,
                    int(is_active),
                    json.dumps(sorted(set(allowed_partitions))),
                    json.dumps(sorted(set(allowed_gpu_types))),
                    max_duration_minutes,
                    max_gpu_count,
                    now,
                    now,
                ),
            )
            conn.commit()

        created = self.get_user_by_username(normalized)
        if created is None:
            raise RuntimeError("created user could not be loaded")
        return created

    def update_user_policy(
        self,
        username: str,
        allowed_partitions: list[str] | None = None,
        allowed_gpu_types: list[str] | None = None,
        max_duration_minutes: int | None = None,
        max_gpu_count: int | None = None,
        is_active: bool | None = None,
    ) -> AuthenticatedUser | None:
        """Patch policy fields for one user."""
        normalized = username.strip().lower()
        existing = self.get_user_by_username(normalized)
        if existing is None:
            return None
        if existing.is_admin:
            raise ValueError("admin policy cannot be changed")

        next_allowed_partitions = existing.allowed_partitions if allowed_partitions is None else sorted(set(allowed_partitions))
        next_allowed_gpu_types = existing.allowed_gpu_types if allowed_gpu_types is None else sorted(set(allowed_gpu_types))
        next_max_duration = existing.max_duration_minutes if max_duration_minutes is None else max_duration_minutes
        next_max_gpu_count = existing.max_gpu_count if max_gpu_count is None else max_gpu_count
        next_is_active = existing.is_active if is_active is None else is_active

        if next_max_duration < 1:
            raise ValueError("max_duration_minutes must be >= 1")
        if next_max_gpu_count < 1:
            raise ValueError("max_gpu_count must be >= 1")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET allowed_partitions = ?, allowed_gpu_types = ?,
                    max_duration_minutes = ?, max_gpu_count = ?,
                    is_active = ?, updated_at = ?
                WHERE username = ?
                """,
                (
                    json.dumps(next_allowed_partitions),
                    json.dumps(next_allowed_gpu_types),
                    next_max_duration,
                    next_max_gpu_count,
                    int(next_is_active),
                    self._now_iso(),
                    normalized,
                ),
            )
            conn.commit()

        return self.get_user_by_username(normalized)

    def set_user_password(self, username: str, password: str) -> AuthenticatedUser | None:
        """Reset password for one user."""
        normalized = username.strip().lower()
        if not password:
            raise ValueError("password cannot be empty")

        user = self.get_user_by_username(normalized)
        if user is None:
            return None

        pw_hash, pw_salt = self._hash_password(password)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET password_hash = ?, password_salt = ?, updated_at = ?
                WHERE username = ?
                """,
                (pw_hash, pw_salt, self._now_iso(), normalized),
            )
            conn.commit()

        return self.get_user_by_username(normalized)

    def authenticate(self, username: str, password: str) -> AuthenticatedUser | None:
        """Verify username/password and return active invited user."""
        normalized = username.strip().lower()
        row = self._get_row_by_username(normalized)
        if row is None:
            return None

        if not self._verify_password(password, row["password_salt"], row["password_hash"]):
            return None

        user = self._row_to_user(row)
        if not user.is_active or not user.invited:
            return None

        self.record_login(user.user_id)
        return self.get_user_by_id(user.user_id)

    def record_login(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_login = ?, updated_at = ? WHERE id = ?",
                (self._now_iso(), self._now_iso(), user_id),
            )
            conn.commit()

    def get_user_by_id(self, user_id: int) -> AuthenticatedUser | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> AuthenticatedUser | None:
        row = self._get_row_by_username(username.strip().lower())
        if row is None:
            return None
        return self._row_to_user(row)

    def list_users(self) -> list[AuthenticatedUser]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [self._row_to_user(row) for row in rows]

    def _get_row_by_username(self, username: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return row

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def _hash_password(cls, password: str) -> tuple[str, str]:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, cls._iterations)
        return cls._b64(digest), cls._b64(salt)

    @classmethod
    def _verify_password(cls, password: str, salt_b64: str, hash_b64: str) -> bool:
        try:
            salt = base64.b64decode(salt_b64.encode("ascii"), validate=True)
            expected = base64.b64decode(hash_b64.encode("ascii"), validate=True)
        except Exception:
            return False

        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, cls._iterations)
        return hmac.compare_digest(digest, expected)

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> AuthenticatedUser:
        partitions = json.loads(row["allowed_partitions"] or "[]")
        gpu_types = json.loads(row["allowed_gpu_types"] or "[]")
        return AuthenticatedUser(
            user_id=int(row["id"]),
            username=str(row["username"]),
            is_admin=bool(row["is_admin"]),
            invited=bool(row["invited"]),
            is_active=bool(row["is_active"]),
            allowed_partitions=list(partitions),
            allowed_gpu_types=list(gpu_types),
            max_duration_minutes=int(row["max_duration_minutes"]),
            max_gpu_count=int(row["max_gpu_count"]),
            last_login=row["last_login"],
        )
