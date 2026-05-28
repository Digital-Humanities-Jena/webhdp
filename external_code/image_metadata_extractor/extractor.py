#!/usr/bin/env python3
"""Extract stable file and image metadata for WebHDP component testing."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import struct
import sys
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_PATH = Path("output") / "image_metadata.json"
JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _boolish(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 10 or data[:6] not in {b"GIF87a", b"GIF89a"}:
        return None
    return struct.unpack("<HH", data[6:10])


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    offset = 2
    while offset + 3 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return None
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            return None
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            return None
        if marker in JPEG_SOF_MARKERS and segment_length >= 7:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += segment_length
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        start_code = data.find(b"\x9d\x01\x2a", 20)
        if start_code != -1 and start_code + 7 < len(data):
            width_raw, height_raw = struct.unpack("<HH", data[start_code + 3 : start_code + 7])
            return width_raw & 0x3FFF, height_raw & 0x3FFF
    return None


def _detect_image(data: bytes) -> dict[str, Any]:
    probes = [
        ("png", "image/png", _png_dimensions),
        ("jpeg", "image/jpeg", _jpeg_dimensions),
        ("gif", "image/gif", _gif_dimensions),
        ("webp", "image/webp", _webp_dimensions),
    ]
    for image_format, mime_type, detector in probes:
        dimensions = detector(data)
        if dimensions is not None:
            width, height = dimensions
            return {
                "format": image_format,
                "mime_type": mime_type,
                "width": width,
                "height": height,
                "megapixels": round((width * height) / 1_000_000, 4),
            }
    return {
        "format": "unknown",
        "mime_type": None,
        "width": None,
        "height": None,
        "megapixels": None,
    }


def extract_metadata(input_file: str, *, include_hash: bool = True, probe_bytes: int = 65536) -> dict[str, Any]:
    path = Path(input_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input image does not exist: {path}")

    probe_limit = max(32, int(probe_bytes or 65536))
    with path.open("rb") as handle:
        header = handle.read(probe_limit)

    stat = path.stat()
    detected = _detect_image(header)
    guessed_mime, _ = mimetypes.guess_type(path.name)
    warnings: list[str] = []
    if detected["format"] == "unknown":
        warnings.append("Image format or dimensions could not be detected from the probed bytes.")

    report: dict[str, Any] = {
        "success": detected["format"] != "unknown",
        "input": {
            "path": str(path),
            "filename": path.name,
            "extension": path.suffix.lower(),
            "size_bytes": stat.st_size,
            "guessed_mime_type": guessed_mime,
        },
        "image": detected,
        "warnings": warnings,
    }
    if include_hash:
        report["input"]["sha256"] = _sha256(path)
    return report


def _write_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output_path.resolve()


def _run_component_request() -> int | None:
    request_path = os.environ.get("WEBHDP_COMPONENT_REQUEST")
    response_path = os.environ.get("WEBHDP_COMPONENT_RESPONSE")
    if not request_path:
        return None
    if not response_path:
        print("WEBHDP_COMPONENT_RESPONSE is required when WEBHDP_COMPONENT_REQUEST is set", file=sys.stderr)
        return 2

    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        inputs = request.get("inputs") or {}
        parameters = request.get("parameters") or {}
        input_file = inputs.get("input_file")
        output_path = Path(parameters.get("output_path") or DEFAULT_OUTPUT_PATH)
        report = extract_metadata(
            str(input_file),
            include_hash=_boolish(parameters.get("include_hash"), default=True),
            probe_bytes=int(parameters.get("probe_bytes") or 65536),
        )
        resolved_output = _write_report(report, output_path)
        response = {
            "success": bool(report.get("success")),
            "status": "completed" if report.get("success") else "failed",
            "outputs": {"metadata_report": str(resolved_output)},
            "artifacts": [
                {
                    "artifact_kind": "file",
                    "name": "metadata_report",
                    "path": str(resolved_output),
                    "metadata": {"content_type": "application/json"},
                }
            ],
            "logs": {"stdout": "", "stderr": ""},
        }
        if not report.get("success"):
            response["error"] = "; ".join(report.get("warnings") or ["Image metadata extraction failed"])
    except Exception as exc:
        response = {
            "success": False,
            "status": "failed",
            "error": str(exc),
            "outputs": {},
            "artifacts": [],
            "logs": {"stdout": "", "stderr": str(exc)},
        }

    Path(response_path).write_text(json.dumps(response, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if response.get("success") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract image file metadata.")
    parser.add_argument("--input-file", required=True, help="Image file to inspect.")
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH), help="JSON report output path.")
    parser.add_argument(
        "--include-hash",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Compute SHA-256.",
    )
    parser.add_argument("--probe-bytes", type=int, default=65536, help="Leading bytes to inspect.")
    return parser


def main(argv: list[str] | None = None) -> int:
    component_status = _run_component_request()
    if component_status is not None:
        return component_status

    args = build_parser().parse_args(argv)
    report = extract_metadata(args.input_file, include_hash=bool(args.include_hash), probe_bytes=args.probe_bytes)
    output_path = _write_report(report, Path(args.output_path))
    print(json.dumps({"success": report["success"], "metadata_report": str(output_path)}, sort_keys=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
