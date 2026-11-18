"""Translate an MSF row into a Zenodo dataset and its validated metadata exports."""

import json
import re
from datetime import date
from html import escape
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd

from constants import MSF_ALLOWED_EXTENSIONS
from services.edm_service import EdmService
from services.lod_artifact_service import FILENAMES, generate_artifacts
from services.lod_reliability import FORMATS, MetadataRows, assert_public_document, snapshot_templates, source_identity
from services.msf_service import MSFService
from services.zenodo_metadata_normalizer import normalize_zenodo_metadata, normalize_publication_date

MAX_MSF_BYTES = 2 * 1024 * 1024
MAX_SPREADSHEET_BYTES = 16 * 1024 * 1024

MSF_FIELDS = {
    "zenodo:title": ("title",),
    "zenodo:description": ("description",),
    "zenodo:creators": ("creator", "creators"),
    "zenodo:publication_date": ("publication_date",),
    "zenodo:keywords": ("keywords",),
    "zenodo:license": ("license", "rights", "dc:rights"),
    "zenodo:language": ("language", "dc:language"),
    "dcterms:created": ("dcterms:created",),
    "dc:publisher": ("provider", "dc:publisher", "publisher"),
    "dcterms:spatial": ("locations", "dcterms:spatial"),
    "dcterms:temporal": ("temporal", "dcterms:temporal"),
    "dcterms:medium": ("medium", "dcterms:medium"),
    "dcterms:references": ("references", "dcterms:references"),
    "dc:identifier": ("identifier", "dc:identifier"),
    "edm:intendedUsage": ("intended_usage",),
    "schema:digitalSourceType": ("digital_source_type",),
    "model_type": ("model_type",),
    "edm:vertexCount": ("vertex_count",),
    "edm:polygonCount": ("polygon_count",),
    "edm:pointCount": ("point_count",),
    "dcterms:extent": ("extent",),
}
FORM_FIELDS = {
    "title", "description", "creators", "publication_date", "keywords", "license", "language",
}
FORMAT_LABELS = {"edm": "EDM", "iiif": "IIIF", "mets": "METS/MODS", "cidoc_crm": "CIDOC-CRM", "jsonld": "JSON-LD"}


def _msf_row(path: Path, source_path: str, service: MSFService) -> pd.Series:
    if path.suffix.lower() not in MSF_ALLOWED_EXTENSIONS:
        raise ValueError("Use a CSV, XLSX, or XLS metadata spreadsheet.")
    if path.stat().st_size > MAX_MSF_BYTES:
        raise ValueError("The metadata spreadsheet must be 2 MB or smaller.")
    try:
        if path.suffix.lower() == ".xlsx":
            with ZipFile(path) as workbook:
                entries = workbook.infolist()
                if len(entries) > 512 or sum(entry.file_size for entry in entries) > MAX_SPREADSHEET_BYTES:
                    raise ValueError("The metadata workbook is too large when opened.")
        data, profile = service.parse_msf_file_with_profile(str(path))
    except (ValueError, OSError, BadZipFile) as exc:
        raise ValueError("The metadata spreadsheet could not be read. Check the file and column headings.") from exc

    filename_column = profile["filename_column"]
    if not filename_column:
        raise ValueError("The metadata spreadsheet needs a filename column.")
    data = data.iloc[profile["data_start_row"] :]
    rows = MetadataRows(((row[filename_column], row) for _, row in data.iterrows()), [source_path])
    row = rows.get(source_path)
    if row is None:
        raise ValueError("No metadata row matches the uploaded model. Use its filename or relative path in the spreadsheet.")
    matched_path = source_identity(row[filename_column])
    if "/" in matched_path and matched_path.casefold() != source_identity(source_path).casefold():
        raise ValueError("The metadata row refers to a different model path. Use the relative path in the ZIP.")
    return row


def _mapped_row(row: pd.Series, service: MSFService) -> dict:
    # Use WebHDP's LOD mapper for alias handling and structured field values.
    # Try the alternate headings only when the preferred value is empty.
    metadata = {}
    for tag, fields in MSF_FIELDS.items():
        for field in fields:
            mapped = service.apply_lod_mapping(row, {}, {tag: {"source": "msf", "field": field}}, include_defaults=False)
            if mapped:
                metadata.update(mapped)
                break
    affiliations = service.apply_lod_mapping(
        row, {}, {"affiliation": {"source": "msf", "field": "creator affiliation"}}, include_defaults=False,
    ).get("affiliation", "")
    if affiliations and metadata.get("creators"):
        names = [name.strip() for name in re.split(r"[;|]", affiliations) if name.strip()]
        for index, creator in enumerate(metadata["creators"]):
            if len(names) == 1:
                creator["affiliation"] = names[0]
            elif index < len(names):
                creator["affiliation"] = names[index]
    return metadata


