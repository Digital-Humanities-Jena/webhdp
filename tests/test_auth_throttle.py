from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from flask import Flask

from services.auth_throttle import check_auth_limit, record_auth_attempt


def make_app(path, *, trusted_hops=0):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="authentication-rate-limiter-test-key",
        AUTH_THROTTLE_DB_PATH=str(path),
        AUTH_TRUSTED_PROXY_HOPS=trusted_hops,
        REGISTER_RATE_LIMIT_ATTEMPTS=1,
        AUTH_RATE_LIMIT_IP_MULTIPLIER=1,
    )
    return app


def test_public_attempt_is_reserved_once_across_workers(tmp_path):
    path = tmp_path / "auth-throttle.db"
    workers = [make_app(path), make_app(path)]
    ready = Barrier(len(workers))

    def attempt(app):
        with app.test_request_context("/register", environ_base={"REMOTE_ADDR": "192.0.2.1"}):
            ready.wait(timeout=5)
            return record_auth_attempt("register", "person@example.test", consume=True)

    with ThreadPoolExecutor() as executor:
        admitted, rejected = sorted(executor.map(attempt, workers))

    assert admitted == 0
    assert 0 < rejected <= 900
    assert b"person@example.test" not in path.read_bytes()


def test_proxy_headers_are_ignored_without_trusted_proxy(tmp_path):
    app = make_app(tmp_path / "auth-throttle.db")

    def attempt(forwarded):
        with app.test_request_context(headers={"X-Forwarded-For": forwarded}, environ_base={"REMOTE_ADDR": "192.0.2.1"}):
            return record_auth_attempt("register", consume=True)

    assert attempt("192.0.2.3") == 0
    assert attempt("192.0.2.4") > 0


def test_trusted_proxy_boundary_uses_rightmost_verified_hop(tmp_path):
    app = make_app(tmp_path / "auth-throttle.db", trusted_hops=2)
    source = {"REMOTE_ADDR": "192.0.2.1"}
    with app.test_request_context(headers={"X-Forwarded-For": "198.51.100.1, 192.0.2.8, 192.0.2.5"}, environ_base=source):
        assert record_auth_attempt("register", consume=True) == 0
    with app.test_request_context(headers={"X-Forwarded-For": "198.51.100.9, 192.0.2.8, 192.0.2.5"}, environ_base=source):
        assert check_auth_limit("register") > 0
    with app.test_request_context(headers={"X-Forwarded-For": "198.51.100.1, 192.0.2.9, 192.0.2.5"}, environ_base=source):
        assert record_auth_attempt("register", consume=True) == 0
