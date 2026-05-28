#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


PRIMARY_CSV_COLUMNS = [
    "original_filename",
    "zenodo_doi",
    "glb_direct_link",
    "record_link",
    "zenodo_record_id",
    "record_status",
    "session_id",
    "local_record_id",
]


@dataclass(frozen=True)
class HdpcSource:
    session_id: int
    hdpc_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Hunt dataset records from local session .hdpc files."
    )
    parser.add_argument(
        "--hdpc",
        action="append",
        nargs=2,
        metavar=("SESSION_ID", "PATH"),
        required=True,
        help="Session id and local path to a session .hdpc file.",
    )
    parser.add_argument(
        "--primary-json",
        default="hunt_dataset.json",
        help="Primary JSON output path.",
    )
    parser.add_argument(
        "--primary-csv",
        default="hunt_dataset.csv",
        help="Primary CSV output path.",
    )
    parser.add_argument(
        "--secondary-json",
        default="hunt_dataset_superseded_drafts.json",
        help="Secondary JSON output path.",
    )
    parser.add_argument(
        "--secondary-csv",
        default="hunt_dataset_superseded_drafts.csv",
        help="Secondary CSV output path.",
    )
    parser.add_argument(
        "--hunt-token",
        default="Hunt_Dataset",
        help="Substring used to detect Hunt source paths.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout for Zenodo public API fallbacks.",
    )
    return parser.parse_args()


def parse_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def is_hunt_path(path: str | None, token: str) -> bool:
    return token.lower() in str(path or "").lower()