def read_deposit_metadata(source_path: str, *, msf_path: Path | None = None, form_metadata: dict | None = None) -> dict:
    """Map an uploaded spreadsheet or the same fields entered in the deposit form.

    Non-empty spreadsheet fields take precedence. The source path is relative to
    the original package, before repair or renaming.
    """
    service = MSFService()
    form = form_metadata or {}
    row = pd.Series({key: value for key, value in form.items() if key in FORM_FIELDS and isinstance(value, str)}, dtype=object)
    metadata = _mapped_row(row, service)
    if isinstance(form.get("creator"), str) and "creators" not in metadata:
        metadata["creators"] = [{"name": form["creator"].strip()}]
    elif isinstance(form.get("creators"), list):
        metadata["creators"] = [
            {field: person[field].strip() for field in ("name", "affiliation", "orcid") if isinstance(person.get(field), str) and person[field].strip()}
            for person in form["creators"] if isinstance(person, dict)
        ]
    if msf_path is not None:
        metadata.update(_mapped_row(_msf_row(Path(msf_path), source_path, service), service))

    metadata["creators"] = [person for person in metadata.get("creators", []) if person.get("name")]
    if not all(metadata.get(key) for key in ("title", "description", "creators")):
        raise ValueError("Add a title, description, and at least one creator in the form or metadata spreadsheet.")
    if len(metadata["title"]) > 255 or len(metadata["description"]) > 30000:
        raise ValueError("Use a title of at most 255 characters and a description of at most 30,000 characters.")
    if "publication_date" in metadata:
        normalized_date = normalize_publication_date(metadata["publication_date"])
        try:
            if date.fromisoformat(normalized_date).isoformat() != normalized_date:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Use YYYY-MM-DD for the publication date.") from exc
        metadata["publication_date"] = normalized_date
    if "language" in metadata:
        metadata["language"] = metadata["language"].lower()
        if not re.fullmatch(r"[a-z]{3}", metadata["language"]):
            raise ValueError("Use an ISO 639-3 language code such as eng or deu.")
    if "license" in metadata:
        metadata["license"] = metadata["license"].lower()
        if not re.fullmatch(r"[a-z0-9.+-]{1,80}", metadata["license"]):
            raise ValueError("Use a Zenodo license identifier such as cc-by-4.0 or cc0-1.0.")

    assert_public_document(json.dumps(metadata, ensure_ascii=False))
    zenodo = normalize_zenodo_metadata({**metadata, "upload_type": "dataset", "access_right": "open"}, apply_defaults=True)
    # Zenodo's description field interprets HTML. The form and MSF use plain text.
    description = zenodo["description"]
    zenodo["description"] = escape(description).replace("\n", "<br>")
    export_metadata = {**metadata, **zenodo, "description": description}
    return {"zenodo": zenodo, "formats": {standard: dict(export_metadata) for standard in FORMATS}}


def generate_deposit_metadata(
    output_dir: Path, *, draft: dict, metadata: dict, main_file_key: str,
    additional_files: list[dict] | None = None, progress=None, is_sandbox: bool = True,
) -> dict[str, str]:
    """Generate all standard attachments using the actual Zenodo attachment keys."""
    remote_id = str(draft.get("id") or "")
    if not remote_id.isascii() or not remote_id.isdecimal():
        raise ValueError("Zenodo did not provide a record identifier for the metadata exports.")
    if not main_file_key or main_file_key in {".", ".."} or any(separator in main_file_key for separator in ("/", "\\")):
        raise ValueError("Metadata requires the filename of a Zenodo attachment.")
    reserved = (draft.get("metadata") or {}).get("prereserve_doi") or {}
    format_metadata = {standard: dict(values) for standard, values in metadata["formats"].items()}
    service = EdmService()
    record = {"id": remote_id, "links": {"html": "https://sandbox.zenodo.org" if is_sandbox else "https://zenodo.org"}}
    manifest_url = service.generate_content_url(remote_id, FILENAMES["iiif"], is_sandbox=is_sandbox)
    format_metadata["iiif"].update(
        iiif_manifest_id=manifest_url,
        iiif_canvas_id=f"{service.get_record_html_url(record)}/canvas/1",
        iiif_annotation_page_id=f"{manifest_url}#page-1",
        iiif_annotation_id=f"{manifest_url}#annotation-1",
    )
    specification = {
        "options": {},
        "metadata": format_metadata,
        "templates": snapshot_templates({}),
        "record": {
            **record,
            "doi": draft.get("doi") or reserved.get("doi"),
            "files": [],
        },
        "main_file_key": main_file_key,
        "additional_files": [{"key": file["key"], "size": file.get("size", 0)} for file in additional_files or []],
        "allow_placeholder_thumbnail": False,
    }
    outputs, manifest = generate_artifacts(str(output_dir), specification, lambda path, report: None, progress)
    if not all(manifest["formats"][standard]["success"] and standard in outputs for standard in FORMATS):
        failed = [FORMAT_LABELS[standard] for standard in FORMATS if standard not in outputs]
        raise ValueError(f"Metadata validation failed for {', '.join(failed)}. The validation report is available to the operator.")
    return {standard: Path(path).name for standard, path in outputs.items()}
