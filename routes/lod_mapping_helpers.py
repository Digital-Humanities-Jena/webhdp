import os
import json
from typing import Any, Dict

from services.zenodo_metadata_normalizer import normalize_zenodo_metadata


def has_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def merge_non_empty_metadata(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in (overrides or {}).items():
        if has_non_empty_value(value):
            merged[key] = value
    return merged


def infer_row_fallback_title(row: Any, msf_profile: Dict[str, Any]) -> str:
    filename_column = ""
    if isinstance(msf_profile, dict):
        filename_column = str(msf_profile.get("filename_column") or "").strip()

    filename_value = ""
    if filename_column and hasattr(row, "index") and filename_column in row.index:
        filename_value = str(row.get(filename_column) or "").strip()
    elif hasattr(row, "index") and "filename" in row.index:
        filename_value = str(row.get("filename") or "").strip()

    if filename_value:
        base_name = os.path.basename(filename_value)
        stem = os.path.splitext(base_name)[0]
        if stem:
            return stem
    return "Untitled"


def build_pipeline_aligned_lod_metadata(
    *,
    msf_service: Any,
    row: Any,
    zenodo_record: Dict[str, Any],
    mapping_config: Dict[str, Any],
    msf_profile: Dict[str, Any],
    zenodo_mapping: Dict[str, Any] | None = None,
    session_id: int | None = None,
    with_provenance: bool = False,
) -> Dict[str, Any] | tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Build LOD metadata in the same spirit as pipeline execution:
    1) start from normalized Zenodo metadata defaults,
    2) apply mapper values without mapper defaults,
    3) merge only non-empty mapped values over base metadata.
    """
    zenodo_metadata = {}
    if isinstance(zenodo_record, dict):
        candidate = zenodo_record.get("metadata")
        if isinstance(candidate, dict):
            zenodo_metadata = dict(candidate)

    provenance = {key: {'source': 'entered'} for key, value in zenodo_metadata.items() if has_non_empty_value(value)}
    item_defaults = {}
    source_name = str(row.get((msf_profile or {}).get('filename_column') or 'filename', '') or '').strip().replace('\\', '/')
    if session_id is not None:
        from database.models import BatchFileMetadata
        from services.lod_reliability import MetadataRows
        from services.submission_pipeline_service import _split_batch_shared_zenodo_metadata
        entries = BatchFileMetadata.query.filter_by(session_id=session_id).all()
        rows = MetadataRows([(entry.filename, json.loads(entry.metadata_json)) for entry in entries], [entry.filename for entry in entries])
        shared, item_defaults = _split_batch_shared_zenodo_metadata(zenodo_metadata)
        batch_metadata = rows.get(source_name) or {}
        zenodo_metadata = merge_non_empty_metadata(shared, batch_metadata)
        provenance = {key: {'source': 'batch' if has_non_empty_value(batch_metadata.get(key)) else 'shared'}
                      for key, value in zenodo_metadata.items() if has_non_empty_value(value)}
        zenodo_record = {**zenodo_record, 'metadata': zenodo_metadata}

    if zenodo_mapping:
        zenodo_metadata = merge_non_empty_metadata(zenodo_metadata, msf_service.apply_lod_mapping(
            row, zenodo_record, zenodo_mapping, include_defaults=False))
        zenodo_record = {**zenodo_record, "metadata": zenodo_metadata}

    fallback_title = infer_row_fallback_title(row, msf_profile)
    fallback_options = {}
    if session_id is not None:
        from services.submission_pipeline_service import _derive_batch_fallback_title, _derive_batch_fallback_creators, NEUTRAL_ITEM_DESCRIPTION
        fallback_title = _derive_batch_fallback_title(zenodo_metadata, source_name)
        fallback_options = {'fallback_description': NEUTRAL_ITEM_DESCRIPTION,
                            'fallback_creators': _derive_batch_fallback_creators(zenodo_metadata, item_defaults)}
    normalized_base = normalize_zenodo_metadata(
        zenodo_metadata,
        apply_defaults=True,
        fallback_title=fallback_title,
        **fallback_options,
    )
    # Keep LOD-only settings (such as the provider) which the Zenodo normalizer
    # intentionally excludes from API metadata, just as submission does.
    normalized_base = merge_non_empty_metadata(zenodo_metadata, normalized_base)
    zenodo_record = {**zenodo_record, 'metadata': normalized_base}
    mapped_values = msf_service.apply_lod_mapping(
        row,
        zenodo_record,
        mapping_config,
        include_defaults=False,
    )
    metadata = merge_non_empty_metadata(normalized_base, mapped_values)
    if not with_provenance:
        return metadata
    for key in normalized_base:
        if key not in provenance:
            provenance[key] = {'source': 'inferred' if key == 'title' else 'default'}
    for config in (zenodo_mapping or {}, mapping_config or {}):
        for tag, item in config.items():
            values = msf_service.apply_lod_mapping(row, zenodo_record, {tag: item}, include_defaults=False)
            for key, value in values.items():
                if has_non_empty_value(value):
                    origin = provenance.get(item.get('field'), {}) if item.get('source') == 'zenodo' else {}
                    source = origin.get('source') if origin.get('source') in ('default', 'inferred') else 'mapped' if item.get('source') in ('msf', 'zenodo') else 'entered'
                    provenance[key] = {'source': source, 'field': item.get('field') or 'Static value'}
    return metadata, provenance


def record_for_metadata_row(row, profile, record):
    """Preview the selected source's modality instead of a fixed example model."""
    column = (profile or {}).get('filename_column') or 'filename'
    value = str(row.get(column, '') or '').strip().replace('\\', '/')
    if not value or value.lower() == 'nan':
        raise ValueError('The selected metadata row needs a source filename')
    name = os.path.basename(value)
    from services.edm_service import EdmService
    record = dict(record or {})
    files = EdmService()._normalize_zenodo_files(record)
    if not any((file.get('key') or file.get('filename')) == name for file in files):
        files = [{'key': name, 'filename': name}]
    record['files'] = files
    return record, name


def spreadsheet_samples(df, profile, service):
    """Name every source row and summarize input gaps; this does not validate exports."""
    filename_column = profile.get('filename_column') or 'filename'
    mapping = service.suggest_column_mapping(list(df.columns))
    aliases = {'_creators_raw': 'creators', '_filename': 'filename'}
    columns = {aliases.get(target, target): column for column, target in mapping.items()}
    samples, missing = [], {'filename': 0, 'title': 0, 'description': 0, 'creators': 0}
    names = {}
    def text(value):
        value = str(value).strip() if value is not None else ''
        return '' if value.lower() in ('nan', 'none', '<na>') else value
    for index, (_, row) in enumerate(df.iterrows()):
        name = text(row.get(filename_column))
        title = text(row.get(columns.get('title', 'title')))
        samples.append({'row_index': index, 'filename': name, 'title': title,
                        'label': f"{name or 'Missing filename'} · row {index + 1}"})
        if name:
            names[name.casefold()] = names.get(name.casefold(), 0) + 1
        for key in missing:
            column = filename_column if key == 'filename' else columns.get(key, columns.get('creator', 'creator') if key == 'creators' else key)
            if not text(row.get(column)):
                missing[key] += 1
    return {'sample_records': samples, 'quality_summary': {'row_count': len(df), 'missing': missing,
            'duplicate_source_count': sum(count - 1 for count in names.values() if count > 1),
            'scope': 'Spreadsheet values before defaults; export validation applies only to the selected preview.'}}
