#!/usr/bin/env python3
"""Run a durable WebHDP-Link worker against the configured WebHDP database.

Usage: .venv/bin/python scripts/webhdp_link_worker.py [--once] [--poll-seconds 2]
Use the same environment and storage volume as the web application. Multiple
worker processes obey global and per-application concurrency quotas.
"""
import argparse
from pathlib import Path
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=float, default=2)
    args = parser.parse_args()
    from app import app
    from services.webhdp_link_worker import process_next
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        with app.app_context():
            worked = process_next()
        if args.once:
            break
        if not worked:
            time.sleep(max(0.2, min(args.poll_seconds, 30)))


if __name__ == '__main__':
    main()
