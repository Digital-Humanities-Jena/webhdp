# services/msf_service.py
"""Service for handling Metadata Source File (MSF) parsing and validation"""

import logging
import os
import re
import csv
import unicodedata
from difflib import SequenceMatcher
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from constants import (
    DEFAULT_MSF_COLUMN_MAPPING,
    MSF_ALLOWED_EXTENSIONS,
    MSF_CSV_DELIMITER,
    MSF_UPLOAD_TYPE_MAPPING,
)

logger = logging.getLogger(__name__)


@dataclass
class MSFValidationResult:
    """Result of validating MSF against directory files"""
    is_valid: bool
    filename_column: str
    filename_detection_confidence: float = 0.0
    matched_files: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)  # In MSF but not in directory
    unmapped_files: List[str] = field(default_factory=list)  # In directory but not in MSF
    implicitly_included_files: List[str] = field(default_factory=list)  # Referenced dependencies
    duplicate_msf_files: List[str] = field(default_factory=list)
    duplicate_directory_files: List[str] = field(default_factory=list)
    duplicate_directory_details: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "filename_column": self.filename_column,
            "filename_detection_confidence": self.filename_detection_confidence,
            "matched_files": self.matched_files,
            "missing_files": self.missing_files,
            "unmapped_files": self.unmapped_files,
            "implicitly_included_files": self.implicitly_included_files,
            "duplicate_msf_files": self.duplicate_msf_files,
            "duplicate_directory_files": self.duplicate_directory_files,
            "duplicate_directory_details": self.duplicate_directory_details,
            "matched_count": len(self.matched_files),
            "missing_count": len(self.missing_files),
            "unmapped_count": len(self.unmapped_files),
            "implicitly_included_count": len(self.implicitly_included_files),
            "duplicate_msf_count": len(self.duplicate_msf_files),
            "duplicate_directory_count": len(self.duplicate_directory_files),
            "errors": self.errors,
            "warnings": self.warnings,
        }


