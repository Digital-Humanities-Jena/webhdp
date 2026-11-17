"""Read-only integrity and HDPC export adapters (GPL-3.0-or-later).

These replace the published permission-changing validator and interpolated-SQL
export path with bounded processing suitable for a WebHDP container invocation.
"""
from __future__ import annotations

import csv
from datetime import date
import json
import math
import mimetypes
from pathlib import Path
import sqlite3
import struct
import warnings
import wave
import zipfile

try:
    from .common import checked_parameters, sha256, staged_file, write_json
except ImportError:
    from common import checked_parameters, sha256, staged_file, write_json


def read_only_database(path):
    connection = sqlite3.connect(Path(path).as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA query_only = ON")
    calls = [0]
    def budget():
        calls[0] += 1
        return calls[0] > 50000
    connection.set_progress_handler(budget, 1000)
    return connection


def _finite_json(source):
    def reject(value):
        raise ValueError(f"Non-finite JSON value: {value}")
    return json.loads(source, parse_constant=reject)


def validate_glb(path):
    size = path.stat().st_size
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError("Truncated GLB header")
        magic, version, length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or length != size:
            raise ValueError("Invalid GLB magic, version or declared length")
        offset, chunks, document = 12, [], None
        binary_length = 0
        while offset < size:
            raw = stream.read(8)
            if len(raw) != 8:
                raise ValueError("Truncated GLB chunk header")
            count, kind = struct.unpack("<I4s", raw)
            if count % 4 or offset + 8 + count > size:
                raise ValueError("Invalid GLB chunk length")
            if not chunks and kind != b"JSON":
                raise ValueError("GLB first chunk must contain JSON")
            if kind == b"JSON":
                if document is not None or count > 64 * 1024**2:
                    raise ValueError("Duplicate or oversized GLB JSON chunk")
                document = _finite_json(stream.read(count).decode("utf-8"))
            else:
                if kind == b"BIN\0":
                    if b"BIN\0" in chunks:
                        raise ValueError("Duplicate binary chunk")
                    binary_length = count
                stream.seek(count, 1)
            chunks.append(kind)
            offset += 8 + count
        if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
            raise ValueError("GLB requires a glTF 2.0 asset")
        for index, buffer in enumerate(document.get("buffers", [])):
            if "uri" not in buffer and (index != 0 or type(buffer.get("byteLength")) is not int
                                        or not 0 <= binary_length - buffer["byteLength"] <= 3):
                raise ValueError("GLB buffer byte length does not match its binary chunk")
    return {"format": "GLB", "version": version, "chunks": len(chunks),
            "validation_coverage": "container structure; not full glTF semantic validation"}


def validate_audio(path):
    """Parse supported audio headers/metadata without decoding or editing audio."""
    import mutagen
    from mutagen.aac import AAC
    from mutagen.aiff import AIFF
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggflac import OggFLAC
    from mutagen.oggopus import OggOpus
    from mutagen.oggspeex import OggSpeex
    from mutagen.oggvorbis import OggVorbis

    if path.stat().st_size > 512 * 1024**2:
        raise ValueError("Audio metadata validation input exceeds 512 MiB")
    audio = mutagen.File(path, options=[AAC, AIFF, FLAC, MP3, MP4, OggFLAC, OggOpus, OggSpeex, OggVorbis])
    if audio is None or getattr(audio, "info", None) is None:
        raise ValueError("No supported audio stream could be parsed")
    duration = getattr(audio.info, "length", None)
    if type(duration) not in {int, float} or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Audio stream duration must be finite and positive")
    details = {"format": type(audio).__name__, "duration_seconds": duration,
               "metadata_tags": len(audio.tags) if audio.tags is not None else 0,
               "parser": "mutagen", "parser_version": mutagen.version_string,
               "validation_coverage": "audio headers and metadata; compressed signal is not decoded"}
    for name in ("sample_rate", "channels", "bitrate", "bits_per_sample"):
        value = getattr(audio.info, name, None)
        if value is not None:
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError(f"Audio {name} must be finite")
            # Vorbis VBR streams can declare an unknown nominal bitrate as 0
            # or -1; it does not invalidate otherwise parsed stream metadata.
            if value < 0 and name != "bitrate":
                raise ValueError(f"Audio {name} must be nonnegative")
            details[name] = value if value > 0 else None
    return details


def integrity(inputs, raw, output):
    p = checked_parameters(raw, {"include_hash": (True, bool, None)})
    source = staged_file(inputs)
    suffix = source.suffix.lower()
    result = {"component": "validate_file_integrity", "upstream_record": "10.5281/zenodo.16993089",
              "input_name": source.name, "bytes": source.stat().st_size, "is_valid": True,
              "errors": [], "warnings": [], "validation_details": {}, "source_modified": False,
              "validation_dispatch": "filename extension", "mime_type_basis": "filename extension guess"}
    if p["include_hash"]:
        result["sha256"] = sha256(source)
    try:
        if source.stat().st_size == 0:
            raise ValueError("The file is empty")
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        result["mime_type"] = mime
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif", ".bmp"}:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = 100_000_000
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    result["validation_details"] = {"format": image.format, "width": image.width, "height": image.height,
                                                    "mode": image.mode, "frames": getattr(image, "n_frames", 1)}
                    image.verify()
                with Image.open(source) as image:
                    image.load()
        elif suffix in {".json", ".gltf"}:
            data = _finite_json(source.read_text(encoding="utf-8"))
            if suffix == ".gltf" and (not isinstance(data, dict) or data.get("asset", {}).get("version") != "2.0"):
                raise ValueError("glTF JSON requires asset.version 2.0")
            result["validation_details"] = {"structure": type(data).__name__, "validation_coverage": "JSON syntax"}
        elif suffix == ".glb":
            result["validation_details"] = validate_glb(source)
        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(source, strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF content cannot be verified without a password")
            result["validation_details"] = {"pages": len(reader.pages), "encrypted": False,
                                            "validation_coverage": "PDF parser and page tree; content streams are not rendered"}
        elif suffix in {".hdpc", ".sqlite", ".sqlite3", ".db"}:
            with read_only_database(source) as connection:
                rows = connection.execute("PRAGMA quick_check").fetchall()
                if rows != [("ok",)]:
                    raise ValueError("SQLite structural integrity check failed")
                result["validation_details"] = {"quick_check": "ok", "validation_coverage": "SQLite quick_check; not application-schema or foreign-key validation"}
        elif suffix == ".zip":
            with zipfile.ZipFile(source) as archive:
                if len(archive.infolist()) > 20000 or sum(item.file_size for item in archive.infolist()) > 4 * 1024**3:
                    raise ValueError("Archive exceeds validation limits")
                bad = archive.testzip()
                if bad:
                    raise ValueError(f"ZIP checksum mismatch: {bad}")
                result["validation_details"] = {"members": len(archive.infolist()), "crc_checked": True}
        elif suffix in {".wav", ".wave"}:
            with wave.open(str(source), "rb") as audio:
                expected = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
                read = 0
                while chunk := audio.readframes(65536):
                    read += len(chunk)
                if read != expected:
                    raise ValueError("WAV samples are truncated")
                result["validation_details"] = {"channels": audio.getnchannels(), "frames": audio.getnframes(),
                                                "sample_rate": audio.getframerate()}
        elif suffix in {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".aif", ".aiff", ".aifc"}:
            result["validation_details"] = validate_audio(source)
        else:
            with source.open("rb") as stream:
                stream.read(65536)
            result["validation_details"] = {"validation_coverage": "readability only"}
            result["warnings"].append("This format has no structural validator in this component; readability does not establish format correctness.")
    except Exception as exc:
        result["is_valid"] = False
        result["errors"].append(str(exc))
    report = write_json(output / "integrity-report.json", result)
    return {"validation_report": report}, {"is_valid": result["is_valid"], "errors": len(result["errors"]),
                                          "warnings": len(result["warnings"]), "file": source.name}


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def safe_csv_cell(value):
    if isinstance(value, bytes):
        return "hex:" + value.hex()
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_hdpc(inputs, raw, output):
    spec = {"export_mode": ("files_overview", str, {"files_overview", "zenodo_records", "metadata_export", "project_summary", "api_log", "custom"}),
            "table": ("source_files", str, None), "columns": ("", str, None),
            "filter_status": ("", str, None), "date_range_start": ("", str, None), "date_range_end": ("", str, None),
            "include_project_info": (True, bool, None), "max_rows": (10000, int, (1, 100000))}
    p = checked_parameters(raw, spec)
    for key in ("date_range_start", "date_range_end"):
        if p[key]:
            date.fromisoformat(p[key])
    if p["date_range_start"] and p["date_range_end"] and p["date_range_start"] > p["date_range_end"]:
        raise ValueError("Start date must not follow end date")
    source = staged_file(inputs)
    original_hash = sha256(source)
    mode = p["export_mode"]
    table = {"files_overview": "source_files", "zenodo_records": "zenodo_records", "metadata_export": "metadata_values",
             "project_summary": "project_info", "api_log": "api_log", "custom": p["table"]}[mode]
    connection = read_only_database(source)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not {"project_info", "source_files"} <= tables:
            raise ValueError("An HDPC database must contain project_info and source_files tables")
        if table not in tables:
            raise ValueError(f"The requested HDPC table is unavailable: {table}")
        available = [row[1] for row in connection.execute(f"PRAGMA table_info({quote(table)})")]
        columns = [name.strip() for name in p["columns"].split(",") if name.strip()] or available
        if not columns or len(set(columns)) != len(columns) or set(columns) - set(available):
            raise ValueError("Export columns must be distinct existing columns")
        fields = [f"t.{quote(name)}" for name in columns]
        joins, values, predicates = [], [], []
        if p["include_project_info"] and table != "project_info" and "project_id" in available:
            project_columns = [row[1] for row in connection.execute('PRAGMA table_info("project_info")')]
            if "project_id" in project_columns:
                joins.append('LEFT JOIN "project_info" p ON t."project_id" = p."project_id"')
                for name in ("project_name", "project_short_code"):
                    if name in project_columns and name not in columns:
                        fields.append(f"p.{quote(name)} AS {quote(name)}")
        if p["filter_status"]:
            status = next((name for name in ("record_status", "status") if name in available), None)
            if not status:
                raise ValueError("Selected export table has no status field")
            predicates.append(f"t.{quote(status)} = ?")
            values.append(p["filter_status"])
        if p["date_range_start"] or p["date_range_end"]:
            timestamp = next((name for name in ("added_timestamp", "created_timestamp", "extracted_timestamp", "timestamp", "creation_timestamp") if name in available), None)
            if not timestamp:
                raise ValueError("Selected export table has no supported timestamp field")
            for key, op in (("date_range_start", ">="), ("date_range_end", "<=")):
                if p[key]:
                    predicates.append(f"DATE(t.{quote(timestamp)}) {op} ?")
                    values.append(p[key])
        if mode == "project_summary":
            for child, alias in (("source_files", "total_files"), ("zenodo_records", "total_zenodo_records"), ("batches", "total_batches")):
                if child in tables:
                    child_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({quote(child)})")}
                    clause = ' WHERE c."project_id" = t."project_id"' if "project_id" in child_columns and "project_id" in available else ""
                    fields.append(f"(SELECT COUNT(*) FROM {quote(child)} c{clause}) AS {quote(alias)}")
                else:
                    fields.append(f"0 AS {quote(alias)}")
        query = f"SELECT {', '.join(fields)} FROM {quote(table)} t " + " ".join(joins)
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += f" ORDER BY t.{quote(columns[0])} LIMIT ?"
        cursor = connection.execute(query, [*values, p["max_rows"] + 1])
        headers = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        truncated = len(rows) > p["max_rows"]
        rows = rows[:p["max_rows"]]
    finally:
        connection.close()
    csv_file = output / "hdpc-export.csv"
    with csv_file.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([safe_csv_cell(name) for name in headers])
        writer.writerows([[safe_csv_cell(value) for value in row] for row in rows])
    if sha256(source) != original_hash:
        raise ValueError("Source database changed during export")
    report = write_json(output / "hdpc-export-report.json", {
        "component": "hdpc_exporter", "upstream_record": "10.5281/zenodo.16995063", "input_name": source.name,
        "source_sha256": original_hash, "source_modified": False, "mode": mode, "table": table,
        "rows_exported": len(rows), "columns": headers, "truncated": truncated,
        "formula_cells_escaped": True, "parameters": p, "csv_sha256": sha256(csv_file),
    })
    return {"csv_file": csv_file, "export_report": report}, {"rows_exported": len(rows), "columns_exported": len(headers), "truncated": truncated}


def run(component, inputs, parameters, output):
    if set(inputs) - {"input_file"}:
        raise ValueError("Unexpected component input")
    return integrity(inputs, parameters, output) if component == "validate_file_integrity" else export_hdpc(inputs, parameters, output)
