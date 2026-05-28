#!/usr/bin/env python3
"""Reject mutable production image tags before deployment."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


IMAGE_ENV_NAMES = (
    "WEBHDP_BACKEND_IMAGE",
    "WEBHDP_FRONTEND_IMAGE",
    "WEBHDP_FAST_RENDERER_IMAGE",
    "WEBHDP_ANY_TO_USDZ_IMAGE",
)
DEFAULT_IMAGE_NAMES = {
    "WEBHDP_BACKEND_IMAGE": "webhdp-backend",
    "WEBHDP_FRONTEND_IMAGE": "webhdp-frontend",
    "WEBHDP_FAST_RENDERER_IMAGE": "webhdp-fast-renderer",
    "WEBHDP_ANY_TO_USDZ_IMAGE": "webhdp-any-to-usdz",
}
MUTABLE_TAGS = {"", "latest", "local", "dev", "development", "main", "master"}
ROOT = Path(__file__).resolve().parents[1]


def _tag_for(image: str) -> str:
    if "@" in image:
        return "digest"
    if ":" not in image.rsplit("/", 1)[-1]:
        return ""
    return image.rsplit(":", 1)[1].strip().lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-mutable", action="store_true", default=os.environ.get("ALLOW_MUTABLE_IMAGE_TAGS", "").lower() in {"1", "true", "yes", "on"})
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / ".env.example", override=False)

    args = parse_args()
    errors = []
    default_tag = os.environ.get("WEBHDP_IMAGE_TAG", "").strip()
    for name in IMAGE_ENV_NAMES:
        image = os.environ.get(name, "").strip()
        if not image and default_tag:
            image = f"{DEFAULT_IMAGE_NAMES[name]}:{default_tag}"
        tag = _tag_for(image)
        if not image:
            errors.append(f"{name} is not set")
            continue
        if not args.allow_mutable and tag in MUTABLE_TAGS:
            errors.append(f"{name} uses mutable tag: {image}")
    if errors:
        print("Production images must use immutable version/SHA tags:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Release image tags look immutable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