class MSFService:
    """Service for Metadata Source File operations"""

    def __init__(self):
        self.allowed_extensions = MSF_ALLOWED_EXTENSIONS
        self.csv_delimiter = MSF_CSV_DELIMITER
        self.default_mapping = DEFAULT_MSF_COLUMN_MAPPING
        self.filename_extensions = {
            ".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply", ".dae", ".3ds", ".blend",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg",
            ".mp4", ".avi", ".mov", ".mkv", ".webm", ".wmv",
            ".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a",
            ".pdf", ".txt", ".csv", ".xml", ".json",
        }
        self.column_aliases = {
            "file": "filename",
            "file_name": "filename",
            "filepath": "filename",
            "path": "filename",
            "dc:title": "title",
            "dc:creator": "creator",
            "dc:description": "description",
            "dc:subject": "keywords",
            "dc:date": "dcterms:created",
            "dc:identifier": "identifier",
            "dc:type": "dc:type",
            "creator_affiliation": "creator affiliation",
            "creator affiliation": "creator affiliation",
            "affiliation": "creator affiliation",
            "date": "dcterms:created",
            "created": "dcterms:created",
            "dcterms_created": "dcterms:created",
            "edm:intendedusage": "intended usage",
            "intendedusage": "intended usage",
            "schema:digitalsourcetype": "digital source type",
            "digitalsourcetype": "digital source type",
            "modeltype": "model type",
            "edm:vertexcount": "vertex count",
            "edm:polygoncount": "polygon count",
            "edm:pointcount": "point count",
            "pointcount": "point count",
            "dcterms:extent": "extent",
        }
        self.instruction_markers = [
            "case-sensitive",
            "auto-increment",
            "iso 8601",
            "validation rules",
            "select from dropdown",
            "max. 255 chars",
        ]

    def _normalize_column_key(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = text.replace("-", "_").replace(" ", "_")
        return re.sub(r"_+", "_", text)

    def _is_instruction_text(self, value: Any) -> bool:
        text = str(value or "").strip().lower()
        return any(marker in text for marker in self.instruction_markers)

    def _looks_like_filename(self, value: Any) -> bool:
        text = str(value or "").strip()
        if not text or self._is_instruction_text(text):
            return False
        ext = os.path.splitext(text)[1].lower()
        return ext in self.filename_extensions

    def _coerce_bool(self, value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return None

    def _normalize_mapped_scalar(self, value: Any) -> Optional[str]:
        """Normalize scalar mapping values; return None for null-like placeholders."""
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass

        text = str(value).strip()
        if not text:
            return None
        if text.lower() in {"nan", "none", "null", "nat", "<na>"}:
            return None
        return text

    def _normalize_reference_key(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKD", text)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = normalized.lower().replace("&", "and")
        normalized = re.sub(r"\(\d+\)", "", normalized)
        normalized = re.sub(r"\bcopy\b", "", normalized)
        normalized = re.sub(r"[^a-z0-9]+", "", normalized)
        return normalized.strip()

    def _looks_like_embedded_header_row(
        self,
        row_values: List[Any],
        columns: List[str],
        filename_column: Optional[str],
    ) -> bool:
        normalized_columns = {
            self._normalize_column_key(col) for col in columns if str(col or "").strip()
        }
        normalized_columns.update(
            {
                self.column_aliases.get(self._normalize_column_key(col), self._normalize_column_key(col))
                for col in columns
                if str(col or "").strip()
            }
        )
        normalized_columns.update(
            {
                self._normalize_column_key(key)
                for key in self.default_mapping.keys()
                if str(key or "").strip()
            }
        )
        if filename_column:
            normalized_columns.add(self._normalize_column_key(filename_column))

        normalized_cells = [
            self._normalize_column_key(value)
            for value in row_values
            if str(value or "").strip()
        ]
        if len(normalized_cells) < 2:
            return False

        matched_cells = sum(1 for value in normalized_cells if value in normalized_columns)
        if matched_cells < 2:
            return False

        first_value = normalized_cells[0]
        return first_value in {
            "filename",
            self._normalize_column_key(filename_column),
        }

    def _repair_filename_reference_values(
        self,
        values: List[Any],
        available_files: Optional[List[str]],
        *,
        match_by_stem: bool = True,
        fuzzy_match: bool = True,
        min_similarity: float = 0.9,
        min_margin: float = 0.05,
        enforce_unique_matches: bool = True,
    ) -> Dict[str, Any]:
        available = [str(item).strip() for item in (available_files or []) if str(item or "").strip()]
        if not available:
            return {
                "values": list(values),
                "changed_cells": 0,
                "unresolved_count": 0,
                "unresolved_preview": [],
                "strategy_counts": {},
            }

        basename_lookup: Dict[str, List[str]] = {}
        canonical_lookup: Dict[str, List[str]] = {}
        stem_lookup: Dict[str, List[str]] = {}
        stem_canonical_lookup: Dict[str, List[str]] = {}
        for name in available:
            basename_lookup.setdefault(name.lower(), []).append(name)

            canonical = self._normalize_reference_key(name)
            if canonical:
                canonical_lookup.setdefault(canonical, []).append(name)

            stem = os.path.splitext(name)[0].lower()
            if stem:
                stem_lookup.setdefault(stem, []).append(name)
                stem_canonical = self._normalize_reference_key(stem)
                if stem_canonical:
                    stem_canonical_lookup.setdefault(stem_canonical, []).append(name)

        canonical_basenames = sorted(canonical_lookup.keys())
        stem_canonical_basenames = sorted(stem_canonical_lookup.keys())

        def _pick_unique(items: List[str]) -> Optional[str]:
            unique_items = sorted(set(items), key=lambda item: item.lower())
            if len(unique_items) == 1:
                return unique_items[0]
            return None

        used_targets: Set[str] = set()
        updated_values = list(values)
        candidates: List[Dict[str, Any]] = []
        unresolved_preview: List[Dict[str, Any]] = []
        unresolved_count = 0
        unresolved_row_indices: List[int] = []

        for raw_value in values:
            original = str(raw_value or "").strip()
            if not original:
                continue

            normalized = self._normalize_filename_value(original)
            if normalized and normalized.lower() in basename_lookup:
                used_targets.add(basename_lookup[normalized.lower()][0].lower())

        for idx, raw_value in enumerate(values):
            original = str(raw_value or "").strip()
            if not original:
                continue

            normalized = self._normalize_filename_value(original)
            if not normalized or normalized.lower() in basename_lookup:
                continue

            stem = os.path.splitext(normalized)[0].lower()
            canonical = self._normalize_reference_key(normalized)
            stem_canonical = self._normalize_reference_key(stem)
            candidate_name = None
            strategy = None
            score = 0.0
            top_similarity = 0.0
            second_similarity = 0.0

            if match_by_stem and stem:
                candidate_name = _pick_unique(stem_lookup.get(stem, []))
                if candidate_name:
                    strategy = "stem_exact"
                    score = 0.99

            if not candidate_name and canonical:
                candidate_name = _pick_unique(canonical_lookup.get(canonical, []))
                if candidate_name:
                    strategy = "canonical_exact"
                    score = 0.98

            if not candidate_name and match_by_stem and stem_canonical:
                candidate_name = _pick_unique(stem_canonical_lookup.get(stem_canonical, []))
                if candidate_name:
                    strategy = "stem_canonical_exact"
                    score = 0.97

            if not candidate_name and fuzzy_match and stem_canonical and stem_canonical_basenames:
                scored_candidates = []
                for candidate_key in stem_canonical_basenames:
                    similarity = SequenceMatcher(None, stem_canonical, candidate_key).ratio()
                    if similarity <= 0:
                        continue
                    unique_candidate = _pick_unique(stem_canonical_lookup.get(candidate_key, []))
                    if unique_candidate:
                        scored_candidates.append((similarity, unique_candidate))
                scored_candidates.sort(reverse=True)
                if scored_candidates:
                    top_similarity, top_candidate = scored_candidates[0]
                    second_similarity = scored_candidates[1][0] if len(scored_candidates) > 1 else 0.0
                    if (
                        top_similarity >= float(min_similarity)
                        and (top_similarity - second_similarity) >= float(min_margin)
                    ):
                        candidate_name = top_candidate
                        strategy = "stem_fuzzy"
                        score = top_similarity

            if not candidate_name and fuzzy_match and canonical and canonical_basenames:
                scored_candidates: List[Tuple[float, str]] = []
                for candidate_key in canonical_basenames:
                    similarity = SequenceMatcher(None, canonical, candidate_key).ratio()
                    if similarity <= 0:
                        continue
                    unique_candidate = _pick_unique(canonical_lookup.get(candidate_key, []))
                    if unique_candidate:
                        scored_candidates.append((similarity, unique_candidate))
                scored_candidates.sort(reverse=True)
                if scored_candidates:
                    top_similarity, top_candidate = scored_candidates[0]
                    second_similarity = scored_candidates[1][0] if len(scored_candidates) > 1 else 0.0
                    if (
                        top_similarity >= float(min_similarity)
                        and (top_similarity - second_similarity) >= float(min_margin)
                    ):
                        candidate_name = top_candidate
                        strategy = "fuzzy"
                        score = top_similarity

            if candidate_name and strategy:
                candidates.append(
                    {
                        "row_index": idx,
                        "original": original,
                        "normalized": normalized,
                        "candidate": candidate_name,
                        "strategy": strategy,
                        "score": float(score),
                        "similarity": float(top_similarity),
                        "margin": float(max(top_similarity - second_similarity, 0.0)),
                    }
                )
            else:
                unresolved_count += 1
                unresolved_row_indices.append(idx)
                if len(unresolved_preview) < 50:
                    unresolved_preview.append(
                        {
                            "row_index": int(idx + 2),
                            "value": original,
                            "normalized": normalized,
                        }
                    )

        strategy_priority = {"stem_exact": 3, "canonical_exact": 2, "fuzzy": 1}
        candidates.sort(
            key=lambda item: (
                strategy_priority.get(str(item.get("strategy")), 0),
                float(item.get("score") or 0.0),
                -int(item.get("row_index") or 0),
            ),
            reverse=True,
        )

        changed_cells = 0
        strategy_counts: Counter[str] = Counter()
        for idx, raw_value in enumerate(values):
            original = str(raw_value or "").strip()
            if not original:
                continue
            normalized = self._normalize_filename_value(original)
            if (
                normalized
                and normalized.lower() in basename_lookup
                and original != normalized
            ):
                updated_values[idx] = basename_lookup[normalized.lower()][0]
                changed_cells += 1
                strategy_counts.update(["basename_normalized"])

        for item in candidates:
            candidate_lower = str(item["candidate"]).lower()
            if enforce_unique_matches and candidate_lower in used_targets:
                unresolved_count += 1
                unresolved_row_indices.append(int(item["row_index"]))
                if len(unresolved_preview) < 50:
                    unresolved_preview.append(
                        {
                            "row_index": int(item["row_index"] + 2),
                            "value": item["original"],
                            "normalized": item["normalized"],
                            "conflict_with": item["candidate"],
                        }
                    )
                continue
            if item["original"] != item["candidate"]:
                updated_values[item["row_index"]] = item["candidate"]
                changed_cells += 1
                strategy_counts.update([str(item["strategy"])])
            if enforce_unique_matches:
                used_targets.add(candidate_lower)

        return {
            "values": updated_values,
            "changed_cells": int(changed_cells),
            "unresolved_count": int(unresolved_count),
            "unresolved_row_indices": unresolved_row_indices,
            "unresolved_preview": unresolved_preview,
            "strategy_counts": dict(strategy_counts),
        }

    def _build_directory_duplicate_details(self, directory_root: Optional[str]) -> List[Dict[str, Any]]:
        if not directory_root or not os.path.isdir(directory_root):
            return []

        groups: Dict[str, List[str]] = {}
        real_root = os.path.realpath(directory_root)
        for root, _, files in os.walk(directory_root):
            for name in files:
                if name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in self.allowed_extensions:
                    continue
                full_path = os.path.join(root, name)
                try:
                    rel_path = os.path.relpath(os.path.realpath(full_path), real_root)
                except Exception:
                    rel_path = os.path.relpath(full_path, directory_root)
                groups.setdefault(name.lower(), []).append(rel_path)

        details: List[Dict[str, Any]] = []
        for basename, paths in sorted(groups.items()):
            unique_paths = sorted(set(paths), key=lambda item: item.lower())
            if len(unique_paths) < 2:
                continue
            suggested_directories = sorted(
                {
                    path.split(os.sep, 1)[0]
                    for path in unique_paths
                    if path and os.sep in path
                },
                key=lambda item: item.lower(),
            )
            details.append(
                {
                    "basename": basename,
                    "paths": unique_paths,
                    "suggested_directories": suggested_directories,
                }
            )
        return details

    def _parse_creators_value(self, value: str) -> List[Dict[str, str]]:
        """
        Parse creator strings while preserving surname-first names such as
        "Surname, GivenName". Supports explicit multi-creator separators (; or |).
        """
        normalized = self._normalize_mapped_scalar(value)
        if not normalized:
            return []

        tokens: List[str] = []
        if ";" in normalized or "|" in normalized:
            for raw_token in re.split(r"[;|]", normalized):
                token = self._normalize_mapped_scalar(raw_token)
                if token:
                    tokens.append(token)
        else:
            comma_parts = [part.strip() for part in normalized.split(",") if self._normalize_mapped_scalar(part)]
            if len(comma_parts) == 2:
                left, right = comma_parts
                # "Alice Doe, Bob Doe" => likely two creators.
                if " " in left and " " in right:
                    tokens.extend([left, right])
                else:
                    # "Schild, Romuald" => one creator in surname-first notation.
                    tokens.append(f"{left}, {right}")
            elif (
                len(comma_parts) > 2
                and len(comma_parts) % 2 == 0
                and all(" " not in part for part in comma_parts)
            ):
                # "Surname, Given, OtherSurname, OtherGiven" style.
                for idx in range(0, len(comma_parts), 2):
                    tokens.append(f"{comma_parts[idx]}, {comma_parts[idx + 1]}")
            else:
                tokens.extend(comma_parts)

        return [{"name": token} for token in tokens if self._normalize_mapped_scalar(token)]

    def _normalize_parse_options(self, parse_options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        options = dict(parse_options or {})
        normalized = {}
        if "sheet_name" in options and options["sheet_name"] not in ("", None):
            normalized["sheet_name"] = str(options["sheet_name"]).strip()

        if "use_first_row_as_header" in options:
            normalized["use_first_row_as_header"] = self._coerce_bool(options.get("use_first_row_as_header"))

        if "delimiter" in options and options["delimiter"]:
            normalized["delimiter"] = str(options["delimiter"])

        return normalized

    def _parse_csv_raw(
        self, file_path: str, delimiter: Optional[str], header: Optional[int]
    ) -> pd.DataFrame:
        if delimiter:
            return pd.read_csv(file_path, delimiter=delimiter, dtype=str, header=header)

        # Default behavior: try configured delimiter first, then comma.
        primary = self.csv_delimiter or ";"
        try:
            df = pd.read_csv(file_path, delimiter=primary, dtype=str, header=header)
            if len(df.columns) <= 1 and primary != ",":
                return pd.read_csv(file_path, delimiter=",", dtype=str, header=header)
            return df
        except Exception:
            return pd.read_csv(file_path, delimiter=",", dtype=str, header=header)

    def _detect_csv_delimiter(self, file_path: str) -> Optional[str]:
        try:
            with open(file_path, "r", encoding="utf-8-sig", newline="") as handle:
                sample = handle.read(65536)
            if not sample:
                return None
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
                return dialect.delimiter
            except csv.Error:
                first_line = next((line for line in sample.splitlines() if line.strip()), "")
                counts = {candidate: first_line.count(candidate) for candidate in [",", ";", "\t", "|"]}
                delimiter, count = max(counts.items(), key=lambda item: item[1])
                return delimiter if count > 0 else None
        except OSError:
            return None

    def _is_headerless_csv(self, df_header: pd.DataFrame, df_no_header: pd.DataFrame) -> bool:
        header_names = [str(col).strip() for col in df_header.columns]
        normalized_headers = [self._normalize_column_key(col) for col in header_names]
        known_header_count = 0
        suspicious_header_count = 0
        filename_like_header_count = 0

        canonical_keys = set(self.default_mapping.keys())
        for key in normalized_headers:
            canonical = self.column_aliases.get(key, key).replace("_", " ")
            if canonical in canonical_keys:
                known_header_count += 1

        for col in header_names:
            if self._looks_like_filename(col):
                filename_like_header_count += 1
            if (
                len(col) > 80
                or col.lower().startswith("unnamed:")
                or ("," in col and " " in col and len(col) > 40)
            ):
                suspicious_header_count += 1

        if df_no_header.empty:
            return False

        first_row = df_no_header.iloc[0].tolist()
        first_row_filename_like = sum(1 for value in first_row if self._looks_like_filename(value))
        first_row_non_empty = sum(1 for value in first_row if str(value or "").strip())
        first_row_filename_ratio = (
            first_row_filename_like / first_row_non_empty if first_row_non_empty else 0.0
        )

        # Headerless signal: no recognizable headers, but header row appears data-like.
        return (
            known_header_count == 0
            and (suspicious_header_count > 0 or filename_like_header_count > 0)
            and first_row_filename_ratio >= 0.2
        )

    def _infer_headerless_column_names(self, df: pd.DataFrame) -> List[str]:
        columns = list(df.columns)
        inferred = [f"column_{idx + 1}" for idx in range(len(columns))]
        if df.empty or not columns:
            return inferred

        stats = {}
        for col in columns:
            values = [str(v).strip() for v in df[col].tolist() if str(v).strip()]
            non_empty_count = len(values)
            filename_ratio = (
                sum(1 for value in values if self._looks_like_filename(value)) / non_empty_count
                if non_empty_count
                else 0.0
            )
            avg_len = (
                sum(len(value) for value in values) / non_empty_count if non_empty_count else 0.0
            )
            unique_ratio = (
                len(set(value.lower() for value in values)) / non_empty_count if non_empty_count else 0.0
            )
            identifier_ratio = (
                sum(1 for value in values if re.search(r"\d", value) and len(value) <= 24) / non_empty_count
                if non_empty_count
                else 0.0
            )
            date_like_ratio = (
                sum(
                    1
                    for value in values
                    if re.search(r"\b\d{4}\b", value) or re.search(r"\b(BC|AD|century)\b", value, re.I)
                )
                / non_empty_count
                if non_empty_count
                else 0.0
            )
            stats[col] = {
                "filename_ratio": filename_ratio,
                "avg_len": avg_len,
                "unique_ratio": unique_ratio,
                "identifier_ratio": identifier_ratio,
                "date_like_ratio": date_like_ratio,
            }

        assigned: Set[int] = set()

        def assign(label: str, col_idx: Optional[int], min_score: float = 0.0, score: float = 1.0) -> None:
            if col_idx is None or col_idx in assigned or score < min_score:
                return
            inferred[col_idx] = label
            assigned.add(col_idx)

        # filename
        filename_idx = None
        filename_score = 0.0
        for idx, col in enumerate(columns):
            score = stats[col]["filename_ratio"]
            if score > filename_score:
                filename_score = score
                filename_idx = idx
        assign("filename", filename_idx, min_score=0.15, score=filename_score)

        # description (long free text)
        desc_idx = None
        desc_score = 0.0
        for idx, col in enumerate(columns):
            if idx in assigned:
                continue
            score = stats[col]["avg_len"] / 100.0
            if score > desc_score:
                desc_score = score
                desc_idx = idx
        assign("description", desc_idx, min_score=0.4, score=desc_score)

        # title (short-medium text, usually unique)
        title_idx = None
        title_score = 0.0
        for idx, col in enumerate(columns):
            if idx in assigned:
                continue
            avg_len = stats[col]["avg_len"]
            if avg_len < 3 or avg_len > 90:
                continue
            score = stats[col]["unique_ratio"] + (1.0 - abs(avg_len - 35) / 35.0)
            if score > title_score:
                title_score = score
                title_idx = idx
        assign("title", title_idx, min_score=0.8, score=title_score)

        # creator/institution-like (repeated text values)
        creator_idx = None
        creator_score = 0.0
        for idx, col in enumerate(columns):
            if idx in assigned:
                continue
            avg_len = stats[col]["avg_len"]
            if avg_len < 3 or avg_len > 120:
                continue
            score = (1.0 - stats[col]["unique_ratio"]) + (1.0 - abs(avg_len - 25) / 25.0)
            if score > creator_score:
                creator_score = score
                creator_idx = idx
        assign("creator", creator_idx, min_score=0.6, score=creator_score)

        # identifier
        id_idx = None
        id_score = 0.0
        for idx, col in enumerate(columns):
            if idx in assigned:
                continue
            score = stats[col]["identifier_ratio"] - (stats[col]["avg_len"] / 100.0)
            if score > id_score:
                id_score = score
                id_idx = idx
        assign("identifier", id_idx, min_score=0.3, score=id_score)

        # date-ish
        date_idx = None
        date_score = 0.0
        for idx, col in enumerate(columns):
            if idx in assigned:
                continue
            score = stats[col]["date_like_ratio"]
            if score > date_score:
                date_score = score
                date_idx = idx
        assign("dcterms:created", date_idx, min_score=0.2, score=date_score)

        return inferred

    def _score_excel_sheet(self, df: pd.DataFrame) -> float:
        if df.empty or len(df.columns) == 0:
            return -1.0

        columns = [str(col).strip() for col in df.columns]
        normalized = [self._normalize_column_key(col) for col in columns]
        mapped_count = 0
        canonical_keys = set(self.default_mapping.keys())
        for key in normalized:
            canonical = self.column_aliases.get(key, key).replace("_", " ")
            if canonical in canonical_keys:
                mapped_count += 1

        filename_like_best = 0
        sample = df.head(200).fillna("")
        for col in sample.columns:
            count = sum(1 for value in sample[col].tolist() if self._looks_like_filename(value))
            filename_like_best = max(filename_like_best, count)

        non_empty_rows = int(sample.replace("", pd.NA).dropna(how="all").shape[0])
        return mapped_count * 10 + filename_like_best * 2 + non_empty_rows * 0.05

    def _select_excel_sheet(self, file_path: str, options: Dict[str, Any]) -> Tuple[str, List[str], Dict[str, float]]:
        xls = pd.ExcelFile(file_path)
        available_sheets = xls.sheet_names
        requested_sheet = options.get("sheet_name")
        if requested_sheet in available_sheets:
            return requested_sheet, available_sheets, {requested_sheet: 0.0}

        sheet_scores: Dict[str, float] = {}
        best_sheet = available_sheets[0]
        best_score = -1.0
        for sheet_name in available_sheets:
            try:
                sheet_df = pd.read_excel(file_path, sheet_name=sheet_name, dtype=str)
            except Exception:
                sheet_scores[sheet_name] = -1.0
                continue
            score = self._score_excel_sheet(sheet_df)
            sheet_scores[sheet_name] = score
            if score > best_score:
                best_score = score
                best_sheet = sheet_name

        return best_sheet, available_sheets, sheet_scores

    def _detect_data_start_row(self, df: pd.DataFrame, filename_column: Optional[str]) -> int:
        if df.empty:
            return 0
        if filename_column and filename_column in df.columns:
            for idx in range(len(df)):
                value = df.iloc[idx][filename_column]
                if self._looks_like_filename(value):
                    return idx

        for idx in range(len(df)):
            row_values = df.iloc[idx].tolist()
            if any(str(value or "").strip() for value in row_values):
                if not any(self._is_instruction_text(value) for value in row_values):
                    return idx
        return 0

    def suggest_sample_row_index(self, df: pd.DataFrame, filename_column: Optional[str] = None) -> int:
        if df.empty:
            return 0

        candidate_column = filename_column
        if not candidate_column or candidate_column not in df.columns:
            hint_candidates = [
                col for col in df.columns if self._normalize_column_key(col) in {"filename", "file", "file_name"}
            ]
            if hint_candidates:
                candidate_column = hint_candidates[0]

        if candidate_column and candidate_column in df.columns:
            for idx in range(len(df)):
                value = df.iloc[idx][candidate_column]
                if self._looks_like_filename(value):
                    return idx

        return self._detect_data_start_row(df, filename_column=None)

    def parse_msf_file_with_profile(
        self, file_path: str, parse_options: Optional[Dict[str, Any]] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        if not os.path.exists(file_path):
            raise ValueError(f"MSF file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.allowed_extensions:
            raise ValueError(f"Unsupported file format: {ext}. Allowed: {self.allowed_extensions}")

        options = self._normalize_parse_options(parse_options)

        try:
            profile: Dict[str, Any] = {
                "file_path": file_path,
                "file_type": "csv" if ext == ".csv" else "excel",
                "parse_options": {},
                "sheet_name": None,
                "available_sheets": [],
                "header_row_index": 0,
                "filename_column": None,
                "filename_confidence": 0.0,
            }

            if ext == ".csv":
                explicit_header_pref = options.get("use_first_row_as_header")
                delimiter = options.get("delimiter") or self._detect_csv_delimiter(file_path)

                df_header = self._parse_csv_raw(file_path, delimiter=delimiter, header=0)
                df_no_header = self._parse_csv_raw(file_path, delimiter=delimiter, header=None)

                if explicit_header_pref is None:
                    use_first_row_as_header = not self._is_headerless_csv(df_header, df_no_header)
                else:
                    use_first_row_as_header = bool(explicit_header_pref)

                if use_first_row_as_header:
                    df = df_header
                    profile["header_row_index"] = 0
                else:
                    df = df_no_header
                    df.columns = self._infer_headerless_column_names(df)
                    profile["header_row_index"] = None

                profile["parse_options"] = {
                    "use_first_row_as_header": use_first_row_as_header,
                    "delimiter": delimiter or self.csv_delimiter,
                }

            elif ext in [".xlsx", ".xls"]:
                selected_sheet, available_sheets, sheet_scores = self._select_excel_sheet(file_path, options)
                df = pd.read_excel(file_path, sheet_name=selected_sheet, dtype=str)
                profile["sheet_name"] = selected_sheet
                profile["available_sheets"] = available_sheets
                profile["sheet_scores"] = sheet_scores
                profile["parse_options"] = {"sheet_name": selected_sheet}
            else:
                raise ValueError(f"Unsupported file format: {ext}")

            # Clean DataFrame
            df.columns = [str(col).strip() for col in df.columns]
            df = df.dropna(how="all").fillna("").reset_index(drop=True)

            detected_filename_col, detected_conf = self.detect_filename_column(df, [])
            profile["filename_column"] = detected_filename_col
            profile["filename_confidence"] = round(detected_conf, 3)
            profile["data_start_row"] = self._detect_data_start_row(df, detected_filename_col)
            profile["suggested_row_index"] = self.suggest_sample_row_index(df, detected_filename_col)
            profile["columns"] = list(df.columns)
            profile["row_count"] = len(df)
            profile["column_count"] = len(df.columns)

            logger.info(
                "Parsed MSF file with profile: %s rows, %s cols, filename column=%s",
                len(df),
                len(df.columns),
                profile.get("filename_column"),
            )
            return df, profile
        except Exception as e:
            logger.error(f"Failed to parse MSF file: {e}", exc_info=True)
            raise ValueError(f"Failed to parse MSF file: {e}")

    def parse_msf_file(
        self, file_path: str, parse_options: Optional[Dict[str, Any]] = None
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Parse an MSF file (Excel or CSV) and return a DataFrame.

        Args:
            file_path: Path to the MSF file

        Returns:
            Tuple of (DataFrame, list of column names)

        Raises:
            ValueError: If file format is not supported or file cannot be parsed
        """
        df, _profile = self.parse_msf_file_with_profile(file_path, parse_options=parse_options)
        return df, list(df.columns)

    def detect_filename_column(
        self, df: pd.DataFrame, directory_files: List[str]
    ) -> Tuple[Optional[str], float]:
        """
        Auto-detect which column contains filenames by comparing values against directory files.

        Args:
            df: Parsed MSF DataFrame
            directory_files: List of filenames from the directory

        Returns:
            Tuple of (best matching column name, match ratio 0.0-1.0)
        """
        if not directory_files:
            # Even if no directory files, we might be able to detect based on headers
            # to provide better error messages later (e.g. "0 files matched")
            logger.debug("No directory files provided for filename detection")

        directory_files_set = set(f.lower() for f in directory_files)
        best_column = None
        best_ratio = 0.0

        for col in df.columns:
            # Get unique non-empty values from this column
            col_values = set(
                str(v).strip().lower()
                for v in df[col].unique()
                if pd.notna(v) and str(v).strip()
            )

            if not col_values:
                continue

            matches = col_values.intersection(directory_files_set)
            filename_like_ratio = (
                sum(1 for value in col_values if self._looks_like_filename(value)) / len(col_values)
                if col_values
                else 0.0
            )
            if directory_files_set:
                ratio = len(matches) / len(col_values)
            else:
                # No directory set: rely on value-shape confidence.
                ratio = filename_like_ratio

            logger.debug(
                "Column '%s': matches=%s/%s, filename_like=%.2f, score=%.2f",
                col,
                len(matches),
                len(col_values),
                filename_like_ratio,
                ratio,
            )

            if ratio > best_ratio:
                best_ratio = ratio
                best_column = col

        # Also check for column names that suggest filenames
        filename_hints = ["filename", "file", "name", "filepath", "file_name"]
        for col in df.columns:
            col_lower = col.lower().strip()
            if any(hint == col_lower or hint in col_lower for hint in filename_hints):
                # If we found a hint and best_ratio is low (or directory_files was empty),
                # this is our best guess.
                if best_ratio < 0.5:
                    logger.info(f"Using hint-based filename column: '{col}' (no directory matches found)")
                    return col, 0.0

        logger.info(f"Best filename column: '{best_column}' with {best_ratio:.2%} match ratio")
        return best_column, best_ratio

    def validate_msf_against_directory(
        self,
        df: pd.DataFrame,
        directory_files: List[str],
        filename_column: Optional[str] = None,
        directory_root: Optional[str] = None,
    ) -> MSFValidationResult:
        """
        Validate MSF data against directory files and identify matched/missing/unmapped files.

        Args:
            df: Parsed MSF DataFrame
            directory_files: List of filenames from the directory
            filename_column: Name of the column containing filenames (auto-detected if None)

        Returns:
            MSFValidationResult with validation details
        """
        result = MSFValidationResult(
            is_valid=True,
            filename_column="",
        )

        # Auto-detect filename column if not provided
        if not filename_column:
            detected_col, ratio = self.detect_filename_column(df, directory_files)
            if not detected_col:
                result.is_valid = False
                result.errors.append("Could not detect filename column in MSF")
                return result
            result.filename_detection_confidence = float(ratio or 0.0)
            if ratio < 0.3:
                result.warnings.append(
                    f"Low confidence in filename column detection: '{detected_col}' ({ratio:.0%} match)"
                )
            filename_column = detected_col
        else:
            result.filename_detection_confidence = 1.0

        if filename_column not in df.columns:
            result.is_valid = False
            result.errors.append(f"Filename column '{filename_column}' not found in MSF")
            return result

        result.filename_column = filename_column

        # Get filenames from MSF (skip header/description rows by checking for file extensions)
        msf_filenames = []
        for idx, val in enumerate(df[filename_column]):
            filename = str(val).strip()
            # Skip rows that don't look like filenames (e.g., description rows)
            if self._looks_like_filename(filename):
                msf_filenames.append((idx, filename))

        # Duplicate detection is mandatory for deterministic matching.
        # Matching by basename cannot be trusted if duplicates exist.
        msf_name_counts = Counter(fn.lower() for _, fn in msf_filenames)
        duplicate_msf_names = sorted([name for name, count in msf_name_counts.items() if count > 1])

        dir_name_counts = Counter(f.lower() for f in directory_files if f and f.strip())
        duplicate_dir_names = sorted([name for name, count in dir_name_counts.items() if count > 1])
        result.duplicate_msf_files = duplicate_msf_names
        result.duplicate_directory_files = duplicate_dir_names
        if duplicate_dir_names:
            result.duplicate_directory_details = self._build_directory_duplicate_details(directory_root)

        if duplicate_msf_names:
            result.is_valid = False
            preview = ", ".join(duplicate_msf_names[:10])
            suffix = " ..." if len(duplicate_msf_names) > 10 else ""
            result.errors.append(
                f"Duplicate filenames detected in MSF column '{filename_column}' (case-insensitive): "
                f"{preview}{suffix}. Please make filenames unique."
            )

        if duplicate_dir_names:
            result.is_valid = False
            preview = ", ".join(duplicate_dir_names[:10])
            suffix = " ..." if len(duplicate_dir_names) > 10 else ""
            result.errors.append(
                f"Duplicate filenames detected in scanned directory (case-insensitive): "
                f"{preview}{suffix}. Please ensure unique basenames."
            )

        if not result.is_valid:
            return result

        # Build lookup sets for comparison (case-insensitive)
        msf_files_lower = {fn.lower(): (idx, fn) for idx, fn in msf_filenames}
        dir_files_lower = {f.lower(): f for f in directory_files}

        # Find matches, missing, and unmapped
        for msf_lower, (idx, msf_original) in msf_files_lower.items():
            if msf_lower in dir_files_lower:
                result.matched_files.append(dir_files_lower[msf_lower])
            else:
                result.missing_files.append(msf_original)

        for dir_lower, dir_original in dir_files_lower.items():
            if dir_lower not in msf_files_lower:
                result.unmapped_files.append(dir_original)

        # If dependencies are referenced by matched files (OBJ/MTL/GLTF), treat them as included.
        implicit_files = self._find_implicitly_included_files(
            matched_files=result.matched_files,
            directory_files=directory_files,
            directory_root=directory_root,
        )
        if implicit_files:
            implicit_lower = {name.lower() for name in implicit_files}
            result.implicitly_included_files = sorted(implicit_files, key=lambda name: name.lower())
            result.unmapped_files = [
                name for name in result.unmapped_files if name.lower() not in implicit_lower
            ]

        # Add warnings/errors based on results
        if not result.matched_files:
            result.is_valid = False
            result.errors.append("No files matched between MSF and directory")

        if result.missing_files:
            result.warnings.append(
                f"{len(result.missing_files)} file(s) in MSF not found in directory"
            )

        if result.unmapped_files:
            result.warnings.append(
                f"{len(result.unmapped_files)} file(s) in directory not in MSF (will be excluded)"
            )

        if result.implicitly_included_files:
            result.warnings.append(
                f"{len(result.implicitly_included_files)} dependency file(s) are referenced by matched models and will be included"
            )

        logger.info(
            f"MSF Validation: {len(result.matched_files)} matched, "
            f"{len(result.missing_files)} missing, {len(result.unmapped_files)} unmapped, "
            f"{len(result.implicitly_included_files)} implicit dependencies"
        )
        return result

    def _find_implicitly_included_files(
        self,
        matched_files: List[str],
        directory_files: List[str],
        directory_root: Optional[str] = None,
    ) -> List[str]:
        """
        Find directory files that are not explicitly listed in MSF but should be treated
        as included because they are tightly coupled dependencies of matched files.
        """
        if not matched_files or not directory_files:
            return []

        directory_lookup = {
            filename.lower(): filename
            for filename in directory_files
            if isinstance(filename, str) and filename.strip()
        }
        matched_lower = {filename.lower() for filename in matched_files}
        implicit: Set[str] = set()

        # Include sibling files sharing the same stem as matched entries.
        stem_to_files: Dict[str, List[str]] = {}
        for filename in directory_files:
            if not isinstance(filename, str) or not filename.strip():
                continue
            stem = os.path.splitext(filename)[0].lower()
            stem_to_files.setdefault(stem, []).append(filename)

        candidate_obj_filenames: Set[str] = set()
        candidate_mtl_filenames: Set[str] = set()

        for matched in matched_files:
            if not isinstance(matched, str) or not matched.strip():
                continue
            stem = os.path.splitext(matched)[0].lower()
            siblings = stem_to_files.get(stem, [])
            for sibling in siblings:
                if sibling.lower() in matched_lower:
                    continue
                implicit.add(sibling)
                ext = os.path.splitext(sibling)[1].lower()
                if ext == ".obj":
                    candidate_obj_filenames.add(sibling)
                elif ext == ".mtl":
                    candidate_mtl_filenames.add(sibling)

            if os.path.splitext(matched)[1].lower() == ".obj":
                canonical_obj = directory_lookup.get(matched.lower(), matched)
                candidate_obj_filenames.add(canonical_obj)
            if os.path.splitext(matched)[1].lower() == ".mtl":
                canonical_mtl = directory_lookup.get(matched.lower(), matched)
                candidate_mtl_filenames.add(canonical_mtl)

        if not directory_root or not os.path.isdir(directory_root):
            return sorted(implicit, key=lambda name: name.lower())

        # Build a quick on-disk lookup by basename (validation already rejects duplicates).
        disk_paths_by_lower: Dict[str, str] = {}
        for root, _, files in os.walk(directory_root):
            for filename in files:
                lowered = filename.lower()
                if lowered not in disk_paths_by_lower:
                    disk_paths_by_lower[lowered] = os.path.join(root, filename)

        # Expand OBJ -> MTL references.
        for obj_name in list(candidate_obj_filenames):
            obj_path = disk_paths_by_lower.get(obj_name.lower())
            if not obj_path:
                continue
            for mtl_name in self._parse_obj_mtllib_names(obj_path):
                canonical_mtl = directory_lookup.get(mtl_name.lower())
                if canonical_mtl:
                    implicit.add(canonical_mtl)
                    candidate_mtl_filenames.add(canonical_mtl)

        # Expand MTL -> texture references.
        for mtl_name in candidate_mtl_filenames:
            mtl_path = disk_paths_by_lower.get(mtl_name.lower())
            if not mtl_path:
                continue
            for tex_name in self._parse_mtl_texture_names(mtl_path):
                canonical_tex = directory_lookup.get(tex_name.lower())
                if canonical_tex:
                    implicit.add(canonical_tex)

        return sorted(implicit, key=lambda name: name.lower())

    def _parse_obj_mtllib_names(self, obj_path: str) -> Set[str]:
        names: Set[str] = set()
        try:
            with open(obj_path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped.lower().startswith("mtllib"):
                        continue
                    parts = stripped.split(None, 1)
                    if len(parts) < 2:
                        continue
                    for token in parts[1].split():
                        names.add(os.path.basename(token.strip().strip('"').strip("'")))
        except Exception as exc:
            logger.debug(f"Failed to parse OBJ dependencies from {obj_path}: {exc}")
        return names

    def _parse_mtl_texture_names(self, mtl_path: str) -> Set[str]:
        names: Set[str] = set()
        texture_map_pattern = re.compile(r"^\s*(map_[a-zA-Z_]+|bump|refl)\s+(.*)")
        try:
            with open(mtl_path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    match = texture_map_pattern.match(line)
                    if not match:
                        continue
                    full_reference = match.group(2).strip()
                    if not full_reference:
                        continue
                    token = full_reference.split()[-1]
                    names.add(os.path.basename(token.strip().strip('"').strip("'")))
        except Exception as exc:
            logger.debug(f"Failed to parse MTL dependencies from {mtl_path}: {exc}")
        return names

    def get_metadata_for_file(
        self,
        df: pd.DataFrame,
        filename: str,
        filename_column: str,
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get Zenodo metadata for a specific file from the MSF DataFrame.

        Args:
            df: Parsed MSF DataFrame
            filename: The filename to get metadata for
            filename_column: Name of the column containing filenames
            column_mapping: Optional custom column mapping (uses defaults if None)

        Returns:
            Dictionary with Zenodo-compatible metadata, or None if file not found
        """
        mapping = column_mapping or self.default_mapping

        # Find the row for this file (case-insensitive)
        filename_lower = filename.lower()
        matching_rows = df[
            df[filename_column].apply(lambda x: str(x).strip().lower() == filename_lower)
        ]

        if matching_rows.empty:
            logger.warning(f"No MSF row found for file: {filename}")
            return None

        # Take the first matching row
        row = matching_rows.iloc[0]

        # Build metadata dictionary
        metadata = {}
        raw_data = {}

        # Build normalized lookup for provided mapping keys once.
        normalized_mapping: Dict[str, str] = {}
        for map_key, map_value in mapping.items():
            normalized_map_key = self._normalize_column_key(map_key)
            canonical = self.column_aliases.get(normalized_map_key, normalized_map_key).replace("_", " ")
            normalized_mapping[canonical] = map_value

        # Map columns to Zenodo fields
        for col in df.columns:
            col_lower = col.lower().strip()
            value = str(row[col]).strip() if pd.notna(row[col]) else ""

            if not value:
                continue

            # Check if this column has a mapping
            normalized_col = self._normalize_column_key(col)
            canonical_col = self.column_aliases.get(normalized_col, normalized_col).replace("_", " ")
            zenodo_key = normalized_mapping.get(canonical_col)

            if zenodo_key:
                raw_data[zenodo_key] = value
            else:
                # Store unmapped columns with underscore prefix
                raw_data[f"_unmapped_{col_lower}"] = value

        # Transform raw data into proper Zenodo format
        metadata = self._transform_to_zenodo_format(raw_data)

        return metadata

    def apply_lod_mapping(
        self,
        row: pd.Series,
        zenodo_record: Dict[str, Any],
        mapping_config: Dict[str, Any],
        include_defaults: bool = True,
    ) -> Dict[str, Any]:
        """
        Apply LOD-Mapper configuration to generate metadata.

        Args:
            row: pandas Series from MSF
            zenodo_record: Dictionary with Zenodo metadata
            mapping_config: Dictionary mapping target tags to sources
                {
                    "dc:title": {"source": "msf", "field": "Title"},
                    "dc:description": {"source": "zenodo", "field": "metadata.description"},
                    ...
                }
        """
        metadata = {}
        row_lookup: Dict[str, str] = {}
        for col in row.index:
            col_text = str(col)
            norm = self._normalize_column_key(col_text)
            canonical = self.column_aliases.get(norm, norm).replace("_", " ")
            row_lookup[col_text] = col_text
            row_lookup[col_text.lower()] = col_text
            row_lookup[norm] = col_text
            row_lookup[canonical] = col_text
            row_lookup[canonical.replace(" ", "_")] = col_text

        # Helper to get value from Zenodo record using dot notation or nested keys
        def get_zenodo_value(path: str):
            curr = zenodo_record
            for key in path.split('.'):
                if isinstance(curr, dict):
                    curr = curr.get(key)
                else:
                    return None
            return curr

        def resolve_row_field(field_name: Any) -> Optional[str]:
            if field_name in row.index:
                return str(field_name)
            normalized_field = self._normalize_column_key(field_name)
            canonical_field = self.column_aliases.get(normalized_field, normalized_field).replace("_", " ")
            return (
                row_lookup.get(field_name)
                or row_lookup.get(str(field_name).lower())
                or row_lookup.get(normalized_field)
                or row_lookup.get(canonical_field)
                or row_lookup.get(canonical_field.replace(" ", "_"))
            )

        def is_created_row_field(field_name: Any) -> bool:
            normalized_field = self._normalize_column_key(field_name)
            canonical_field = self.column_aliases.get(normalized_field, normalized_field)
            return canonical_field == "dcterms:created"

        # Mapping of Target Tags to metadata object keys used in EDM templates
        TAG_TO_KEY = {
            "dc:title": "title",
            "dc:description": "description",
            "dc:creator": "creators", # Expects list of {name, affiliation, orcid}
            "dc:publisher": "provider",
            "dcterms:created": "cho_created",
            "dc:subject": "keywords", # Expects list of strings
            "dc:language": "language",
            "dc:type": "resource_type",
            "edm:type": "edm_type_override", # We can use this to override edm:type
            "edm:country": "country",
            "edm:language": "language",
            "dcterms:spatial": "locations", # Expects list of {place, description, lat, lon}
            "dcterms:temporal": "temporal",
            "dcterms:medium": "medium",
            "dcterms:references": "references",
            "dcterms:isPartOf": "isPartOf",
            "edm:intendedUsage": "intended_usage",
            "schema:digitalSourceType": "digital_source_type",
            "edm:vertexCount": "vertex_count",
            "edm:polygonCount": "polygon_count",
            "edm:pointCount": "point_count",
            "dcterms:extent": "extent",
            "dc:format": "format",
            "edm:object": "thumbnail_path",
            "dc:identifier": "_external_identifier",
            "dc:source": "_source",
            # IIIF-focused mappings (3D profile)
            "label": "title",
            "summary": "description",
            "rights": "license",
            "provider": "provider",
            "iiif:manifestId": "iiif_manifest_id",
            "iiif:canvasId": "iiif_canvas_id",
            "iiif:canvasLabel": "iiif_canvas_label",
            "iiif:sceneId": "iiif_scene_id",
            "iiif:sceneLabel": "iiif_scene_label",
            "iiif:annotationPageId": "iiif_annotation_page_id",
            "iiif:annotationId": "iiif_annotation_id",
            "iiif:modelId": "iiif_model_id",
            "iiif:modelFormat": "iiif_model_format",
            "iiif:modelLabel": "iiif_model_label",
            "iiif:translateX": "iiif_translate_x",
            "iiif:translateY": "iiif_translate_y",
            "iiif:translateZ": "iiif_translate_z",
            "iiif:rotateX": "iiif_rotate_x",
            "iiif:rotateY": "iiif_rotate_y",
            "iiif:rotateZ": "iiif_rotate_z",
            "iiif:scaleX": "iiif_scale_x",
            "iiif:scaleY": "iiif_scale_y",
            "iiif:scaleZ": "iiif_scale_z",
            "iiif:pointX": "iiif_point_x",
            "iiif:pointY": "iiif_point_y",
            "iiif:pointZ": "iiif_point_z",
            # Legacy aliases kept for backward compatibility with older mappings.
            "iiif:latitude": "iiif_point_x",
            "iiif:longitude": "iiif_point_y",
            "iiif:altitude": "iiif_point_z",
            "iiif:heading": "iiif_heading",
            # Zenodo-focused mappings
            "zenodo:title": "title",
            "zenodo:description": "description",
            "zenodo:upload_type": "upload_type",
            "zenodo:publication_date": "publication_date",
            "zenodo:creators": "creators",
            "zenodo:access_right": "access_right",
            "zenodo:license": "license",
            "zenodo:communities": "communities",
            "zenodo:keywords": "keywords",
            "zenodo:notes": "notes",
            "zenodo:version": "version",
            "zenodo:language": "language",
            # Render thumbnail mapping controls
            "lod:thumbnailMode": "lod_thumbnail_mode",
            "lod:thumbnailPattern": "lod_thumbnail_pattern",
            "lod:thumbnailFiles": "lod_thumbnail_files",
        }

        derived_cho_created_value = None

        for tag, config in mapping_config.items():
            key = TAG_TO_KEY.get(tag, tag.split(':')[-1] if ':' in tag else tag)
            source = config.get("source")
            field = config.get("field")

            value = None
            resolved_field = None
            if source == "msf":
                resolved_field = resolve_row_field(field)
                if resolved_field is not None and resolved_field in row.index:
                    value = self._normalize_mapped_scalar(row.get(resolved_field, ""))
                else:
                    value = None
            elif source == "zenodo":
                value = get_zenodo_value(field)
            elif source == "options":
                value = config.get("value")
            elif source == "static":
                value = config.get("value")

            normalized_scalar_value = self._normalize_mapped_scalar(value)
            if (
                key == "publication_date"
                and source == "msf"
                and field is not None
                and is_created_row_field(field)
                and normalized_scalar_value
            ):
                derived_cho_created_value = normalized_scalar_value

            if value is not None:
                # Handle special fields that expect specific structures
                if key == "creators" and isinstance(value, str):
                    creators = self._parse_creators_value(value)
                    if creators:
                        metadata[key] = creators
                elif key == "keywords" and isinstance(value, str):
                    keywords = []
                    for raw_keyword in value.split(","):
                        normalized_keyword = self._normalize_mapped_scalar(raw_keyword)
                        if normalized_keyword:
                            keywords.append(normalized_keyword)
                    if keywords:
                        metadata[key] = keywords
                elif key == "communities" and isinstance(value, str):
                    communities = []
                    for raw_identifier in re.split(r"[;,]", value):
                        normalized_identifier = self._normalize_mapped_scalar(raw_identifier)
                        if normalized_identifier:
                            communities.append({"identifier": normalized_identifier})
                    if communities:
                        metadata[key] = communities
                elif key == "references" and isinstance(value, str):
                    references = []
                    for raw_ref in re.split(r"[;,]", value):
                        normalized_ref = self._normalize_mapped_scalar(raw_ref)
                        if normalized_ref:
                            references.append(normalized_ref)
                    if references:
                        metadata[key] = references
                elif key == "locations" and isinstance(value, str):
                    locations = []
                    for raw_place in value.split(","):
                        normalized_place = self._normalize_mapped_scalar(raw_place)
                        if normalized_place:
                            locations.append({"place": normalized_place})
                    if locations:
                        metadata[key] = locations
                elif key == "lod_thumbnail_files" and isinstance(value, str):
                    thumbnail_files = []
                    for raw_name in re.split(r"[;,]", value):
                        normalized_name = self._normalize_mapped_scalar(raw_name)
                        if normalized_name:
                            thumbnail_files.append(normalized_name)
                    if thumbnail_files:
                        metadata[key] = thumbnail_files
                else:
                    metadata[key] = value

        if derived_cho_created_value and not self._normalize_mapped_scalar(metadata.get("cho_created")):
            metadata["cho_created"] = derived_cho_created_value

        if include_defaults:
            # Fill in defaults for mandatory fields if missing
            title_value = self._normalize_mapped_scalar(metadata.get("title"))
            if not title_value:
                row_title = None
                resolved_title_field = resolve_row_field("title")
                if resolved_title_field and resolved_title_field in row.index:
                    row_title = self._normalize_mapped_scalar(row.get(resolved_title_field))

                row_filename = None
                resolved_filename_field = resolve_row_field("filename")
                if resolved_filename_field and resolved_filename_field in row.index:
                    row_filename = self._normalize_mapped_scalar(row.get(resolved_filename_field))

                fallback_title = row_title or row_filename or "Untitled record"
                metadata["title"] = fallback_title

            publication_date_value = self._normalize_mapped_scalar(metadata.get("publication_date"))
            if not publication_date_value:
                metadata["publication_date"] = datetime.now().strftime("%Y-%m-%d")

            creators_value = metadata.get("creators")
            has_valid_creators = False
            if isinstance(creators_value, list):
                for creator_entry in creators_value:
                    if isinstance(creator_entry, dict):
                        creator_name = self._normalize_mapped_scalar(creator_entry.get("name"))
                        if creator_name:
                            has_valid_creators = True
                            break
            if not has_valid_creators:
                metadata["creators"] = [{"name": "Unknown"}]

        return metadata

    def _transform_to_zenodo_format(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform raw MSF data into proper Zenodo metadata format.
        Handles special fields like creators, affiliations, dates, etc.
        """
        metadata = {}

        # Direct mappings
        if raw_data.get("title"):
            metadata["title"] = raw_data["title"]

        if raw_data.get("description"):
            metadata["description"] = raw_data["description"]

        # Handle publication_date
        if raw_data.get("publication_date"):
            date_str = raw_data["publication_date"]
            try:
                # Try to parse and format as YYYY-MM-DD
                if "-" in date_str:
                    parsed = datetime.strptime(date_str, "%Y-%m-%d")
                    metadata["publication_date"] = parsed.strftime("%Y-%m-%d")
                else:
                    # Fallback to current date
                    metadata["publication_date"] = datetime.now().strftime("%Y-%m-%d")
            except Exception:
                metadata["publication_date"] = datetime.now().strftime("%Y-%m-%d")
        else:
            metadata["publication_date"] = datetime.now().strftime("%Y-%m-%d")

        # Handle upload_type
        if raw_data.get("upload_type"):
            upload_type_raw = raw_data["upload_type"].lower().strip()
            metadata["upload_type"] = MSF_UPLOAD_TYPE_MAPPING.get(upload_type_raw, "dataset")
        else:
            metadata["upload_type"] = "dataset"

        # Handle creators and affiliations
        creators_raw = raw_data.get("_creators_raw", "")
        affiliations_raw = raw_data.get("_affiliations_raw", "")

        if raw_data.get("_external_identifier"):
            metadata["_external_identifier"] = raw_data["_external_identifier"]
        if affiliations_raw:
            metadata["_affiliations_raw"] = affiliations_raw

        if creators_raw:
            creator_names = [c.strip() for c in creators_raw.split(",") if c.strip()]
            affiliation_list = [a.strip() for a in affiliations_raw.split(",") if a.strip()] if affiliations_raw else []

            creators = []
            for i, name in enumerate(creator_names):
                creator = {"name": name}
                if i < len(affiliation_list):
                    creator["affiliation"] = affiliation_list[i]
                elif affiliation_list:
                    # Use last affiliation for remaining creators
                    creator["affiliation"] = affiliation_list[-1]
                creators.append(creator)

            metadata["creators"] = creators
        elif affiliations_raw:
            metadata["creators"] = [{"name": name} for name in [a.strip() for a in affiliations_raw.split(",") if a.strip()]]

        # Handle keywords
        if raw_data.get("keywords"):
            keywords = [k.strip() for k in raw_data["keywords"].split(",") if k.strip()]
            metadata["keywords"] = keywords

        # Default access right
        metadata["access_right"] = "open"
        metadata["license"] = "cc-by-4.0"

        # Pass through 3D specific fields if present
        for field in [
            "intended_usage",
            "digital_source_type",
            "model_type",
            "vertex_count",
            "polygon_count",
            "point_count",
            "extent",
        ]:
            if raw_data.get(field):
                metadata[field] = raw_data[field]

        return metadata

    def get_all_file_metadata(
        self,
        df: pd.DataFrame,
        matched_files: List[str],
        filename_column: str,
        column_mapping: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get metadata for all matched files.

        Args:
            df: Parsed MSF DataFrame
            matched_files: List of matched filenames
            filename_column: Name of the column containing filenames
            column_mapping: Optional custom column mapping

        Returns:
            Dictionary mapping filename -> Zenodo metadata
        """
        result = {}
        for filename in matched_files:
            metadata = self.get_metadata_for_file(df, filename, filename_column, column_mapping)
            if metadata:
                result[filename] = metadata
        return result

    def suggest_column_mapping(self, columns: List[str]) -> Dict[str, str]:
        """
        Suggest column-to-Zenodo mapping for a given MSF header set.

        Returns:
            Dict with source column name as key and target field key as value.
        """
        suggestions: Dict[str, str] = {}
        for col in columns:
            normalized = self._normalize_column_key(col)
            canonical = self.column_aliases.get(normalized, normalized).replace("_", " ")
            mapped = self.default_mapping.get(canonical)
            if mapped:
                suggestions[col] = mapped
        return suggestions

    def get_default_column_mapping(self) -> Dict[str, str]:
        """Return the default column mapping configuration"""
        return self.default_mapping.copy()

    def _normalize_filename_value(self, value: Any) -> str:
        """
        Normalize filename-like values to match basename-based directory scanning.

        Rules:
        - trim surrounding whitespace
        - normalize separators to forward slashes
        - collapse repeated slashes
        - strip leading './' and '/'
        - keep only basename
        """
        text = str(value or "").strip()
        if not text:
            return ""

        normalized = text.replace("\\", "/")
        normalized = re.sub(r"/+", "/", normalized)
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.lstrip("/")
        normalized = os.path.basename(normalized)
        return normalized.strip()

    def _write_patched_msf(
        self,
        df: pd.DataFrame,
        source_path: str,
        parse_options: Optional[Dict[str, Any]] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        """
        Persist a patched MSF to disk and return the created file path.
        """
        ext = os.path.splitext(source_path)[1].lower()
        base_name = os.path.splitext(os.path.basename(source_path))[0]
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        target_dir = output_dir or os.path.dirname(source_path) or "."
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, f"{base_name}.patched.{ts}{ext}")

        if ext == ".csv":
            delimiter = (
                (parse_options or {}).get("delimiter")
                or self.csv_delimiter
                or ","
            )
            df.to_csv(target_path, index=False, sep=str(delimiter))
        elif ext in {".xlsx", ".xls"}:
            sheet_name = str((parse_options or {}).get("sheet_name") or "Sheet1")
            df.to_excel(target_path, index=False, sheet_name=sheet_name)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

        return target_path

    def _normalize_duplicate_cell(self, value: Any, case_sensitive: bool = False) -> str:
        text = str(value or "").strip()
        return text if case_sensitive else text.lower()

    def _scan_duplicates_for_columns(
        self,
        df: pd.DataFrame,
        columns: List[str],
        case_sensitive: bool = False,
        max_groups_per_column: int = 200,
    ) -> Dict[str, Any]:
        by_column: Dict[str, Dict[str, Any]] = {}
        total_groups = 0
        total_rows = 0

        for column in columns:
            if column not in df.columns:
                by_column[column] = {
                    "error": f"Column '{column}' not found",
                    "duplicate_group_count": 0,
                    "duplicate_row_count": 0,
                    "groups": [],
                }
                continue

            key_to_indices: Dict[str, List[int]] = {}
            display_by_key: Dict[str, str] = {}
            for idx, raw_value in enumerate(df[column].tolist()):
                display_value = str(raw_value or "").strip()
                key = self._normalize_duplicate_cell(display_value, case_sensitive=case_sensitive)
                if not key:
                    continue
                key_to_indices.setdefault(key, []).append(idx)
                display_by_key.setdefault(key, display_value)

            duplicate_groups = {
                key: indices
                for key, indices in key_to_indices.items()
                if len(indices) > 1
            }

            groups_preview: List[Dict[str, Any]] = []
            for key, indices in list(duplicate_groups.items())[:max_groups_per_column]:
                groups_preview.append(
                    {
                        "value": display_by_key.get(key, key),
                        "count": len(indices),
                        "row_indices": [idx + 2 for idx in indices],
                    }
                )

            duplicate_group_count = len(duplicate_groups)
            duplicate_row_count = sum(len(indices) for indices in duplicate_groups.values())
            total_groups += duplicate_group_count
            total_rows += duplicate_row_count
            by_column[column] = {
                "duplicate_group_count": duplicate_group_count,
                "duplicate_row_count": duplicate_row_count,
                "groups": groups_preview,
                "truncated": duplicate_group_count > max_groups_per_column,
            }

        return {
            "columns": columns,
            "case_sensitive": case_sensitive,
            "total_duplicate_groups": total_groups,
            "total_duplicate_rows": total_rows,
            "by_column": by_column,
        }

    def _normalize_join_delimiter(self, delimiter: Any, auto_space: bool) -> str:
        raw = str(delimiter if delimiter is not None else "")
        if not auto_space:
            return raw
        stripped = raw.strip()
        if not stripped:
            return ""
        return f" {stripped} "

    def _apply_validator_operation(
        self,
        df: pd.DataFrame,
        operation: Dict[str, Any],
        detected_filename_col: Optional[str],
        directory_files: Optional[List[str]] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, Any], List[str], List[str]]:
        op_type = str(operation.get("type") or "").strip().lower()
        blockers: List[str] = []
        warnings: List[str] = []
        op_report: Dict[str, Any] = {"type": op_type, "status": "skipped"}

        if not op_type:
            blockers.append("Operation is missing 'type'")
            return df, op_report, blockers, warnings

        working_df = df.copy()

        if op_type == "resolve_duplicates":
            raw_columns = operation.get("columns") or []
            columns = [str(col).strip() for col in raw_columns if str(col or "").strip()]
            if not columns:
                blockers.append("resolve_duplicates requires at least one column")
                return df, op_report, blockers, warnings
            missing = [col for col in columns if col not in working_df.columns]
            if missing:
                blockers.append(f"resolve_duplicates columns not found: {missing}")
                return df, op_report, blockers, warnings

            strategy = str(operation.get("strategy") or "keep_first").strip().lower()
            case_sensitive = bool(operation.get("case_sensitive", False))
            ignore_empty = True if "ignore_empty" not in operation else bool(operation.get("ignore_empty"))
            normalize_as_filename = bool(operation.get("normalize_as_filename"))
            key_to_indices: Dict[Tuple[str, ...], List[int]] = {}
            key_display: Dict[Tuple[str, ...], Dict[str, str]] = {}
            for idx in range(len(working_df)):
                values = [str(working_df.at[idx, col] if pd.notna(working_df.at[idx, col]) else "").strip() for col in columns]
                if ignore_empty and all(not value for value in values):
                    continue
                key = tuple(
                    self._normalize_filename_value(value).lower()
                    if normalize_as_filename and col == detected_filename_col
                    else self._normalize_duplicate_cell(value, case_sensitive=case_sensitive)
                    for col, value in zip(columns, values)
                )
                key_to_indices.setdefault(key, []).append(idx)
                key_display.setdefault(key, {col: values[pos] for pos, col in enumerate(columns)})

            duplicate_groups = {
                key: indices for key, indices in key_to_indices.items() if len(indices) > 1
            }
            groups_detected = len(duplicate_groups)
            rows_affected = 0
            rows_removed = 0
            rows_merged = 0

            if groups_detected == 0:
                op_report = {
                    "type": op_type,
                    "status": "ok",
                    "strategy": strategy,
                    "columns": columns,
                    "groups_detected": 0,
                    "rows_affected": 0,
                    "rows_removed": 0,
                    "rows_merged": 0,
                    "message": "No duplicates found for selected columns.",
                }
                return working_df, op_report, blockers, warnings

            if strategy == "keep_first":
                rows_to_drop: List[int] = []
                for indices in duplicate_groups.values():
                    rows_to_drop.extend(indices[1:])
                rows_to_drop = sorted(set(rows_to_drop))
                rows_removed = len(rows_to_drop)
                if rows_to_drop:
                    working_df = working_df.drop(index=rows_to_drop).reset_index(drop=True)
                rows_affected = rows_removed
            elif strategy == "keep_last":
                rows_to_drop = []
                for indices in duplicate_groups.values():
                    rows_to_drop.extend(indices[:-1])
                rows_to_drop = sorted(set(rows_to_drop))
                rows_removed = len(rows_to_drop)
                if rows_to_drop:
                    working_df = working_df.drop(index=rows_to_drop).reset_index(drop=True)
                rows_affected = rows_removed
            elif strategy == "merge_non_empty":
                rows_to_drop = []
                for indices in duplicate_groups.values():
                    base_idx = indices[0]
                    for idx in indices[1:]:
                        for col in working_df.columns:
                            base_val = str(
                                working_df.at[base_idx, col]
                                if pd.notna(working_df.at[base_idx, col])
                                else ""
                            ).strip()
                            other_val = str(
                                working_df.at[idx, col]
                                if pd.notna(working_df.at[idx, col])
                                else ""
                            ).strip()
                            if not base_val and other_val:
                                working_df.at[base_idx, col] = other_val
                                rows_affected += 1
                        rows_to_drop.append(idx)

                rows_to_drop = sorted(set(rows_to_drop))
                rows_merged = len(rows_to_drop)
                rows_removed = rows_merged
                if rows_to_drop:
                    working_df = working_df.drop(index=rows_to_drop).reset_index(drop=True)
            elif strategy == "suffix_with_filename":
                target_column = str(operation.get("target_column") or columns[0]).strip()
                filename_column = str(operation.get("filename_column") or detected_filename_col or "").strip()
                if target_column not in working_df.columns:
                    blockers.append(f"suffix_with_filename target column not found: '{target_column}'")
                    return df, op_report, blockers, warnings
                if not filename_column or filename_column not in working_df.columns:
                    blockers.append(
                        "suffix_with_filename requires a valid filename_column "
                        "(explicit or auto-detected)"
                    )
                    return df, op_report, blockers, warnings

                delimiter = self._normalize_join_delimiter(
                    operation.get("delimiter", "—"),
                    bool(operation.get("auto_space", True)),
                )
                also_update_first = bool(operation.get("also_update_first", False))
                for indices in duplicate_groups.values():
                    for position, idx in enumerate(indices):
                        if position == 0 and not also_update_first:
                            continue
                        current_value = str(
                            working_df.at[idx, target_column]
                            if pd.notna(working_df.at[idx, target_column])
                            else ""
                        ).strip()
                        suffix_source = str(
                            working_df.at[idx, filename_column]
                            if pd.notna(working_df.at[idx, filename_column])
                            else ""
                        ).strip() or f"row_{idx + 2}"

                        merged_value = (
                            f"{current_value}{delimiter}{suffix_source}"
                            if current_value
                            else suffix_source
                        )
                        if merged_value != current_value:
                            working_df.at[idx, target_column] = merged_value
                            rows_affected += 1
                if rows_affected == 0:
                    warnings.append(
                        "suffix_with_filename found duplicate groups but made no data changes."
                    )
            else:
                blockers.append(
                    "Unsupported resolve_duplicates strategy "
                    f"'{strategy}'. Allowed: keep_first, keep_last, merge_non_empty, suffix_with_filename"
                )
                return df, op_report, blockers, warnings

            op_report = {
                "type": op_type,
                "status": "ok",
                "strategy": strategy,
                "columns": columns,
                "groups_detected": groups_detected,
                "rows_affected": int(rows_affected),
                "rows_removed": int(rows_removed),
                "rows_merged": int(rows_merged),
                "group_preview": [
                    {
                        "key": key_display.get(key, {}),
                        "count": len(indices),
                        "row_indices": [idx + 2 for idx in indices],
                    }
                    for key, indices in list(duplicate_groups.items())[:25]
                ],
                "group_preview_truncated": groups_detected > 25,
            }
            return working_df, op_report, blockers, warnings

        if op_type == "merge_columns":
            target_column = str(operation.get("target_column") or "").strip()
            source_columns = [
                str(col).strip()
                for col in (operation.get("source_columns") or [])
                if str(col or "").strip()
            ]
            if not target_column:
                blockers.append("merge_columns requires target_column")
                return df, op_report, blockers, warnings
            if not source_columns:
                blockers.append("merge_columns requires source_columns")
                return df, op_report, blockers, warnings
            missing = [col for col in source_columns if col not in working_df.columns]
            if missing:
                blockers.append(f"merge_columns source columns not found: {missing}")
                return df, op_report, blockers, warnings

            if target_column not in working_df.columns:
                working_df[target_column] = ""

            delimiter = self._normalize_join_delimiter(
                operation.get("delimiter", "—"),
                bool(operation.get("auto_space", True)),
            )
            skip_empty = True if "skip_empty" not in operation else bool(operation.get("skip_empty"))
            overwrite = bool(operation.get("overwrite", False))
            updated_rows = 0

            for idx in range(len(working_df)):
                parts: List[str] = []
                for col in source_columns:
                    value = str(
                        working_df.at[idx, col]
                        if pd.notna(working_df.at[idx, col])
                        else ""
                    ).strip()
                    if skip_empty and not value:
                        continue
                    parts.append(value)

                if not parts:
                    continue

                merged_value = delimiter.join(parts) if delimiter else "".join(parts)
                current_value = str(
                    working_df.at[idx, target_column]
                    if pd.notna(working_df.at[idx, target_column])
                    else ""
                ).strip()
                if overwrite or not current_value:
                    if merged_value != current_value:
                        working_df.at[idx, target_column] = merged_value
                        updated_rows += 1

            op_report = {
                "type": op_type,
                "status": "ok",
                "target_column": target_column,
                "source_columns": source_columns,
                "delimiter": delimiter,
                "overwrite": overwrite,
                "skip_empty": skip_empty,
                "updated_rows": int(updated_rows),
            }
            return working_df, op_report, blockers, warnings

        if op_type == "normalize_filename_column":
            column = str(operation.get("column") or detected_filename_col or "").strip()
            if not column:
                blockers.append("normalize_filename_column requires a column or detected filename column")
                return df, op_report, blockers, warnings
            if column not in working_df.columns:
                blockers.append(f"normalize_filename_column column not found: '{column}'")
                return df, op_report, blockers, warnings

            normalized_count = 0
            normalized_values: List[str] = []
            for value in working_df[column].tolist():
                normalized = self._normalize_filename_value(value)
                normalized_values.append(normalized)
                if str(value or "").strip() != normalized:
                    normalized_count += 1
            working_df[column] = normalized_values

            op_report = {
                "type": op_type,
                "status": "ok",
                "column": column,
                "normalized_cells": int(normalized_count),
            }
            return working_df, op_report, blockers, warnings

        if op_type == "repair_references":
            column = str(operation.get("column") or detected_filename_col or "").strip()
            if not column:
                blockers.append("repair_references requires a column or detected filename column")
                return df, op_report, blockers, warnings
            if column not in working_df.columns:
                blockers.append(f"repair_references column not found: '{column}'")
                return df, op_report, blockers, warnings

            available_files = [str(item).strip() for item in (directory_files or []) if str(item or "").strip()]
            if not available_files:
                blockers.append("repair_references requires scanned directory files")
                return df, op_report, blockers, warnings

            match_by_stem = True if "match_by_stem" not in operation else bool(operation.get("match_by_stem"))
            keep_unresolved = True if "keep_unresolved" not in operation else bool(operation.get("keep_unresolved"))
            fuzzy_match = True if "fuzzy_match" not in operation else bool(operation.get("fuzzy_match"))
            min_similarity = float(operation.get("min_similarity", 0.9))
            min_margin = float(operation.get("min_margin", 0.05))
            enforce_unique_matches = (
                True if "enforce_unique_matches" not in operation else bool(operation.get("enforce_unique_matches"))
            )

            basename_lookup: Dict[str, List[str]] = {}
            for name in available_files:
                basename_lookup.setdefault(name.lower(), []).append(name)

            duplicate_directory_names = sorted(
                [name for name, values in basename_lookup.items() if len(values) > 1]
            )
            if duplicate_directory_names:
                warnings.append(
                    "repair_references detected duplicate basenames in directory scan; first match is used."
                )

            repair_report = self._repair_filename_reference_values(
                working_df[column].tolist(),
                available_files,
                match_by_stem=match_by_stem,
                fuzzy_match=fuzzy_match,
                min_similarity=min_similarity,
                min_margin=min_margin,
                enforce_unique_matches=enforce_unique_matches,
            )
            working_df[column] = repair_report["values"]
            if not keep_unresolved:
                for idx in repair_report.get("unresolved_row_indices") or []:
                    if 0 <= idx < len(working_df):
                        working_df.at[idx, column] = ""

            op_report = {
                "type": op_type,
                "status": "ok",
                "column": column,
                "match_by_stem": match_by_stem,
                "fuzzy_match": fuzzy_match,
                "min_similarity": min_similarity,
                "min_margin": min_margin,
                "enforce_unique_matches": enforce_unique_matches,
                "keep_unresolved": keep_unresolved,
                "changed_cells": int(repair_report.get("changed_cells") or 0),
                "strategy_counts": repair_report.get("strategy_counts") or {},
                "unresolved_count": int(repair_report.get("unresolved_count") or 0),
                "unresolved_preview": repair_report.get("unresolved_preview") or [],
                "unresolved_preview_truncated": int(repair_report.get("unresolved_count") or 0) > len(repair_report.get("unresolved_preview") or []),
            }
            return working_df, op_report, blockers, warnings

        if op_type == "normalize_text_columns":
            raw_columns = operation.get("columns") or []
            columns = [str(col).strip() for col in raw_columns if str(col or "").strip()]
            if not columns:
                blockers.append("normalize_text_columns requires at least one column")
                return df, op_report, blockers, warnings

            missing = [col for col in columns if col not in working_df.columns]
            if missing:
                warnings.append(f"normalize_text_columns ignored missing columns: {missing}")
                columns = [col for col in columns if col in working_df.columns]
            if not columns:
                blockers.append("normalize_text_columns has no valid columns after filtering")
                return df, op_report, blockers, warnings

            mode = str(operation.get("mode") or "none").strip().lower()
            if mode not in {"none", "lower", "upper", "title", "sentence"}:
                blockers.append(
                    "normalize_text_columns mode must be one of: none, lower, upper, title, sentence"
                )
                return df, op_report, blockers, warnings

            collapse_whitespace = True if "collapse_whitespace" not in operation else bool(
                operation.get("collapse_whitespace")
            )
            dedupe_delimited = bool(operation.get("dedupe_delimited", False))
            delimiter_raw = operation.get("delimiter", ";")
            delimiter = str(delimiter_raw if delimiter_raw is not None else "")
            auto_space = bool(operation.get("auto_space", True))
            join_delimiter = self._normalize_join_delimiter(delimiter, auto_space)

            changed_cells = 0
            deduped_cells = 0
            for col in columns:
                new_values: List[str] = []
                for value in working_df[col].tolist():
                    text = str(value if value is not None else "")
                    original = text

                    if collapse_whitespace:
                        text = " ".join(text.split())

                    if mode == "lower":
                        text = text.lower()
                    elif mode == "upper":
                        text = text.upper()
                    elif mode == "title":
                        text = text.title()
                    elif mode == "sentence":
                        stripped = text.strip()
                        text = (
                            f"{stripped[0].upper()}{stripped[1:].lower()}"
                            if stripped
                            else stripped
                        )

                    if dedupe_delimited and delimiter:
                        parts = [item.strip() for item in text.split(delimiter)]
                        unique_parts: List[str] = []
                        seen: Set[str] = set()
                        for item in parts:
                            if not item:
                                continue
                            key = item.lower()
                            if key in seen:
                                continue
                            seen.add(key)
                            unique_parts.append(item)
                        deduped_text = (
                            (join_delimiter if join_delimiter else delimiter).join(unique_parts)
                            if unique_parts
                            else ""
                        )
                        if deduped_text != text:
                            deduped_cells += 1
                        text = deduped_text

                    if text != original:
                        changed_cells += 1
                    new_values.append(text)

                working_df[col] = new_values

            op_report = {
                "type": op_type,
                "status": "ok",
                "columns": columns,
                "mode": mode,
                "collapse_whitespace": collapse_whitespace,
                "dedupe_delimited": dedupe_delimited,
                "delimiter": delimiter,
                "changed_cells": int(changed_cells),
                "deduped_cells": int(deduped_cells),
            }
            return working_df, op_report, blockers, warnings

        if op_type == "trim_whitespace":
            raw_columns = operation.get("columns") or list(working_df.columns)
            columns = [str(col).strip() for col in raw_columns if str(col or "").strip()]
            if not columns:
                warnings.append("trim_whitespace skipped because no columns were provided.")
                return working_df, {"type": op_type, "status": "skipped"}, blockers, warnings

            missing = [col for col in columns if col not in working_df.columns]
            if missing:
                warnings.append(f"trim_whitespace ignored missing columns: {missing}")
                columns = [col for col in columns if col in working_df.columns]
            changed_cells = 0
            for col in columns:
                new_values: List[str] = []
                for value in working_df[col].tolist():
                    text = str(value if value is not None else "")
                    trimmed = text.strip()
                    if text != trimmed:
                        changed_cells += 1
                    new_values.append(trimmed)
                working_df[col] = new_values

            op_report = {
                "type": op_type,
                "status": "ok",
                "columns": columns,
                "changed_cells": int(changed_cells),
            }
            return working_df, op_report, blockers, warnings

        if op_type == "remove_empty_rows":
            before = len(working_df)
            keep_mask = working_df.apply(
                lambda row: any(str(value or "").strip() for value in row.tolist()),
                axis=1,
            )
            working_df = working_df[keep_mask].reset_index(drop=True)
            removed = before - len(working_df)
            op_report = {
                "type": op_type,
                "status": "ok",
                "removed_rows": int(removed),
            }
            return working_df, op_report, blockers, warnings

        blockers.append(f"Unsupported operation type '{op_type}'")
        return df, op_report, blockers, warnings

    def run_local_validator(
        self,
        file_path: str,
        parse_options: Optional[Dict[str, Any]] = None,
        directory_files: Optional[List[str]] = None,
        directory_root: Optional[str] = None,
        filename_column: Optional[str] = None,
        duplicate_scan_columns: Optional[List[str]] = None,
        operations: Optional[List[Dict[str, Any]]] = None,
        include_reference_check: bool = True,
        include_dataframe: bool = False,
    ) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            raise ValueError(f"MSF file not found: {file_path}")

        normalized_parse_options = self._normalize_parse_options(parse_options)
        original_df, profile = self.parse_msf_file_with_profile(
            file_path,
            parse_options=normalized_parse_options,
        )
        working_df = original_df.copy()
        scanned_files = list(directory_files or [])
        blockers: List[str] = []
        warnings: List[str] = []
        actions: List[str] = []
        operations_report: List[Dict[str, Any]] = []

        detected_filename_col = str(filename_column or "").strip() or None
        if not detected_filename_col:
            detected_filename_col, detected_conf = self.detect_filename_column(working_df, scanned_files)
            if detected_filename_col and detected_conf < 0.3:
                warnings.append(
                    f"Low confidence in filename column detection: '{detected_filename_col}' ({detected_conf:.0%} match)"
                )
        if detected_filename_col and detected_filename_col not in working_df.columns:
            blockers.append(f"Filename column '{detected_filename_col}' not found in MSF")

        scan_columns_raw = duplicate_scan_columns or []
        if not scan_columns_raw and detected_filename_col:
            scan_columns_raw = [detected_filename_col]

        scan_columns = []
        for col in scan_columns_raw:
            col_name = str(col or "").strip()
            if not col_name:
                continue
            if col_name not in working_df.columns:
                warnings.append(f"Duplicate scan skipped missing column '{col_name}'")
                continue
            scan_columns.append(col_name)

        pre_duplicate_scan = self._scan_duplicates_for_columns(
            working_df, scan_columns, case_sensitive=False
        ) if scan_columns else {
            "columns": [],
            "case_sensitive": False,
            "total_duplicate_groups": 0,
            "total_duplicate_rows": 0,
            "by_column": {},
        }

        def _build_operation_action(op_report: Dict[str, Any], operation_index: int) -> str:
            op_type = str(op_report.get("type") or "").strip()
            prefix = f"Operation #{operation_index}"
            if op_type == "resolve_duplicates":
                strategy = str(op_report.get("strategy") or "unknown")
                groups = int(op_report.get("groups_detected") or 0)
                rows_removed = int(op_report.get("rows_removed") or 0)
                rows_merged = int(op_report.get("rows_merged") or 0)
                rows_affected = int(op_report.get("rows_affected") or 0)
                return (
                    f"{prefix} (resolve_duplicates): strategy='{strategy}', "
                    f"groups={groups}, rows_removed={rows_removed}, "
                    f"rows_merged={rows_merged}, cell_updates={rows_affected}."
                )
            if op_type == "merge_columns":
                target_column = str(op_report.get("target_column") or "")
                source_columns = op_report.get("source_columns") or []
                updated_rows = int(op_report.get("updated_rows") or 0)
                return (
                    f"{prefix} (merge_columns): merged {source_columns} into "
                    f"'{target_column}', updated_rows={updated_rows}."
                )
            return f"{prefix} ({op_type}) applied."

        if operations:
            for idx, operation in enumerate(operations):
                if not isinstance(operation, dict):
                    blockers.append(f"Operation #{idx + 1} is not an object")
                    continue
                updated_df, op_report, op_blockers, op_warnings = self._apply_validator_operation(
                    working_df,
                    operation,
                    detected_filename_col,
                    scanned_files,
                )
                if op_blockers:
                    blockers.extend([f"Operation #{idx + 1}: {item}" for item in op_blockers])
                if op_warnings:
                    warnings.extend([f"Operation #{idx + 1}: {item}" for item in op_warnings])
                operations_report.append(op_report)
                if not op_blockers:
                    working_df = updated_df
                    if op_report.get("status") == "ok":
                        actions.append(_build_operation_action(op_report, idx + 1))

        post_duplicate_scan = self._scan_duplicates_for_columns(
            working_df, scan_columns, case_sensitive=False
        ) if scan_columns else pre_duplicate_scan

        reference_check = None
        if include_reference_check and scanned_files and detected_filename_col and not blockers:
            validation_result = self.validate_msf_against_directory(
                working_df,
                scanned_files,
                filename_column=detected_filename_col,
                directory_root=directory_root,
            )
            reference_check = validation_result.to_dict()
            if validation_result.errors:
                blockers.extend([f"Reference check: {msg}" for msg in validation_result.errors])
            if validation_result.warnings:
                warnings.extend(validation_result.warnings)
        elif include_reference_check and not scanned_files:
            warnings.append("Reference check skipped because no directory files were provided.")

        summary = {
            "rows_original": int(len(original_df)),
            "rows_after_operations": int(len(working_df)),
            "columns": list(working_df.columns),
            "filename_column": detected_filename_col,
            "operations_applied": int(
                sum(1 for item in operations_report if item.get("status") == "ok")
            ),
        }

        result: Dict[str, Any] = {
            "is_valid": len(blockers) == 0,
            "msf_path": file_path,
            "parse_options": profile.get("parse_options", {}),
            "available_sheets": profile.get("available_sheets", []),
            "sheet_name": profile.get("sheet_name"),
            "header_row_index": profile.get("header_row_index"),
            "filename_column": detected_filename_col,
            "scan_directory_root": directory_root,
            "scan_file_count": len(scanned_files),
            "checks": {
                "reference_availability": reference_check,
                "duplicates_before_operations": pre_duplicate_scan,
                "duplicates_after_operations": post_duplicate_scan,
            },
            "operations": operations_report,
            "actions": actions,
            "warnings": warnings,
            "blockers": blockers,
            "summary": summary,
            "preview": self.get_msf_preview(working_df, max_rows=10),
            "supported_export_formats": ["csv", "xlsx"],
        }

        if include_dataframe:
            result["_dataframe"] = working_df
            result["_export_parse_options"] = profile.get("parse_options", {})

        return result

    def write_dataframe_export(
        self,
        df: pd.DataFrame,
        source_path: str,
        file_format: str,
        parse_options: Optional[Dict[str, Any]] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        export_format = str(file_format or "").strip().lower()
        if export_format not in {"csv", "xlsx"}:
            raise ValueError("Unsupported export format. Allowed: ['csv', 'xlsx']")

        base_name = os.path.splitext(os.path.basename(source_path))[0]
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        target_dir = output_dir or os.path.dirname(source_path) or "."
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, f"{base_name}.validator.{ts}.{export_format}")

        export_df = df.copy().fillna("")
        if export_format == "csv":
            delimiter = (parse_options or {}).get("delimiter") or self.csv_delimiter or ","
            export_df.to_csv(target_path, index=False, sep=str(delimiter))
        else:
            sheet_name = str((parse_options or {}).get("sheet_name") or "Sheet1").strip() or "Sheet1"
            export_df.to_excel(target_path, index=False, sheet_name=sheet_name[:31])

        return target_path

    def patch_msf_file(
        self,
        file_path: str,
        parse_options: Optional[Dict[str, Any]] = None,
        directory_files: Optional[List[str]] = None,
        directory_root: Optional[str] = None,
        filename_column: Optional[str] = None,
        duplicate_policy: str = "fail",
        apply: bool = False,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze and optionally patch an MSF file.

        duplicate_policy:
        - fail: report duplicate filename rows as blockers
        - keep_first: keep first row per filename, drop following duplicates
        - merge_non_empty: merge duplicate rows by filling empty cells from later rows
        """
        if not os.path.exists(file_path):
            raise ValueError(f"MSF file not found: {file_path}")

        allowed_duplicate_policies = {"fail", "keep_first", "merge_non_empty"}
        policy = str(duplicate_policy or "fail").strip().lower()
        if policy not in allowed_duplicate_policies:
            raise ValueError(
                f"Unsupported duplicate_policy '{duplicate_policy}'. "
                f"Allowed: {sorted(allowed_duplicate_policies)}"
            )

        ext = os.path.splitext(file_path)[1].lower()
        normalized_parse_options = self._normalize_parse_options(parse_options)
        original_df, profile = self.parse_msf_file_with_profile(
            file_path,
            parse_options=normalized_parse_options,
        )
        working_df = original_df.copy()
        scanned_files = list(directory_files or [])

        blockers: List[str] = []
        warnings: List[str] = []
        actions: List[str] = []

        detected_filename_col = filename_column
        if not detected_filename_col:
            detected_filename_col, detected_conf = self.detect_filename_column(working_df, scanned_files)
            if not detected_filename_col:
                blockers.append("Could not detect filename column in MSF")
            elif detected_conf < 0.3:
                warnings.append(
                    f"Low confidence in filename column detection: '{detected_filename_col}' ({detected_conf:.0%} match)"
                )

            # Fallback for headerless CSVs that were parsed with the first data row as header.
            # Signal: detected column name itself looks like a filename.
            if (
                ext == ".csv"
                and normalized_parse_options.get("use_first_row_as_header") is None
                and detected_filename_col
                and self._looks_like_filename(detected_filename_col)
            ):
                fallback_options = dict(normalized_parse_options)
                fallback_options["use_first_row_as_header"] = False
                fallback_df, fallback_profile = self.parse_msf_file_with_profile(
                    file_path,
                    parse_options=fallback_options,
                )
                fallback_col, fallback_conf = self.detect_filename_column(fallback_df, scanned_files)

                def _count_filename_rows(df: pd.DataFrame, column_name: Optional[str]) -> int:
                    if not column_name or column_name not in df.columns:
                        return 0
                    return sum(
                        1
                        for value in df[column_name].tolist()
                        if self._looks_like_filename(str(value or "").strip())
                    )

                current_count = _count_filename_rows(working_df, detected_filename_col)
                fallback_count = _count_filename_rows(fallback_df, fallback_col)
                if fallback_col and (
                    not self._looks_like_filename(fallback_col)
                    or fallback_count > current_count
                ):
                    working_df = fallback_df.copy()
                    profile = fallback_profile
                    detected_filename_col = fallback_col
                    actions.append(
                        "Re-parsed CSV as headerless based on filename-like header detection."
                    )
                    if fallback_conf < 0.3:
                        warnings.append(
                            f"Low confidence in filename column detection: '{fallback_col}' ({fallback_conf:.0%} match)"
                        )

        if detected_filename_col and detected_filename_col not in working_df.columns:
            blockers.append(f"Filename column '{detected_filename_col}' not found in MSF")

        filename_cells_normalized = 0
        embedded_header_rows_removed = 0
        filename_reference_repairs = 0
        unresolved_reference_count = 0
        duplicate_groups_count = 0
        duplicate_rows_removed = 0
        duplicate_rows_merged = 0
        filename_like_rows = 0

        if not blockers and detected_filename_col:
            normalized_values: List[str] = []
            for value in working_df[detected_filename_col].tolist():
                normalized = self._normalize_filename_value(value)
                normalized_values.append(normalized)
                if str(value or "").strip() != normalized:
                    filename_cells_normalized += 1
            working_df[detected_filename_col] = normalized_values

            if filename_cells_normalized:
                actions.append(
                    f"Normalized {filename_cells_normalized} filename cell(s) in '{detected_filename_col}'."
                )

            header_row_indices = [
                idx
                for idx in range(len(working_df))
                if self._looks_like_embedded_header_row(
                    working_df.iloc[idx].tolist(),
                    list(working_df.columns),
                    detected_filename_col,
                )
            ]
            if header_row_indices:
                embedded_header_rows_removed = len(header_row_indices)
                working_df = working_df.drop(index=header_row_indices).reset_index(drop=True)
                actions.append(
                    f"Removed {embedded_header_rows_removed} embedded header row(s) from the MSF body."
                )

            if scanned_files:
                repair_report = self._repair_filename_reference_values(
                    working_df[detected_filename_col].tolist(),
                    scanned_files,
                    match_by_stem=True,
                    fuzzy_match=True,
                    min_similarity=0.9,
                    min_margin=0.05,
                    enforce_unique_matches=True,
                )
                if repair_report["changed_cells"]:
                    working_df[detected_filename_col] = repair_report["values"]
                    filename_reference_repairs = int(repair_report["changed_cells"])
                    strategy_counts = repair_report.get("strategy_counts") or {}
                    strategy_summary = ", ".join(
                        f"{key}={value}"
                        for key, value in sorted(strategy_counts.items(), key=lambda item: item[0])
                    )
                    suffix = f" ({strategy_summary})" if strategy_summary else ""
                    actions.append(
                        f"Repaired {filename_reference_repairs} filename reference(s) against scanned files{suffix}."
                    )
                unresolved_reference_count = int(repair_report.get("unresolved_count") or 0)
                if unresolved_reference_count:
                    warnings.append(
                        f"{unresolved_reference_count} filename reference(s) still could not be mapped to scanned files."
                    )

            filename_to_rows: Dict[str, List[int]] = {}
            for idx, value in enumerate(working_df[detected_filename_col].tolist()):
                filename = str(value or "").strip()
                if not self._looks_like_filename(filename):
                    continue
                filename_like_rows += 1
                filename_to_rows.setdefault(filename.lower(), []).append(idx)

            duplicate_groups = {
                filename: indices
                for filename, indices in filename_to_rows.items()
                if len(indices) > 1
            }
            duplicate_groups_count = len(duplicate_groups)

            if duplicate_groups:
                if policy == "fail":
                    preview = ", ".join(list(duplicate_groups.keys())[:10])
                    suffix = " ..." if len(duplicate_groups) > 10 else ""
                    blockers.append(
                        "Duplicate filenames remain in MSF after normalization: "
                        f"{preview}{suffix}. Use duplicate_policy='keep_first' or 'merge_non_empty'."
                    )
                elif policy == "keep_first":
                    rows_to_drop: List[int] = []
                    for indices in duplicate_groups.values():
                        rows_to_drop.extend(indices[1:])
                    rows_to_drop = sorted(set(rows_to_drop))
                    duplicate_rows_removed = len(rows_to_drop)
                    if rows_to_drop:
                        working_df = working_df.drop(index=rows_to_drop).reset_index(drop=True)
                        actions.append(
                            f"Removed {duplicate_rows_removed} duplicate row(s) using keep_first policy."
                        )
                elif policy == "merge_non_empty":
                    rows_to_drop: List[int] = []
                    for indices in duplicate_groups.values():
                        base_idx = indices[0]
                        for idx in indices[1:]:
                            for col in working_df.columns:
                                base_val = str(working_df.at[base_idx, col] if pd.notna(working_df.at[base_idx, col]) else "").strip()
                                other_val = str(working_df.at[idx, col] if pd.notna(working_df.at[idx, col]) else "").strip()
                                if not base_val and other_val:
                                    working_df.at[base_idx, col] = other_val
                            rows_to_drop.append(idx)

                    rows_to_drop = sorted(set(rows_to_drop))
                    duplicate_rows_merged = len(rows_to_drop)
                    if rows_to_drop:
                        working_df = working_df.drop(index=rows_to_drop).reset_index(drop=True)
                        actions.append(
                            f"Merged and removed {duplicate_rows_merged} duplicate row(s) using merge_non_empty policy."
                        )

        validation_payload: Optional[Dict[str, Any]] = None
        if not blockers and detected_filename_col and scanned_files:
            validation_result = self.validate_msf_against_directory(
                working_df,
                scanned_files,
                filename_column=detected_filename_col,
                directory_root=directory_root,
            )
            validation_payload = validation_result.to_dict()
            if not validation_result.is_valid:
                blockers.extend(validation_result.errors or [])
            warnings.extend(validation_result.warnings or [])

        patched_msf_path = None
        if apply:
            if blockers:
                warnings.append("Patch application skipped because blockers remain.")
            else:
                patch_parse_options = dict(profile.get("parse_options") or {})
                if detected_filename_col:
                    profile["filename_column"] = detected_filename_col
                patched_msf_path = self._write_patched_msf(
                    working_df,
                    file_path,
                    parse_options=patch_parse_options,
                    output_dir=output_dir,
                )
                actions.append(f"Wrote patched MSF to {patched_msf_path}.")

        summary = {
            "rows_original": int(len(original_df)),
            "rows_after_patch": int(len(working_df)),
            "filename_column": detected_filename_col,
            "filename_like_rows": int(filename_like_rows),
            "filename_cells_normalized": int(filename_cells_normalized),
            "embedded_header_rows_removed": int(embedded_header_rows_removed),
            "filename_references_repaired": int(filename_reference_repairs),
            "unresolved_reference_count": int(unresolved_reference_count),
            "duplicate_groups_detected": int(duplicate_groups_count),
            "duplicate_rows_removed": int(duplicate_rows_removed),
            "duplicate_rows_merged": int(duplicate_rows_merged),
        }

        return {
            "is_valid": len(blockers) == 0,
            "msf_path": file_path,
            "patched_msf_path": patched_msf_path,
            "apply_requested": bool(apply),
            "duplicate_policy": policy,
            "parse_options": profile.get("parse_options", {}),
            "available_sheets": profile.get("available_sheets", []),
            "sheet_name": profile.get("sheet_name"),
            "header_row_index": profile.get("header_row_index"),
            "filename_column": detected_filename_col,
            "blockers": blockers,
            "warnings": warnings,
            "actions": actions,
            "summary": summary,
            "preview": self.get_msf_preview(working_df),
            "validation": validation_payload,
        }

    def get_msf_preview(
        self, df: pd.DataFrame, max_rows: int = 5
    ) -> Dict[str, Any]:
        """
        Get a preview of the MSF data for display purposes.

        Args:
            df: Parsed MSF DataFrame
            max_rows: Maximum number of data rows to include

        Returns:
            Preview dictionary with columns and sample data
        """
        return {
            "columns": list(df.columns),
            "total_rows": len(df),
            "preview_rows": df.head(max_rows).to_dict(orient="records"),
        }
