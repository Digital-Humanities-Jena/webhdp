"""Operate the guided model workflow and its short-lived demonstration account."""

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import threading
import time

import requests

from app import app
from database.database import db
from database.models import SystemConfig, User, UserRole
from external_code.webhdp_link_zenodo.runner import API, SANDBOX, SandboxClient
from services import model_publication_queue as queue
from services.model_publication_accounts import DEMO_CAPABILITY, DEMO_SECONDS, demo_config_key, demo_expiry, is_demo, sandbox_token


def prepare_demo(output):
    email = f"model-demo-{secrets.token_hex(4)}@webhdp.invalid"
    password = secrets.token_urlsafe(24)
    user = User(email=email, role=UserRole.USER, display_name="WebHDP live demonstration", is_verified=True)
    user.set_password(password)
    user.set_capabilities([DEMO_CAPABILITY])
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"email": email, "password": password, "sign_in_seconds": DEMO_SECONDS}, stream)
            stream.write("\n")
        db.session.add(user)
        db.session.commit()
    except Exception:
        Path(output).unlink(missing_ok=True)
        raise
    print(json.dumps({"email": email, "sign_in_seconds": DEMO_SECONDS}))


def set_window(email, *, close=False):
    user = User.query.filter_by(email=email, role=UserRole.USER).one_or_none()
    if not user or not is_demo(user):
        raise SystemExit("No demonstration account has that address.")
    now = int(time.time())
    current_expiry = demo_expiry(user.id)
    # Prepared accounts are single event accounts.
    if not close and current_expiry:
        raise SystemExit("This account already had a demonstration window. Prepare a new account for another event.")
    if not close and not (queue.enabled() and queue.worker_ready(queue.root()) and sandbox_token(user.id, True)):
        raise SystemExit("Start the publication worker and configure the Sandbox credential before opening the demonstration.")
    key = demo_config_key(user.id)
    setting = db.session.get(SystemConfig, key) or SystemConfig(key=key)
    setting.value = str(now if close else now + DEMO_SECONDS)
    user.token_version += 1
    db.session.add(setting)
    db.session.commit()
    print(json.dumps({"email": email, "closes_at_epoch": int(setting.value)}))


def publish_sample(job_id):
    """Permit a human operator to publish one verified public fixture in Sandbox."""
    from routes.model_publication_routes import sample_catalog

    base = queue.root()
    with queue.connection(base) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=? AND status='completed' AND demo_window>0", (job_id,)).fetchone()
    if not job:
        raise SystemExit("Choose a completed demonstration job.")
    parameters = json.loads(job["input_json"])
    if parameters["metadata_source"] != "archive" or parameters["sample_id"] not in {entry["id"] for entry in sample_catalog()}:
        raise SystemExit("Publication is limited to a sample with its original, reviewed metadata.")
    result = json.loads(job["result_json"])
    identity = result["draft"]["id"]
    client = SandboxClient(sandbox_token(job["user_id"], True))
    client.draft(identity)
    receipt = base / job_id / "publication-attempt"
    # If the HTTP outcome is uncertain, check the record before taking further action.
    try:
        with receipt.open("x") as stream:
            stream.write(str(identity))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise SystemExit(f"A publication attempt already exists. Check {SANDBOX}/records/{identity}.") from None
    try:
        response = client._session.post(f"{API}/{identity}/actions/publish", timeout=(10, 45), allow_redirects=False,
                                        headers=client._headers)
    except requests.RequestException:
        raise SystemExit(f"Publication could not be confirmed. Check {SANDBOX}/records/{identity}.") from None
    finally:
        client._session.close()
    if response.status_code != 202 or response.json().get("id") != identity:
        raise SystemExit(f"Publication returned HTTP {response.status_code}. Check {SANDBOX}/records/{identity}.")
    print(json.dumps({"id": identity, "record_url": f"{SANDBOX}/records/{identity}"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("worker")
    commands.add_parser("prepare-demo").add_argument("--output", required=True, type=Path)
    for name in ("open-demo", "close-demo"):
        commands.add_parser(name).add_argument("email")
    publish = commands.add_parser("publish-sample")
    publish.add_argument("job_id")
    publish.add_argument("--confirm-sandbox", required=True, choices=("publish",))
    options = parser.parse_args()
    if options.command == "worker":
        from services.model_publication_worker import run_worker
        stop = threading.Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        with app.app_context():
            base = queue.root()
        run_worker(app, base, stop=stop)
        return
    with app.app_context():
        if options.command == "prepare-demo":
            prepare_demo(options.output)
        elif options.command == "publish-sample":
            publish_sample(options.job_id)
        else:
            set_window(options.email, close=options.command == "close-demo")


if __name__ == "__main__":
    main()