def get_nested(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def extract_doi(row: sqlite3.Row, metadata: dict[str, Any]) -> str:
    candidates = [
        row["zenodo_doi"],
        metadata.get("doi"),
        get_nested(metadata, "metadata", "doi"),
        get_nested(metadata, "metadata", "prereserve_doi", "doi"),
        get_nested(metadata, "prereserve_doi", "doi"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def record_base(is_sandbox: bool) -> str:
    return "https://sandbox.zenodo.org" if is_sandbox else "https://zenodo.org"


def extract_record_link(
    record_status: str,
    zenodo_record_id: Any,
    metadata: dict[str, Any],
    is_sandbox: bool,
) -> str:
    links = metadata.get("links") if isinstance(metadata.get("links"), dict) else {}
    for key in ("html", "latest_draft_html", "latest_draft", "self"):
        value = str(links.get(key) or "").strip()
        if value:
            if key == "html" and record_status == "published":
                return value.replace("/deposit/", "/records/")
            return value
    record_id = str(zenodo_record_id or metadata.get("id") or "").strip()
    if not record_id:
        return ""
    if record_status == "published":
        return f"{record_base(is_sandbox)}/records/{record_id}"
    return f"{record_base(is_sandbox)}/deposit/{record_id}"


def extract_file_objects(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    files = metadata.get("files")
    if not isinstance(files, list):
        return []
    return [item for item in files if isinstance(item, dict)]


def choose_glb_file(
    source_file_name: str | None,
    metadata_files: list[dict[str, Any]],
) -> dict[str, Any] | None:
    glb_files = []
    expected = str(source_file_name or "").strip().lower()
    for item in metadata_files:
        filename = str(item.get("filename") or item.get("key") or item.get("name") or "").strip()
        if not filename.lower().endswith(".glb"):
            continue
        glb_files.append(item)
        if expected and filename.lower() == expected:
            return item
    return glb_files[0] if glb_files else None


class ZenodoPublicCache:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.cache: dict[tuple[bool, str], dict[str, Any] | None] = {}

    def fetch(self, is_sandbox: bool, record_id: Any) -> dict[str, Any] | None:
        record_key = str(record_id or "").strip()
        if not record_key:
            return None
        cache_key = (is_sandbox, record_key)
        if cache_key in self.cache:
            return self.cache[cache_key]

        url = f"{record_base(is_sandbox)}/api/records/{record_key}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            self.cache[cache_key] = payload if isinstance(payload, dict) else None
        except requests.RequestException:
            self.cache[cache_key] = None
        return self.cache[cache_key]


def resolve_glb_direct_link(
    artifact: dict[str, Any],
    public_cache: ZenodoPublicCache,
) -> str:
    metadata = artifact["record_metadata"]
    source_file_name = artifact["source_file_name"]
    zenodo_record_id = artifact["zenodo_record_id"]
    is_sandbox = bool(artifact["is_sandbox"])
    record_status = str(artifact["record_status"] or "").lower()

    metadata_files = extract_file_objects(metadata)
    glb_file = choose_glb_file(source_file_name, metadata_files)
    if glb_file:
        filename = str(
            glb_file.get("filename") or glb_file.get("key") or glb_file.get("name") or source_file_name or ""
        ).strip()
        if record_status == "published" and zenodo_record_id and filename:
            return f"{record_base(is_sandbox)}/api/records/{zenodo_record_id}/files/{filename}/content"
        links = glb_file.get("links") if isinstance(glb_file.get("links"), dict) else {}
        for key in ("content", "download", "self"):
            url = str(links.get(key) or "").strip()
            if not url:
                continue
            if key == "self" and record_status == "published" and zenodo_record_id and filename:
                return f"{record_base(is_sandbox)}/api/records/{zenodo_record_id}/files/{filename}/content"
            if key == "self" and not url.endswith("/content"):
                return url.rstrip("/") + "/content"
            return url

    public_payload = public_cache.fetch(is_sandbox=is_sandbox, record_id=zenodo_record_id)
    if isinstance(public_payload, dict):
        public_glb = choose_glb_file(source_file_name, extract_file_objects(public_payload))
        if public_glb:
            filename = str(
                public_glb.get("filename") or public_glb.get("key") or public_glb.get("name") or source_file_name or ""
            ).strip()
            if zenodo_record_id and filename:
                return f"{record_base(is_sandbox)}/api/records/{zenodo_record_id}/files/{filename}/content"

    if record_status == "published" and zenodo_record_id and source_file_name:
        return f"{record_base(is_sandbox)}/api/records/{zenodo_record_id}/files/{source_file_name}/content"
    return ""


def load_artifacts(source: HdpcSource, hunt_token: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(source.hdpc_path)
    conn.row_factory = sqlite3.Row
    try:
        source_files = {
            row["file_id"]: dict(row)
            for row in conn.execute("SELECT * FROM source_files")
        }

        files_by_record: dict[int, list[dict[str, Any]]] = defaultdict(list)
        joined_rows = conn.execute(
            """
            SELECT
                rfm.record_id,
                rfm.file_id,
                rfm.file_purpose,
                rfm.upload_status,
                rfm.upload_timestamp,
                rfm.file_path AS mapped_file_path,
                sf.filename,
                sf.absolute_path,
                sf.relative_path,
                sf.file_type,
                sf.size_bytes,
                sf.mime_type
            FROM record_files_map rfm
            LEFT JOIN source_files sf ON sf.file_id = rfm.file_id
            ORDER BY rfm.record_id, rfm.map_id
            """
        ).fetchall()
        for row in joined_rows:
            files_by_record[int(row["record_id"])].append(dict(row))

        artifacts: list[dict[str, Any]] = []
        for row in conn.execute("SELECT * FROM zenodo_records ORDER BY record_id ASC"):
            source_file = source_files.get(row["source_file_id"]) or {}
            source_path = str(source_file.get("absolute_path") or "").strip()
            if not is_hunt_path(source_path, hunt_token):
                continue

            metadata = parse_json(row["record_metadata_json"])
            artifact = {
                "session_id": source.session_id,
                "local_record_id": int(row["record_id"]),
                "source_file_id": row["source_file_id"],
                "source_file_name": source_file.get("filename"),
                "source_file_path": source_path,
                "record_status": str(row["record_status"] or "").strip().lower(),
                "zenodo_record_id": row["zenodo_record_id"] or metadata.get("id"),
                "concept_rec_id": str(row["concept_rec_id"] or metadata.get("conceptrecid") or "").strip(),
                "version": row["version"],
                "zenodo_doi": extract_doi(row, metadata),
                "record_link": extract_record_link(
                    record_status=str(row["record_status"] or "").strip().lower(),
                    zenodo_record_id=row["zenodo_record_id"] or metadata.get("id"),
                    metadata=metadata,
                    is_sandbox=bool(row["is_sandbox"]),
                ),
                "is_sandbox": bool(row["is_sandbox"]),
                "created_at": row["created_timestamp"],
                "updated_at": row["last_updated_timestamp"],
                "last_api_error": row["last_api_error"],
                "record_title": row["record_title"],
                "record_metadata": metadata,
                "record_files": files_by_record.get(int(row["record_id"]), []),
            }
            artifacts.append(artifact)
        return artifacts
    finally:
        conn.close()


def choose_authoritative_session_id(artifacts: list[dict[str, Any]]) -> int:
    by_session: dict[int, tuple[int, float]] = {}
    for artifact in artifacts:
        session_id = int(artifact["session_id"])
        published_count, last_ts = by_session.get(session_id, (0, 0.0))
        if artifact["record_status"] == "published":
            published_count += 1
        last_ts = max(last_ts, parse_timestamp(artifact["created_at"]))
        by_session[session_id] = (published_count, last_ts)
    if not by_session:
        raise RuntimeError("No Hunt artifacts found in the provided .hdpc files.")
    return max(by_session, key=lambda sid: (by_session[sid][0], by_session[sid][1], sid))


def choose_latest_artifact(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        artifacts,
        key=lambda artifact: (
            int(artifact.get("version") or 0),
            parse_timestamp(artifact.get("updated_at")),
            int(artifact.get("local_record_id") or 0),
        ),
    )


def build_exports(
    artifacts: list[dict[str, Any]],
    public_cache: ZenodoPublicCache,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    authoritative_session_id = choose_authoritative_session_id(artifacts)
    authoritative_published = [
        artifact
        for artifact in artifacts
        if artifact["session_id"] == authoritative_session_id and artifact["record_status"] == "published"
    ]

    published_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in authoritative_published:
        path_key = str(artifact["source_file_path"]).strip().lower()
        if path_key:
            published_by_path[path_key].append(artifact)

    primary: list[dict[str, Any]] = []
    for path_key in sorted(published_by_path):
        chosen = choose_latest_artifact(published_by_path[path_key])
        chosen["authority_classification"] = "authoritative_published"
        chosen["glb_direct_link"] = resolve_glb_direct_link(chosen, public_cache)
        primary.append(chosen)

    primary_ids = {(artifact["session_id"], artifact["local_record_id"]) for artifact in primary}

    secondary: list[dict[str, Any]] = []
    for artifact in artifacts:
        if (artifact["session_id"], artifact["local_record_id"]) in primary_ids:
            continue
        artifact["authority_classification"] = "superseded_or_draft"
        artifact["glb_direct_link"] = resolve_glb_direct_link(artifact, public_cache)
        secondary.append(artifact)

    secondary.sort(
        key=lambda artifact: (
            int(artifact["session_id"]),
            parse_timestamp(artifact.get("updated_at")),
            int(artifact["local_record_id"]),
        ),
        reverse=True,
    )
    return authoritative_session_id, primary, secondary


def csv_row(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "original_filename": artifact.get("source_file_name") or "",
        "zenodo_doi": artifact.get("zenodo_doi") or "",
        "glb_direct_link": artifact.get("glb_direct_link") or "",
        "record_link": artifact.get("record_link") or "",
        "zenodo_record_id": artifact.get("zenodo_record_id") or "",
        "record_status": artifact.get("record_status") or "",
        "session_id": artifact.get("session_id") or "",
        "local_record_id": artifact.get("local_record_id") or "",
    }


def json_payload(
    records: list[dict[str, Any]],
    authoritative_session_id: int,
    hdpc_sources: list[HdpcSource],
) -> dict[str, Any]:
    serializable_records = []
    for artifact in records:
        serializable_records.append(
            {
                "authority_classification": artifact.get("authority_classification"),
                "session_id": artifact.get("session_id"),
                "local_record_id": artifact.get("local_record_id"),
                "source_file_id": artifact.get("source_file_id"),
                "source_file_name": artifact.get("source_file_name"),
                "source_file_path": artifact.get("source_file_path"),
                "record_status": artifact.get("record_status"),
                "record_title": artifact.get("record_title"),
                "zenodo_record_id": artifact.get("zenodo_record_id"),
                "concept_rec_id": artifact.get("concept_rec_id"),
                "version": artifact.get("version"),
                "zenodo_doi": artifact.get("zenodo_doi"),
                "record_link": artifact.get("record_link"),
                "glb_direct_link": artifact.get("glb_direct_link"),
                "is_sandbox": artifact.get("is_sandbox"),
                "created_at": artifact.get("created_at"),
                "updated_at": artifact.get("updated_at"),
                "last_api_error": artifact.get("last_api_error"),
                "record_file_count": len(artifact.get("record_files") or []),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authoritative_session_id": authoritative_session_id,
        "hdpc_sources": [
            {"session_id": source.session_id, "hdpc_path": str(source.hdpc_path)}
            for source in hdpc_sources
        ],
        "record_count": len(serializable_records),
        "records": serializable_records,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRIMARY_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    hdpc_sources = [
        HdpcSource(session_id=int(session_id), hdpc_path=Path(path).resolve())
        for session_id, path in args.hdpc
    ]
    for source in hdpc_sources:
        if not source.hdpc_path.exists():
            raise FileNotFoundError(f"Missing .hdpc file for session {source.session_id}: {source.hdpc_path}")

    artifacts: list[dict[str, Any]] = []
    for source in hdpc_sources:
        artifacts.extend(load_artifacts(source, hunt_token=args.hunt_token))
    if not artifacts:
        raise RuntimeError("No Hunt artifacts were found in the supplied .hdpc files.")

    public_cache = ZenodoPublicCache(timeout=args.timeout)
    authoritative_session_id, primary, secondary = build_exports(artifacts, public_cache)

    primary_json = Path(args.primary_json).resolve()
    primary_csv = Path(args.primary_csv).resolve()
    secondary_json = Path(args.secondary_json).resolve()
    secondary_csv = Path(args.secondary_csv).resolve()

    write_json(primary_json, json_payload(primary, authoritative_session_id, hdpc_sources))
    write_csv(primary_csv, [csv_row(record) for record in primary])
    write_json(secondary_json, json_payload(secondary, authoritative_session_id, hdpc_sources))
    write_csv(secondary_csv, [csv_row(record) for record in secondary])

    primary_paths = {str(record["source_file_path"]).strip().lower() for record in primary}
    if len(primary_paths) != len(primary):
        raise RuntimeError("Primary export still contains duplicate source_file_path values.")

    secondary_ids = {(record["session_id"], record["local_record_id"]) for record in secondary}
    overlap = [
        (record["session_id"], record["local_record_id"])
        for record in primary
        if (record["session_id"], record["local_record_id"]) in secondary_ids
    ]
    if overlap:
        raise RuntimeError(f"Primary and secondary exports overlap: {overlap[:5]}")

    summary = {
        "authoritative_session_id": authoritative_session_id,
        "primary_record_count": len(primary),
        "primary_unique_source_paths": len(primary_paths),
        "secondary_record_count": len(secondary),
        "primary_csv": str(primary_csv),
        "primary_json": str(primary_json),
        "secondary_csv": str(secondary_csv),
        "secondary_json": str(secondary_json),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
