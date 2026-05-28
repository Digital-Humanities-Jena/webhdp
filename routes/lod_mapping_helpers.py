import os
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
) -> Dict[str, Any]:
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

    fallback_title = infer_row_fallback_title(row, msf_profile)
    normalized_base = normalize_zenodo_metadata(
        zenodo_metadata,
        apply_defaults=True,
        fallback_title=fallback_title,
    )
    mapped_values = msf_service.apply_lod_mapping(
        row,
        zenodo_record,
        mapping_config,
        include_defaults=False,
    )
    return merge_non_empty_metadata(normalized_base, mapped_values)
