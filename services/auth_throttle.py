"""Bound public authentication across API workers without storing addresses."""

from contextlib import contextmanager
from hashlib import sha256
import hmac
from ipaddress import ip_address
from math import ceil
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time

from flask import current_app, request

from exceptions import AppException


class AuthThrottleUnavailable(AppException):
    status_code = 503
    error_code = "AUTH_THROTTLE_UNAVAILABLE"
    user_message = "Sign-in protection is temporarily unavailable. Try again shortly."


def _client_address():
    remote = request.remote_addr or "unknown"
    hops = _setting("AUTH_TRUSTED_PROXY_HOPS", 0, minimum=0)
    if hops:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")
        if len(forwarded) >= hops:
            remote = forwarded[-hops].strip()
    try:
        return str(ip_address(remote))
    except ValueError:
        return "unknown"


def _setting(name, default, *, minimum=1):
    try:
        return max(minimum, int(current_app.config.get(name, os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def _policy(action):
    ip_multiplier = _setting("AUTH_RATE_LIMIT_IP_MULTIPLIER", 4)
    if action == "demo_login":
        return 300, 30, 20, 20
    if action == "mfa_recovery":
        maximum = _setting("MFA_RECOVERY_RATE_LIMIT_ATTEMPTS", 5)
        return (_setting("MFA_RECOVERY_RATE_LIMIT_WINDOW_SECONDS", 300),
                _setting("MFA_RECOVERY_RATE_LIMIT_LOCKOUT_SECONDS", 900), maximum, maximum * ip_multiplier)
    window = _setting("AUTH_RATE_LIMIT_WINDOW_SECONDS", 300)
    lockout = _setting("AUTH_RATE_LIMIT_LOCKOUT_SECONDS", 900)
    if action == "verify_email":
        maximum = _setting("VERIFY_EMAIL_RATE_LIMIT_ATTEMPTS", 100)
        return window, lockout, maximum, maximum
    maximum = (_setting("REGISTER_RATE_LIMIT_ATTEMPTS", 10) if action == "register"
               else _setting("LOGIN_RATE_LIMIT_ATTEMPTS", 5))
    return window, lockout, maximum, maximum * ip_multiplier


def _digest(action, scope, value):
    secret = current_app.secret_key or current_app.config["JWT_SECRET_KEY"]
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    return hmac.new(key, f"{action}\0{scope}\0{value}".encode("utf-8"), sha256).hexdigest()


def _quota_keys(action, identifier):
    window, lockout, account_limit, ip_limit = _policy(action)
    keys = {_digest(action, "ip", _client_address()): ip_limit}
    if identifier and action != "demo_login":
        keys[_digest(action, "account", identifier.strip().casefold())] = account_limit
    return window, lockout, keys


def _database_path():
    configured = current_app.config.get("AUTH_THROTTLE_DB_PATH") or os.environ.get("AUTH_THROTTLE_DB_PATH")
    if configured:
        return Path(configured)
    if current_app.testing:
        directory = current_app.extensions.get("auth_throttle_tmpdir")
        if directory is None:
            directory = TemporaryDirectory(prefix="webhdp-auth-throttle-")
            current_app.extensions["auth_throttle_tmpdir"] = directory
        return Path(directory.name) / "auth-throttle.sqlite3"
    return Path(current_app.instance_path) / "auth-throttle.sqlite3"


@contextmanager
def _connection():
    connection = None
    try:
        path = _database_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        connection = sqlite3.connect(path, timeout=5)
        connection.execute("""CREATE TABLE IF NOT EXISTS auth_throttle (
            key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, locked INTEGER NOT NULL, expires_at REAL NOT NULL
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS auth_throttle_expiry ON auth_throttle(expires_at)")
        with connection:
            yield connection
    except (OSError, sqlite3.Error) as exc:
        current_app.logger.error("Could not access shared authentication throttle", exc_info=True)
        raise AuthThrottleUnavailable() from exc
    finally:
        if connection is not None:
            connection.close()


def _locked_seconds(rows, now):
    locked_until = max((expires for _, locked, expires in rows.values() if locked), default=now)
    return max(0, ceil(locked_until - now))


def _read(connection, keys, now):
    return {
        key: row
        for key in keys
        if (row := connection.execute(
            "SELECT attempts, locked, expires_at FROM auth_throttle WHERE key=? AND expires_at>?", (key, now),
        ).fetchone()) is not None
    }


def check_auth_limit(action, identifier=None):
    _, _, keys = _quota_keys(action, identifier)
    now = time.time()
    with _connection() as connection:
        return _locked_seconds(_read(connection, keys, now), now)


def record_auth_attempt(action, identifier=None, *, consume=False):
    """Atomically reserve a public action or record a failed login attempt."""
    window, lockout, keys = _quota_keys(action, identifier)
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        now = time.time()
        connection.execute("DELETE FROM auth_throttle WHERE expires_at<=?", (now,))
        rows = _read(connection, keys, now)
        retry_after = _locked_seconds(rows, now)
        if consume and retry_after:
            return retry_after
        for key, limit in keys.items():
            attempts, locked, expires_at = rows.get(key, (0, False, now + window))
            if locked:
                continue
            attempts += 1
            locked = attempts >= limit
            if locked:
                expires_at = now + lockout
            connection.execute(
                """INSERT INTO auth_throttle VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET attempts=excluded.attempts,
                locked=excluded.locked, expires_at=excluded.expires_at""",
                (key, attempts, locked, expires_at),
            )
        return 0


def clear_account_auth_limit(action, identifier):
    if action == "demo_login":
        key = _digest(action, "ip", _client_address())
    elif identifier:
        key = _digest(action, "account", identifier.strip().casefold())
    else:
        return
    with _connection() as connection:
        connection.execute("DELETE FROM auth_throttle WHERE key=?", (key,))
