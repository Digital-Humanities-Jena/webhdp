# services/edm_service.py
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional
from functools import lru_cache
from pathlib import Path
from lxml import etree
import jinja2
import re
import fnmatch
from services.local_edm_validator_client import (
    LocalEdmValidatorClient,
    LocalEdmValidatorClientError,
)

logger = logging.getLogger(__name__)


class DotDict(dict):
    """
    A dictionary subclass that allows attribute-style access to keys.
    This enables Jinja2 templates to use `zenodo.metadata.prereserve_doi.doi`
    instead of `zenodo['metadata']['prereserve_doi']['doi']`.
    """
    def __getattr__(self, name):
        try:
            value = self[name]
            # Recursively wrap nested dicts
            if isinstance(value, dict) and not isinstance(value, DotDict):
                value = DotDict(value)
                self[name] = value
            return value
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")



class EdmService:
    """
    Service for generating Europeana Data Model (EDM) XML files.

    Optimizations included:
    - Enhanced schema compliance (edm:WebResource, edm:Agent)
    - XML validation with XSD/lxml
    - Advanced Jinja2 helpers (lang_tag, iso_date, generate_uri)
    - Template pre-compilation/caching
    - Granular error reporting
    """

    PLACEHOLDER_THUMBNAIL_URL = "https://assets.heritage-data.org/placeholders/3d_model_placeholder.png"


    def __init__(self):
        # XML Namespaces
        self.namespaces = {
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "edm": "http://www.europeana.eu/schemas/edm/",
            "dc": "http://purl.org/dc/elements/1.1/",
            "dcterms": "http://purl.org/dc/terms/",
            "schema": "https://schema.org/",
            "ore": "http://www.openarchives.org/ore/terms/",
            "foaf": "http://xmlns.com/foaf/0.1/",
            "skos": "http://www.w3.org/2004/02/skos/core#",
            "crm": "http://www.cidoc-crm.org/cidoc-crm/",
            "wgs84_pos": "http://www.w3.org/2003/01/geo/wgs84_pos#",
            "rdaGr2": "http://rdvocab.info/ElementsGr2/",
            "svcs": "http://rdfs.org/sioc/services#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "xalan": "http://xml.apache.org/xalan"
        }

        # Constants for Content-Aware Visual Priority (Ported from AnyLOD)
        self.FILE_TYPE_BY_EXTENSION = {
            # 3D Models
            'obj': '3d_model', 'stl': '3d_model', 'fbx': '3d_model', 'gltf': '3d_model',
            'glb': '3d_model', 'ply': '3d_model', 'dae': '3d_model', '3ds': '3d_model',
            'blend': '3d_model', 'c4d': '3d_model', 'max': '3d_model',
            # Images
            'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image',
            'webp': 'image', 'tiff': 'image', 'tif': 'image', 'bmp': 'image',
            'svg': 'image', 'psd': 'image',
            # Video
            'mp4': 'video', 'avi': 'video', 'mov': 'video', 'mkv': 'video',
            'webm': 'video', 'wmv': 'video',
            # Audio
            'mp3': 'audio', 'wav': 'audio', 'flac': 'audio', 'ogg': 'audio',
            # Documents
            'pdf': 'document', 'doc': 'document', 'docx': 'document', 'txt': 'document',
            # Data
            'csv': 'data', 'json': 'data', 'xml': 'data',
        }

        self.PRIMARY_FILE_PRIORITY = {
            '3D': ['3d_model', 'image', 'video', 'document'],
            'IMAGE': ['image', '3d_model', 'document'],
            'VIDEO': ['video', 'image', 'document'],
            'SOUND': ['audio', 'document'],
            'TEXT': ['document', 'presentation', 'data', 'image'],
        }

        self.FORMAT_3D_VOCABULARY = {
            'gltf': 'glTF (GL Transmission Format)',
            'glb': 'glTF Binary',
            'obj': 'Wavefront OBJ',
            'stl': 'STL (Stereolithography)',
            'fbx': 'Autodesk FBX',
            'ply': 'Polygon File Format (PLY)',
            'dae': 'COLLADA (DAE)',
            '3ds': '3D Studio Max',
            'blend': 'Blender',
        }

        # Hierarchical 3D Selection Constants
        self.THREED_TIER_1 = {'glb', 'fbx', 'stl', 'ply', 'dae'}  # Self-contained or mostly robust
        self.THREED_TIER_2 = {'obj', 'gltf'}                      # Requires sidecars (MTL, BIN)
        self.THREED_SIDECARS = {
            'obj': ['.mtl'],
            'gltf': ['.bin']
        }

        # Europeana Problem Patterns (P1-P12)
        self.PROBLEM_PATTERNS = {
            'P1': {'title': 'Systematic use of the same title', 'severity': 'WARNING'},
            'P2': {'title': 'Equal title and description fields', 'severity': 'WARNING'},
            'P3': {'title': 'Near-Identical title and description fields', 'severity': 'WARNING'},
            'P5': {'title': 'Unrecognisable title', 'severity': 'WARNING'},
            'P6': {'title': 'Non-meaningful title', 'severity': 'WARNING'},
            'P7': {'title': 'Very short description', 'severity': 'WARNING'},
            'P9': {'title': 'Missing description fields', 'severity': 'WARNING'},
            'P12': {'title': 'Extremely long values', 'severity': 'WARNING'},
        }

        self.ALLOWED_DIGITAL_SOURCE_TYPE_URIS = {
            "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
            "https://cv.iptc.org/newscodes/digitalsourcetype/dataDrivenMedia",
            "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
        }
        self.DIGITAL_SOURCE_TYPE_MAP = {
            "digital capture": "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
            "digitalcapture": "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
            "digitisation": "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
            "digitization": "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
            "data driven media": "https://cv.iptc.org/newscodes/digitalsourcetype/dataDrivenMedia",
            "datadrivenmedia": "https://cv.iptc.org/newscodes/digitalsourcetype/dataDrivenMedia",
            "digital creation": "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
            "digitalcreation": "https://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation",
            "3d reconstruction": "https://cv.iptc.org/newscodes/digitalsourcetype/dataDrivenMedia",
        }

        self.LANGUAGE_MAP = {
            "english": "en",
            "eng": "en",
            "dutch": "nl",
            "nld": "nl",
            "french": "fr",
            "fra": "fr",
            "fre": "fr",
            "german": "de",
            "deu": "de",
            "ger": "de",
            "italian": "it",
            "ita": "it",
            "spanish": "es",
            "spa": "es",
            "polish": "pl",
            "pol": "pl",
            "multilingual content": "mul",
            "multilingual": "mul",
            "multilingualcontent": "mul",
            "mul": "mul",
        }

        # local-edm-validator /record/validation expects these display values.
        self.ISO_TO_LOCAL_VALIDATOR_LANGUAGE = {
            "en": "English",
            "nl": "Dutch",
            "fr": "French",
            "de": "German",
            "it": "Italian",
            "es": "Spanish",
            "pl": "Polish",
            "mul": "Multilingual Content",
            "und": "Multilingual Content",
        }
        self.LOCAL_VALIDATOR_LANGUAGE_FALLBACK = "Multilingual Content"

        self.ISO_TO_LOCAL_VALIDATOR_COUNTRY = {
            "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia",
            "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia",
            "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece",
            "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia",
            "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands",
            "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SK": "Slovakia",
            "SI": "Slovenia", "ES": "Spain", "SE": "Sweden", "EU": "Europe",
        }
        self.LOCAL_VALIDATOR_COUNTRY_FALLBACK = "Europe"

        self.ALLOWED_INTENDED_USAGE_URIS = {
            "http://data.europeana.eu/vocabulary/usageArea/Knowledge",
            "http://data.europeana.eu/vocabulary/usageArea/Research",
            "http://data.europeana.eu/vocabulary/usageArea/Education",
            "http://data.europeana.eu/vocabulary/usageArea/Infotainment",
            "http://data.europeana.eu/vocabulary/usageArea/Tourism",
            "http://data.europeana.eu/vocabulary/usageArea/Gaming",
            "http://data.europeana.eu/vocabulary/usageArea/Exhibition",
            "http://data.europeana.eu/vocabulary/usageArea/Creativity",
            "http://data.europeana.eu/vocabulary/usageArea/Design",
            "http://data.europeana.eu/vocabulary/usageArea/Art",
            "http://data.europeana.eu/vocabulary/usageArea/Curation",
            "http://data.europeana.eu/vocabulary/usageArea/Maintenance",
            "http://data.europeana.eu/vocabulary/usageArea/Restoration",
            "http://data.europeana.eu/vocabulary/usageArea/Documentation",
        }
        self.INTENDED_USAGE_MAP = {
            "knowledge": "http://data.europeana.eu/vocabulary/usageArea/Knowledge",
            "research": "http://data.europeana.eu/vocabulary/usageArea/Research",
            "education": "http://data.europeana.eu/vocabulary/usageArea/Education",
            "infotainment": "http://data.europeana.eu/vocabulary/usageArea/Infotainment",
            "tourism": "http://data.europeana.eu/vocabulary/usageArea/Tourism",
            "gaming": "http://data.europeana.eu/vocabulary/usageArea/Gaming",
            "exhibition": "http://data.europeana.eu/vocabulary/usageArea/Exhibition",
            "creativity": "http://data.europeana.eu/vocabulary/usageArea/Creativity",
            "design": "http://data.europeana.eu/vocabulary/usageArea/Design",
            "art": "http://data.europeana.eu/vocabulary/usageArea/Art",
            "curation": "http://data.europeana.eu/vocabulary/usageArea/Curation",
            "maintenance": "http://data.europeana.eu/vocabulary/usageArea/Maintenance",
            "restoration": "http://data.europeana.eu/vocabulary/usageArea/Restoration",
            "documentation": "http://data.europeana.eu/vocabulary/usageArea/Documentation",
        }

        # Caching for XSD and XSLT
        self._xsd_cache = {}
        self._xslt_cache = {}
        import threading
        self._cache_lock = threading.Lock()

        # Register namespaces
        for prefix, uri in self.namespaces.items():
            ET.register_namespace(prefix, uri)

        # URI counter for generating unique identifiers
        self._uri_counters = {}

        # Cache for compiled Jinja environments
        self._template_cache = {}

    def _get_xsd(self, xsd_path: str):
        from lxml import etree
        with self._cache_lock:
            if xsd_path not in self._xsd_cache:
                try:
                    xmlschema_doc = etree.parse(xsd_path)
                    self._xsd_cache[xsd_path] = etree.XMLSchema(xmlschema_doc)
                except Exception as e:
                    logger.error(f"Failed to parse XSD {xsd_path}: {e}")
                    return None
            return self._xsd_cache[xsd_path]

    def _get_xslt(self, xslt_path: str):
        from lxml import etree
        with self._cache_lock:
            if xslt_path not in self._xslt_cache:
                try:
                    xslt_doc = etree.parse(xslt_path)
                    self._xslt_cache[xslt_path] = etree.XSLT(xslt_doc)
                except etree.XSLTParseError as e:
                    # Specific handling for XSLT 2.0 features not supported by lxml
                    if "unknown function element" in str(e) or "xsl:function" in str(e):
                        logger.warning(f"XSLT engine (lxml) is incompatible with Schematron rules in {xslt_path}: {e}")
                        # Store a special marker in the cache to avoid re-parsing
                        self._xslt_cache[xslt_path] = "INCOMPATIBLE"
                    else:
                        logger.error(f"Failed to parse XSLT {xslt_path}: {e}")
                        return None
                except Exception as e:
                    logger.error(f"Unexpected error parsing XSLT {xslt_path}: {e}")
                    return None

            val = self._xslt_cache[xslt_path]
            return None if val == "INCOMPATIBLE" else val

    # ==========================================================================
    # Jinja2 Helper Functions
    # ==========================================================================

    def lang_tag(self, text: str, lang: str = "en") -> str:
        """
        Wraps a text value with xml:lang attribute for use in XML.
        Returns the text as-is for embedding; the lang attribute should be
        applied at the element level in the template.

        Usage in template: <dc:title xml:lang="{{ lang }}">{{ text }}</dc:title>
        Or use: {{ helpers.lang_tag(metadata.title, 'de') }}
        """
        return text if text else ""

    def iso_date(self, date_str: str) -> str:
        """
        Normalizes a date string to ISO 8601 format (YYYY-MM-DD).
        Handles various input formats.
        """
        if not date_str:
            return ""

        # If already ISO format, return as-is
        if re.match(r'^\d{4}-\d{2}-\d{2}$', str(date_str)):
            return str(date_str)
        if re.match(r'^\d{4}$', str(date_str)):
            return f"{str(date_str)}-01-01"
        if re.match(r'^\d{4}\.0$', str(date_str)):
            return f"{str(date_str)[:4]}-01-01"

        # Try common formats
        formats = [
            '%Y-%m-%d',
            '%d/%m/%Y',
            '%m/%d/%Y',
            '%Y/%m/%d',
            '%d.%m.%Y',
            '%Y%m%d',
            '%B %d, %Y',
            '%d %B %Y',
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(str(date_str), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

        # Return original if parsing fails
        logger.warning(f"Could not parse date: {date_str}")
        return str(date_str)

    def _normalize_vocab_key(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        return re.sub(r"[\s_-]+", " ", text)

    def normalize_intended_usage_uri(self, value: Any, fallback: str = "") -> str:
        """
        Normalize intended usage values to a controlled Europeana URI.
        Returns an empty string when input is missing/invalid unless a fallback is provided.
        """
        if value is None:
            return fallback

        text = str(value).strip()
        if not text:
            return fallback
        if text in self.ALLOWED_INTENDED_USAGE_URIS:
            return text

        mapped = self.INTENDED_USAGE_MAP.get(self._normalize_vocab_key(text))
        if mapped:
            return mapped
        return fallback

    def normalize_digital_source_type_uri(self, value: Any, fallback: str = "") -> str:
        """
        Normalize digitalSourceType values to an allowed IPTC URI.
        Returns an empty string when input is missing/invalid unless a fallback is provided.
        """
        if value is None:
            return fallback

        text = str(value).strip()
        if not text:
            return fallback
        if text in self.ALLOWED_DIGITAL_SOURCE_TYPE_URIS:
            return text

        mapped = self.DIGITAL_SOURCE_TYPE_MAP.get(self._normalize_vocab_key(text))
        if mapped:
            return mapped
        return fallback

    def normalize_language_code(self, value: Any) -> str:
        """
        Normalize language values to a two-letter ISO 639-1 code.
        Returns 'und' (undetermined) if input is missing/invalid.
        """
        fallback = "und"
        if value is None:
            return fallback

        text = str(value).strip()
        if not text:
            return fallback

        # Check if it's already a valid 2 or 3-letter ISO code
        if re.match(r'^[a-z]{2,3}$', text.lower()):
            return text.lower()

        mapped = self.LANGUAGE_MAP.get(self._normalize_vocab_key(text))
        if mapped:
            return mapped
        return fallback

    def _normalize_edm_metadata_vocabularies(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(metadata, dict):
            return metadata
        normalized = dict(metadata)
        if "intended_usage" in normalized:
            normalized["intended_usage"] = self.normalize_intended_usage_uri(normalized.get("intended_usage"))
        if "digital_source_type" in normalized:
            normalized["digital_source_type"] = self.normalize_digital_source_type_uri(
                normalized.get("digital_source_type")
            )
        if "language" in normalized:
            normalized["language"] = self.normalize_language_code(normalized.get("language"))
        if "point_count" in normalized:
            try:
                normalized["point_count"] = int(str(normalized["point_count"]).replace(",", "").replace(".", "").strip())
            except (ValueError, TypeError):
                pass
        return normalized

    def normalize_local_validator_language(self, iso_code: Any) -> str:
        """Map language input to a local-edm-validator display value."""
        if iso_code is None:
            return self.LOCAL_VALIDATOR_LANGUAGE_FALLBACK

        text = str(iso_code).strip()
        if not text:
            return self.LOCAL_VALIDATOR_LANGUAGE_FALLBACK

        # Already a local-edm-validator display value.
        for value in self.ISO_TO_LOCAL_VALIDATOR_LANGUAGE.values():
            if value.lower() == text.lower():
                return value

        normalized_iso = self.normalize_language_code(text)
        return self.ISO_TO_LOCAL_VALIDATOR_LANGUAGE.get(
            normalized_iso,
            self.LOCAL_VALIDATOR_LANGUAGE_FALLBACK,
        )

    def normalize_metis_language(self, iso_code: Any) -> str:
        """Backward-compatible alias for older callers."""
        return self.normalize_local_validator_language(iso_code)

    def normalize_local_validator_country(self, country: Any) -> str:
        """Map country code or name to a local-edm-validator display value."""
        if not country:
            return self.LOCAL_VALIDATOR_COUNTRY_FALLBACK

        text = str(country).strip()
        if not text:
            return self.LOCAL_VALIDATOR_COUNTRY_FALLBACK

        upper = text.upper()
        if upper in self.ISO_TO_LOCAL_VALIDATOR_COUNTRY:
            return self.ISO_TO_LOCAL_VALIDATOR_COUNTRY[upper]

        # Try finding by name (case-insensitive)
        for code, name in self.ISO_TO_LOCAL_VALIDATOR_COUNTRY.items():
            if name.upper() == upper:
                return name

        if upper == "EUROPE":
            return "Europe"

        return self.LOCAL_VALIDATOR_COUNTRY_FALLBACK

    def normalize_metis_country(self, country: Any) -> str:
        """Backward-compatible alias for older callers."""
        return self.normalize_local_validator_country(country)

    def map_3d_type(self, metadata: Dict[str, Any]) -> str:
        """Match 3D model type based on counts or format."""
        def _has_positive_count(value: Any) -> bool:
            if value in (None, ""):
                return False
            try:
                return float(str(value).strip().replace(",", "")) > 0
            except (TypeError, ValueError):
                return False

        model_type = self._normalize_vocab_key((metadata or {}).get("model_type"))
        if model_type in {"point cloud", "pointcloud", "3d point cloud", "3dpointcloud"}:
            return "http://data.europeana.eu/vocabulary/modelType/3DPointCloud"
        if model_type in {"mesh", "3d mesh", "3dmesh"}:
            return "http://data.europeana.eu/vocabulary/modelType/3DMesh"
        if _has_positive_count((metadata or {}).get("point_count")):
            return "http://data.europeana.eu/vocabulary/modelType/3DPointCloud"
        return "http://data.europeana.eu/vocabulary/modelType/3DMesh"

    def _resolve_oembed_service(self, url: str) -> Optional[Dict[str, str]]:
        if not url:
            return None

        lower_url = str(url).strip().lower()
        if not lower_url:
            return None

        if "sketchfab.com" in lower_url:
            return {
                "endpoint": "https://sketchfab.com/oembed",
                "label": "Sketchfab Viewer",
            }
        if "/oembed" in lower_url:
            from urllib.parse import urlsplit

            split = urlsplit(str(url))
            endpoint = f"{split.scheme}://{split.netloc}{split.path}" if split.scheme and split.netloc else str(url)
            return {
                "endpoint": endpoint,
                "label": "oEmbed Service",
            }
        return None

    def _looks_like_3d_resource_uri(self, url: str) -> bool:
        if not url:
            return False
        from urllib.parse import urlparse, unquote

        path = unquote(urlparse(str(url)).path or "")
        match = re.search(r"/files/([^/]+)/content/?$", path, flags=re.IGNORECASE)
        filename = match.group(1) if match else path.rsplit("/", 1)[-1]
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        return ext in {"glb", "gltf", "obj", "fbx", "stl", "ply", "dae", "3ds", "blend"}

    def _infer_mime_type_from_url(self, url: str) -> str:
        if not url:
            return "application/octet-stream"

        from urllib.parse import urlparse, unquote
        import mimetypes

        path = unquote(urlparse(str(url)).path or "")
        match = re.search(r"/files/([^/]+)/content/?$", path, flags=re.IGNORECASE)
        filename = match.group(1) if match else path.rsplit("/", 1)[-1]
        lower_filename = filename.lower()
        ext = lower_filename.rsplit(".", 1)[-1] if "." in lower_filename else ""

        explicit_3d_mime = {
            "glb": "model/gltf-binary",
            "gltf": "model/gltf+json",
            "obj": "model/obj",
            "stl": "model/stl",
            "ply": "application/ply",
            "fbx": "application/fbx",
            "dae": "model/vnd.collada+xml",
            "3ds": "application/x-3ds",
            "blend": "application/x-blender",
        }
        if ext in explicit_3d_mime:
            return explicit_3d_mime[ext]

        guessed_mime, _ = mimetypes.guess_type(filename or path)
        return guessed_mime or "application/octet-stream"

    def is_oembed_viewer(self, url: str) -> bool:
        """Detect if a URL points to a viewer with a known oEmbed service."""
        return self._resolve_oembed_service(url) is not None

    def generate_uri(self, prefix: str = "item", identifier: Optional[str] = None) -> str:
        """
        Generates consistent URIs for internal nodes.

        Examples:
            generate_uri('agent') -> '#agent1'
            generate_uri('place', 'london') -> '#place_london'
        """
        if identifier:
            # Sanitize identifier for URI use
            safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(identifier).lower())
            return f"#{prefix}_{safe_id}"
        else:
            # Auto-increment counter
            if prefix not in self._uri_counters:
                self._uri_counters[prefix] = 0
            self._uri_counters[prefix] += 1
            return f"#{prefix}{self._uri_counters[prefix]}"

    def reset_uri_counters(self):
        """Reset URI counters for a new document generation."""
        self._uri_counters = {}

    def generate_content_url(self, record_id: str, filename: str, is_sandbox: Optional[bool] = None) -> str:
        """
        Generates the direct content URL for a file in a Zenodo record.
        Respects the provided is_sandbox flag, or falls back to configuration.
        """
        from flask import current_app
        if is_sandbox is None:
            is_sandbox = current_app.config.get("ZENODO_SANDBOX_MODE", False)

        # If it's a placeholder, return its static URL directly
        if filename == 'placeholder_thumbnail.png':
             return self.PLACEHOLDER_THUMBNAIL_URL

        domain = "sandbox.zenodo.org" if is_sandbox else "zenodo.org"
        return f"https://{domain}/api/records/{record_id}/files/{filename}/content"

    def get_record_html_url(self, zenodo_record: Dict[str, Any]) -> str:
        """Return a stable Zenodo landing-page URL, preferring /records/ over legacy /deposit/."""
        if not isinstance(zenodo_record, dict):
            return "https://zenodo.org/records/unknown"

        links = zenodo_record.get("links")
        if isinstance(links, dict):
            html_url = str(links.get("html") or "").strip()
            if html_url:
                return html_url.replace("/deposit/", "/records/")

        record_id = str(zenodo_record.get("id") or zenodo_record.get("record_id") or "unknown").strip()
        base = "https://sandbox.zenodo.org" if "sandbox.zenodo.org" in str(links or "") else "https://zenodo.org"
        return f"{base}/records/{record_id}"

    def get_file_content_url(
        self,
        file_obj: Dict[str, Any],
        record_id: str,
        *,
        is_sandbox: Optional[bool] = None,
    ) -> str:
        """Resolve a direct file URL from Zenodo metadata, preferring authoritative links.content."""
        if isinstance(file_obj, dict):
            existing = str(file_obj.get("content_url") or "").strip()
            if existing:
                return existing

            links = file_obj.get("links")
            if isinstance(links, dict):
                for key in ("content", "download"):
                    direct_url = str(links.get(key) or "").strip()
                    if direct_url:
                        return direct_url

                self_url = str(links.get("self") or "").strip()
                if self_url:
                    if "/api/records/" in self_url and not self_url.endswith("/content"):
                        return self_url.rstrip("/") + "/content"
                    if self_url.endswith("/content"):
                        return self_url

        filename = ""
        if isinstance(file_obj, dict):
            filename = str(file_obj.get("key") or file_obj.get("filename") or file_obj.get("name") or "").strip()
        return self.generate_content_url(record_id, filename, is_sandbox=is_sandbox)

    def get_file_checksum_info(self, file_obj: Dict[str, Any]) -> Dict[str, str]:
        """Normalize checksum metadata into METS-friendly CHECKSUM/CHECKSUMTYPE values."""
        if not isinstance(file_obj, dict):
            return {}

        raw_checksum = file_obj.get("checksum")
        if isinstance(raw_checksum, dict):
            checksum_value = str(raw_checksum.get("value") or "").strip()
            checksum_type = str(raw_checksum.get("type") or "").strip().upper()
            if checksum_value and checksum_type:
                return {"checksum": checksum_value, "checksum_type": checksum_type}
            return {}

        checksum_text = str(raw_checksum or "").strip()
        if not checksum_text:
            return {}

        if ":" in checksum_text:
            algorithm, value = checksum_text.split(":", 1)
            algorithm = algorithm.strip().upper()
            value = value.strip()
            if algorithm and value:
                return {"checksum": value, "checksum_type": algorithm}
            return {}

        return {"checksum": checksum_text, "checksum_type": "MD5"}

    # ==========================================================================
    # Smart File Selection (Content-Aware Visual Priority)
    # ==========================================================================

    def _get_file_extension(self, filename: str) -> str:
        """Extract file extension from filename."""
        if '.' in filename:
            return filename.rsplit('.', 1)[-1].lower()
        return ''

    def _get_file_content_type(self, filename: str) -> str:
        """
        Determine content type category from filename.
        Returns: '3d_model', 'image', 'video', 'audio', 'document', 'data', 'other'
        """
        ext = self._get_file_extension(filename)

        # Load dynamic configuration if available
        config = self._get_modality_config()
        extension_mapping = self.FILE_TYPE_BY_EXTENSION
        if config and "extensions" in config:
            extension_mapping = {**extension_mapping, **config["extensions"]}

        return extension_mapping.get(ext, 'other')

    def _select_smart_primary_file(self, files: list, zenodo_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Intelligently select the best primary file based on inferred EDM type.
        Prioritizes 3D models for potential 3D objects, even if metadata says 'Dataset'.
        Includes hierarchical selection for 3D models (GLB > OBJ > Image).
        """
        if not files:
            return None

        # 1. Group files by our content categories FIRST
        files_by_type = {}
        all_filenames = set()
        for f in files:
            filename = f.get('key') or f.get('filename', '')
            all_filenames.add(filename.lower())
            c_type = self._get_file_content_type(filename)
            if c_type not in files_by_type:
                files_by_type[c_type] = []
            files_by_type[c_type].append(f)

        # 2. Determine implied EDM type from metadata
        resource_type = zenodo_metadata.get('resource_type') if isinstance(zenodo_metadata, dict) else None
        if isinstance(resource_type, dict):
            upload_type = resource_type.get('type') or resource_type.get('id') or zenodo_metadata.get('upload_type', 'other')
        elif resource_type:
            upload_type = str(resource_type)
        else:
            upload_type = zenodo_metadata.get('upload_type', 'other') if isinstance(zenodo_metadata, dict) else 'other'
        edm_type = self._map_zenodo_type_to_edm(upload_type)

        # 3. Robust 3D Override: If ANY 3D model file exists, FORCE EDM Type to 3D.
        # This overrides any metadata "Dataset" or "Image" claims.
        if '3d_model' in files_by_type and files_by_type['3d_model']:
            edm_type = '3D'

        # 4. Dedicated Hierarchical 3D Selection
        if edm_type == '3D' and '3d_model' in files_by_type:
            threed_files = files_by_type['3d_model']

            # --- Tier 1 Selection ---
            tier1_candidates = [f for f in threed_files if self._get_file_extension(f.get('key') or f.get('filename', '')) in self.THREED_TIER_1]
            if tier1_candidates:
                tier1_candidates.sort(key=lambda x: x.get('size', 0), reverse=True)
                return tier1_candidates[0]

            # --- Tier 2 Selection (with sidecar check) ---
            tier2_candidates = []
            for f in threed_files:
                fname = f.get('key') or f.get('filename', '')
                ext = self._get_file_extension(fname)
                if ext in self.THREED_TIER_2:
                    # Check if sidecars exist
                    name_without_ext = fname.rsplit('.', 1)[0].lower()
                    required_sidecars = self.THREED_SIDECARS.get(ext, [])
                    has_all_sidecars = True
                    for suffix in required_sidecars:
                        if (name_without_ext + suffix) not in all_filenames:
                            has_all_sidecars = False
                            break

                    if has_all_sidecars:
                        tier2_candidates.append(f)

            if tier2_candidates:
                tier2_candidates.sort(key=lambda x: x.get('size', 0), reverse=True)
                return tier2_candidates[0]

            # If we are here, we have 3d_model files but none are Tier 1 or validated Tier 2.
            # We now keep them but prioritize good ones first.
            good_threed = tier1_candidates + tier2_candidates
            broken_threed = [f for f in threed_files if f not in good_threed]

            if broken_threed:
                broken_threed.sort(key=lambda x: x.get('size', 0), reverse=True)

            files_by_type['3d_model'] = good_threed + broken_threed
        else:
            broken_threed = []

        # 5. Standard Category-based Selection
        priority = self.PRIMARY_FILE_PRIORITY.get(edm_type, ['document', 'image'])

        for c_type in priority:
            if c_type in files_by_type and files_by_type[c_type]:
                # Tie-breaker: Size (Largest first)
                candidates = files_by_type[c_type]
                candidates.sort(key=lambda x: x.get('size', 0), reverse=True)
                return candidates[0]

        # 6. Last Resort: Even broken 3D models are better than nothing if we expected 3D
        if broken_threed:
            broken_threed.sort(key=lambda x: x.get('size', 0), reverse=True)
            return broken_threed[0]

        # Fallback to largest file
        try:
            return max(files, key=lambda f: f.get('size', 0))
        except Exception:
            return files[0]

    def _enrich_file_metadata(self, f: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Enrich file object with computed properties for the template.
        """
        import mimetypes

        filename = f.get('key') or f.get('filename', '')
        ext = self._get_file_extension(filename)
        c_type = self._get_file_content_type(filename)

        # Detect standard MIME type
        mime_type, _ = mimetypes.guess_type(filename)

        # If detection failed or gave generic binary, use our specific fallbacks
        if not mime_type or mime_type == 'application/octet-stream':
            # Fallback based on known extensions
            # Common 3D formats (Unofficial but widely used)
            mime_map = {
                'obj': 'model/obj',
                'ply': 'application/ply',
                'stl': 'model/stl',
                'fbx': 'application/fbx',
                'dae': 'model/vnd.collada+xml',
                '3ds': 'application/x-3ds',
                'blend': 'application/x-blender',
            }
            if ext in mime_map:
                mime_type = mime_map[ext]
            # Fallback based on our internal c_type
            elif c_type == 'image': mime_type = f"image/{ext}" if ext else "image/jpeg"
            elif c_type == '3d_model': mime_type = "model/gltf-binary" if ext == 'glb' else "application/octet-stream"
            elif c_type == 'video': mime_type = f"video/{ext}" if ext else "video/mp4"
            elif c_type == 'audio': mime_type = f"audio/{ext}" if ext else "audio/mpeg"
            elif c_type == 'document': mime_type = "application/pdf" if ext == 'pdf' else "text/plain"
            else: mime_type = "application/octet-stream"

        enriched = f.copy()
        checksum_info = self.get_file_checksum_info(f)
        enriched.update({
            'filename': filename, # Ensure filename is available at top level
            'extension': ext,
            'content_type': c_type, # Internal Category (image, 3d_model, etc.)
            'mime_type': mime_type, # Standard MIME type for XML (e.g. image/jpeg)
            'format': mime_type,    # Key used by standard templates for dc:format
            'is_3d': c_type == '3d_model',
            'is_image': c_type == 'image',
            'is_video': c_type == 'video',
            'format_name': self.FORMAT_3D_VOCABULARY.get(ext, ''),
            'is_placeholder': f.get('is_placeholder', False), # Flag for templates
            'checksum': checksum_info.get('checksum', ''),
            'checksum_type': checksum_info.get('checksum_type', ''),
            # EDM Type mapping for template use
            # 3D, IMAGE, SOUND, VIDEO, TEXT
            'edm_type': self._map_content_type_to_edm_type(
                c_type,
                override=(metadata or {}).get('edm_type_override'),
            ),
            'metadata': metadata or {}
        })
        return enriched

    def _map_content_type_to_edm_type(self, content_type: str, override: Optional[Any] = None) -> str:
        """Map internal file categories to the EDM schema enumeration."""
        allowed = {"TEXT", "VIDEO", "IMAGE", "SOUND", "3D"}
        if override:
            normalized = str(override).strip().upper()
            if normalized in allowed:
                return normalized

        mapping = {
            "3d_model": "3D",
            "image": "IMAGE",
            "video": "VIDEO",
            "audio": "SOUND",
            "document": "TEXT",
            "data": "TEXT",
            "other": "TEXT",
            "presentation": "TEXT",
        }
        return mapping.get(str(content_type or "").strip().lower(), "TEXT")

    def get_placeholder_thumbnail(self) -> Dict[str, Any]:
        """Returns a virtual file object representing a placeholder thumbnail."""
        return {
            'key': 'placeholder_thumbnail.png',
            'filename': 'placeholder_thumbnail.png',
            'size': 0,
            'is_placeholder': True,
            'content_url': self.PLACEHOLDER_THUMBNAIL_URL,
            # Pre-enrich properties to ensure safety if _enrich skipped or behaves oddly
            'content_type': 'image',
            'mime_type': 'image/png'
        }

    def _normalize_thumbnail_file_list(self, raw_value: Any) -> List[str]:
        """Normalizes a list/string value to a lowercase filename list."""
        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            values = raw_value
        else:
            values = re.split(r"[;,]", str(raw_value))
        return [str(v).strip().lower() for v in values if str(v).strip()]

    def _score_thumbnail_image(self, file_entry: Dict[str, Any], main_file: Optional[Dict[str, Any]] = None) -> int:
        """
        Scores a candidate image for thumbnail quality.
        Higher score means better candidate.
        """
        name = (file_entry.get('key') or file_entry.get('filename', '')).lower()
        score = 0

        if 'thumb' in name:
            score += 20
        if 'preview' in name:
            score += 10

        # Fast Renderer pattern: *_rNNN.png
        if '_r' in name and name[-8:-4].startswith('_r') and name[-7:-4].isdigit():
            score += 15
            if 'r029' in name or 'r030' in name:
                score += 2

        if main_file and file_entry == main_file:
            score -= 5

        return score

    def _select_thumbnail_files(
        self,
        files: List[Dict[str, Any]],
        main_file: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        allow_placeholder: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Select one or multiple thumbnail candidates.
        Supports mapping controls:
        - lod_thumbnail_mode: auto|any|all|pattern|list
        - lod_thumbnail_pattern: wildcard pattern (for pattern mode)
        - lod_thumbnail_files: comma/semicolon list (for list mode)

        When lod_thumbnail_mapping_enabled is true and lod_rendered_thumbnails is present,
        selection is restricted to rendered thumbnail candidates.
        """
        metadata = metadata or {}
        images = [
            entry
            for entry in files
            if self._get_file_content_type(entry.get('key') or entry.get('filename', '')) == 'image'
        ]

        # Prefer thumbnails different from the main file when possible.
        main_name = (main_file or {}).get('key') or (main_file or {}).get('filename')
        if main_name:
            main_name_lower = str(main_name).lower()
            non_main_images = [
                entry
                for entry in images
                if (entry.get('key') or entry.get('filename', '')).lower() != main_name_lower
            ]
            if non_main_images:
                images = non_main_images

        if not images:
            from flask import current_app
            if allow_placeholder or not current_app.config.get("ENABLE_RENDERER", True):
                return [self.get_placeholder_thumbnail()]
            return []

        def sort_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return sorted(
                candidates,
                key=lambda entry: (self._score_thumbnail_image(entry, main_file), entry.get('size', 0)),
                reverse=True,
            )

        candidate_pool = images
        mapping_enabled = bool(metadata.get("lod_thumbnail_mapping_enabled", False))
        rendered_names = set(self._normalize_thumbnail_file_list(metadata.get("lod_rendered_thumbnails")))
        if mapping_enabled and rendered_names:
            rendered_candidates = [
                entry
                for entry in images
                if (entry.get('key') or entry.get('filename', '')).lower() in rendered_names
            ]
            if rendered_candidates:
                candidate_pool = rendered_candidates

        mode = str(metadata.get("lod_thumbnail_mode", "auto")).strip().lower()
        selected: List[Dict[str, Any]] = []

        if mode == "all":
            selected = sort_candidates(candidate_pool)
        elif mode == "pattern":
            pattern = str(metadata.get("lod_thumbnail_pattern", "")).strip().lower()
            if pattern:
                selected = [
                    entry
                    for entry in sort_candidates(candidate_pool)
                    if fnmatch.fnmatch((entry.get('key') or entry.get('filename', '')).lower(), pattern)
                ]
        elif mode in {"list", "specific"}:
            allowed_names = set(self._normalize_thumbnail_file_list(metadata.get("lod_thumbnail_files")))
            if allowed_names:
                selected = [
                    entry
                    for entry in sort_candidates(candidate_pool)
                    if (entry.get('key') or entry.get('filename', '')).lower() in allowed_names
                ]
        else:
            # auto or any => best single candidate.
            sorted_candidates = sort_candidates(candidate_pool)
            selected = [sorted_candidates[0]] if sorted_candidates else []

        # Fallback when strict mapping yields no match.
        if not selected:
            sorted_candidates = sort_candidates(candidate_pool)
            selected = [sorted_candidates[0]] if sorted_candidates else []

        # Deduplicate by filename/key.
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for entry in selected:
            name = (entry.get('key') or entry.get('filename', '')).lower()
            if name and name in seen:
                continue
            seen.add(name)
            deduped.append(entry)

        return deduped

    def _normalize_zenodo_files(self, zenodo_record: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Normalizes the 'files' field from Zenodo responses.
        Drafts and published records have different structures.
        Draft: record['files'] is list, or record['files']['entries'] is dict or list.
        """
        raw_files = zenodo_record.get('files', [])

        # 1. Handle "files": { "entries": ... } structure (Drafts often)
        if isinstance(raw_files, dict):
            if 'entries' in raw_files:
                entries = raw_files['entries']
                if isinstance(entries, dict):
                    # Dict of filename -> file_obj
                    raw_files = list(entries.values())
                elif isinstance(entries, list):
                    raw_files = entries
            # If it's just a dict without entries, it might be the new API format or unexpected
            # Fallback: check if the dict itself looks like a list of values? No, usually not.

        # 2. Ensure it's a list
        if not isinstance(raw_files, list):
            logger.warning(f"Unexpected files structure in Zenodo record: {type(raw_files)}")
            return []

        return raw_files

    def _select_thumbnail_file(
        self,
        files: List[Dict[str, Any]],
        main_file: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        allow_placeholder: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Selects the best image file to serve as the edm:object (thumbnail).
        - If main file is 3D, find a different Image file.
        - If main file is Image, return main_file (or specific logic).
        - Prioritize strictly: 'thumb', 'preview', then largest Image.
        """
        thumbnails = self._select_thumbnail_files(
            files,
            main_file=main_file,
            metadata=metadata,
            allow_placeholder=allow_placeholder,
        )
        return thumbnails[0] if thumbnails else None

    # ==========================================================================
    # XML Validation
    # ==========================================================================

    def validate_xml(self, xml_string: str) -> Dict[str, Any]:
        """
        Validates XML against EDM schema.

        Returns:
            dict: {
                'valid': bool,
                'errors': list of error messages,
                'warnings': list of warnings
            }
        """
        result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }

        try:
            from lxml import etree

            # Parse the XML first to check well-formedness
            try:
                doc = etree.fromstring(xml_string.encode('utf-8'))
            except etree.XMLSyntaxError as e:
                result['valid'] = False
                result['errors'].append(f"XML Syntax Error: {str(e)}")
                return result

            # Basic EDM structure validation
            # Check for required EDM elements
            ns = {
                'rdf': self.namespaces['rdf'],
                'edm': self.namespaces['edm'],
                'ore': self.namespaces['ore'],
                'dc': self.namespaces['dc']
            }

            # Check for ProvidedCHO
            cho_elements = doc.xpath('//edm:ProvidedCHO', namespaces=ns)
            if not cho_elements:
                result['errors'].append("Missing required element: edm:ProvidedCHO")
                result['valid'] = False
            else:
                # Check for dc:title in CHO (mandatory)
                for cho in cho_elements:
                    titles = cho.xpath('.//dc:title', namespaces=ns)
                    if not titles:
                        result['warnings'].append("ProvidedCHO missing dc:title (recommended)")

            # Check for Aggregation
            agg_elements = doc.xpath('//ore:Aggregation', namespaces=ns)
            if not agg_elements:
                result['warnings'].append("Missing ore:Aggregation (required for Europeana)")
            else:
                for agg in agg_elements:
                    # Check for edm:rights (mandatory in aggregation)
                    rights = agg.xpath('.//edm:rights', namespaces=ns)
                    if not rights:
                        result['warnings'].append("Aggregation missing edm:rights (required)")

                    # Check for edm:isShownAt or edm:isShownBy
                    shown_at = agg.xpath('.//edm:isShownAt', namespaces=ns)
                    shown_by = agg.xpath('.//edm:isShownBy', namespaces=ns)
                    if not shown_at and not shown_by:
                        result['warnings'].append("Aggregation should have edm:isShownAt or edm:isShownBy")

            # Check for WebResource (enhanced schema compliance)
            web_resources = doc.xpath('//edm:WebResource', namespaces=ns)
            if not web_resources:
                result['warnings'].append("No edm:WebResource elements found (recommended for full EDM compliance)")

            allowed_edm_types = {"TEXT", "VIDEO", "IMAGE", "SOUND", "3D"}
            for node in doc.xpath("//edm:type", namespaces=ns):
                value = (node.text or "").strip()
                if value not in allowed_edm_types:
                    result["valid"] = False
                    result["errors"].append(
                        f"Invalid edm:type value '{value}'. Expected one of: 3D, IMAGE, SOUND, TEXT, VIDEO."
                    )

            empty_resource_refs = doc.xpath("//*[@rdf:about=''] | //*[@rdf:resource='']", namespaces=ns)
            if empty_resource_refs:
                result["valid"] = False
                result["errors"].append("Invalid empty rdf:about or rdf:resource value found.")

            # Advanced Problem Pattern Validation (local validator equivalent)
            self._validate_problem_patterns(doc, ns, result)

        except ImportError:
            # lxml not available, do basic validation
            result['warnings'].append("lxml not installed - using basic XML validation only")
            try:
                ET.fromstring(xml_string)
            except ET.ParseError as e:
                result['valid'] = False
                result['errors'].append(f"XML Parse Error: {str(e)}")
        except Exception as e:
            result['warnings'].append(f"Validation warning: {str(e)}")

        return result

    def _validate_problem_patterns(self, doc, ns: Dict[str, str], result: Dict[str, Any]):
        """
        Implementation of local-edm-validator problem patterns (P2-P12).
        P1 is skipped as it requires multiple records.
        """
        titles = [t.text.strip() for t in doc.xpath('//dc:title', namespaces=ns) if t.text]
        descriptions = [d.text.strip() for d in doc.xpath('//dc:description', namespaces=ns) if d.text]

        for title in titles:
            # P2: Equal title and description
            if any(title == desc for desc in descriptions):
                result['warnings'].append(f"[{self.PROBLEM_PATTERNS['P2']['title']}] Title matches one of the descriptions.")

            # P3: Near-Identical title and description (simplified similarity check)
            for desc in descriptions:
                if title != desc and (title in desc or desc in title) and abs(len(title) - len(desc)) < 10:
                    result['warnings'].append(f"[{self.PROBLEM_PATTERNS['P3']['title']}] Title and description are nearly identical.")

            # P5: Unrecognisable title
            non_alnum = len([c for c in title if not c.isalnum() and not c.isspace()])
            if non_alnum > 5:
                result['warnings'].append(f"[{self.PROBLEM_PATTERNS['P5']['title']}] Title contains too many special characters.")

            # P6: Non-meaningful title
            if len(title) < 3:
                result['warnings'].append(f"[{self.PROBLEM_PATTERNS['P6']['title']}] Title is too short (< 3 chars).")

            # P12: Extremely long values
            if len(title) > 70:
                result['warnings'].append(f"[{self.PROBLEM_PATTERNS['P12']['title']}] Title is too long (> 70 chars).")

        # P7/P9: Description issues
        if not descriptions:
            result['warnings'].append(f"[{self.PROBLEM_PATTERNS['P7']['title']}] No description fields found.")
        else:
            for desc in descriptions:
                if len(desc) <= 50:
                    result['warnings'].append(f"[{self.PROBLEM_PATTERNS['P9']['title']}] Description is very short (<= 50 chars).")

    def validate_with_xsd(self, xml_string: str, xsd_path: Optional[str] = None) -> Dict[str, Any]:
        """Validate with the bundled RDF-wrapped EDM entry schema, offline."""
        schema_path = Path(xsd_path) if xsd_path else Path(__file__).resolve().parent.parent / "schema_xsds" / "EDM.xsd"
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        try:
            schema = etree.XMLSchema(etree.parse(str(schema_path), parser))
            document = etree.fromstring(xml_string.encode("utf-8"), parser)
            valid = schema.validate(document)
            return {"valid": valid, "errors": [error.message for error in schema.error_log], "skipped": False}
        except (etree.LxmlError, OSError, ValueError) as exc:
            return {"valid": False, "errors": [f"EDM schema validation failed: {exc}"], "skipped": False}

    def validate_with_schematron(self, xml_string: str, xslt_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Validates XML against a Schematron-compiled XSLT file.

        DISABLE NOTE: This validator is currently disabled due to inconsistent behavior
        with XSLT 2.0 rules in a 1.0 engine. local-edm-validator remains the source of truth.
        """
        return {
            'valid': True,
            'errors': [],
            'skipped': True,
            'message': "Schematron validation is currently disabled in favor of local-edm-validator validation (source of truth)."
        }

    def _append_unique(self, target: List[str], message: str) -> None:
        if message and message not in target:
            target.append(message)

    def _normalize_validator_message(self, message: Any) -> Dict[str, str]:
        if isinstance(message, dict):
            message_type = str(
                message.get("messageType")
                or message.get("type")
                or message.get("severity")
                or "INFO"
            ).upper()
            text = str(message.get("message") or message.get("text") or "").strip()
        else:
            message_type = "INFO"
            text = str(message or "").strip()
        return {"type": message_type, "message": text}

    def _normalize_local_validator_report(
        self,
        data: Dict[str, Any],
        *,
        remote_status: Any = "unknown",
    ) -> Dict[str, Any]:
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "infos": [],
            "messages": [],
            "remote_status": remote_status,
            "validator": "local-edm-validator",
            "validation_results": [],
            "problem_patterns": [],
            "step_timings": data.get("stepTimings") or [],
            "total_duration_millis": data.get("totalDurationMillis"),
            "raw": data,
        }

        timings_by_step = {}
        for timing in result["step_timings"]:
            if isinstance(timing, dict):
                step = str(timing.get("step") or "")
                timings_by_step[step] = timing.get("durationMillis")

        for step_result in data.get("validationResults", []) or []:
            if not isinstance(step_result, dict):
                continue
            step = str(step_result.get("step") or "UNKNOWN")
            status = str(step_result.get("status") or "UNKNOWN").upper()
            normalized_messages = [
                self._normalize_validator_message(message)
                for message in (step_result.get("messages") or [])
            ]
            normalized_step = {
                "step": step,
                "status": status,
                "valid": status != "FAILED",
                "messages": normalized_messages,
                "duration_millis": timings_by_step.get(step),
            }
            result["validation_results"].append(normalized_step)

            if status == "FAILED":
                result["valid"] = False

            for message in normalized_messages:
                text = message.get("message") or ""
                if not text:
                    continue
                message_type = message.get("type") or "INFO"
                prefixed = f"[{step}] {text}"
                result["messages"].append({**message, "step": step, "status": status})
                if message_type == "ERROR" or status == "FAILED":
                    result["valid"] = False
                    self._append_unique(result["errors"], prefixed)
                elif message_type == "WARN":
                    self._append_unique(result["warnings"], prefixed)
                else:
                    self._append_unique(result["infos"], prefixed)

        for problem in data.get("problemPatternList", []) or []:
            if not isinstance(problem, dict):
                continue
            description = problem.get("problemPatternDescription") or {}
            pattern_id = (
                description.get("problemPatternId")
                or problem.get("problemPatternId")
                or problem.get("id")
            )
            title = (
                description.get("problemPatternTitle")
                or problem.get("problemPatternTitle")
                or problem.get("title")
                or "Problem pattern detected"
            )
            normalized_problem = {
                "id": str(pattern_id or "").strip(),
                "title": str(title).strip(),
                "raw": problem,
            }
            result["problem_patterns"].append(normalized_problem)
            label = f"{normalized_problem['title']}"
            if normalized_problem["id"]:
                label = f"{label} ({normalized_problem['id']})"
            self._append_unique(result["warnings"], f"[Problem Pattern] {label}")

        return result

    def validate_with_local_edm_validator(
        self,
        xml_string: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Validate XML using local-edm-validator.

        Endpoint: POST /record/validation
        """
        from flask import current_app

        metadata = metadata or {}
        country = self.normalize_local_validator_country(metadata.get('country'))
        language = self.normalize_local_validator_language(metadata.get('language'))

        try:
            current_app.logger.info(
                "EdmService: Validating record with local-edm-validator. "
                "URL: %s, Country: %s, Language: %s",
                current_app.config.get("LOCAL_EDM_VALIDATOR_URL")
                or current_app.config.get("METIS_SANDBOX_URL"),
                country,
                language,
            )
            data = LocalEdmValidatorClient().validate_record(
                xml_string,
                country=country,
                language=language,
                continue_on_error=current_app.config.get(
                    "LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR",
                    True,
                ),
            )
            result = self._normalize_local_validator_report(data, remote_status=200)
        except LocalEdmValidatorClientError as e:
            logger.error("Local EDM validation failed: %s", e)
            result = {
                "valid": False,
                "errors": [f"Connection to Local EDM Validator failed: {str(e)}"],
                "warnings": [],
                "infos": [],
                "remote_status": "connection_failed",
                "validator": "local-edm-validator",
                "validation_results": [],
                "problem_patterns": [],
                "step_timings": [],
                "total_duration_millis": None,
            }

        return result

    def validate_with_metis(self, xml_string: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Compatibility wrapper for callers using the old method name."""
        return self.validate_with_local_edm_validator(xml_string, metadata=metadata)

    def validate_edm_document(
        self,
        xml_string: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        include_remote: bool = False,
    ) -> Dict[str, Any]:
        basic_result = self.validate_xml(xml_string)
        xsd_result = self.validate_with_xsd(xml_string)
        schematron_result = self.validate_with_schematron(xml_string)
        business_result = self.validate_edm_business_rules(xml_string)

        all_errors = list(basic_result.get("errors", []))
        all_warnings = list(basic_result.get("warnings", []))

        for err in xsd_result.get("errors", []):
            prefixed = f"[XSD] {err}"
            if prefixed not in all_errors:
                all_errors.append(prefixed)

        for err in schematron_result.get("errors", []):
            prefixed = f"[Schematron] {err}"
            if prefixed not in all_errors:
                all_errors.append(prefixed)

        for err in business_result.get("errors", []):
            prefixed = f"[Business] {err}"
            if prefixed not in all_errors:
                all_errors.append(prefixed)

        for warn in business_result.get("warnings", []):
            prefixed = f"[Business] {warn}"
            if prefixed not in all_warnings:
                all_warnings.append(prefixed)

        remote_result = None
        valid = (
            basic_result.get("valid", True)
            and xsd_result.get("valid", True)
            and schematron_result.get("valid", True)
            and business_result.get("valid", True)
        )

        if include_remote:
            remote_result = self.validate_with_local_edm_validator(xml_string, metadata=metadata)
            for err in remote_result.get("errors", []):
                prefixed = f"[Local EDM Validator] {err}"
                if prefixed not in all_errors:
                    all_errors.append(prefixed)
            for warn in remote_result.get("warnings", []):
                prefixed = f"[Local EDM Validator] {warn}"
                if prefixed not in all_warnings:
                    all_warnings.append(prefixed)
            valid = valid and remote_result.get("valid", True)

        return {
            "valid": valid,
            "errors": all_errors,
            "warnings": all_warnings,
            "details": {
                "basic": basic_result,
                "xsd": xsd_result,
                "schematron": schematron_result,
                "business": business_result,
                "remote": remote_result,
            },
        }

    # ==========================================================================
    # Template Rendering with Caching
    # ==========================================================================

    @lru_cache(maxsize=32)
    def _get_cached_jinja_env(self) -> jinja2.Environment:
        """Returns a cached Jinja2 environment for template rendering."""
        env = jinja2.Environment(
            autoescape=True,
            # Use DebugUndefined to allow templates to check for missing attributes
            # without throwing errors (enables {% if var %} checks)
            undefined=jinja2.DebugUndefined
        )
        return env

    def _get_template_helpers(self) -> Dict[str, Any]:
        """Returns all helper functions available in templates."""
        return {
            'map_type': self._map_zenodo_type_to_edm,
            'map_license': self._map_license_to_uri,
            'normalize_intended_usage_uri': self.normalize_intended_usage_uri,
            'normalize_digital_source_type_uri': self.normalize_digital_source_type_uri,
            'now': datetime.utcnow,
            'lang_tag': self.lang_tag,
            'iso_date': self.iso_date,
            'generate_uri': self.generate_uri,
            'generate_content_url': self.generate_content_url,
            'map_3d_type': self.map_3d_type,
            'is_oembed': self.is_oembed_viewer,
        }

    def _ensure_schema_namespace(self, xml_content: str) -> str:
        """
        Guarantee that rendered EDM XML declares the `schema` namespace when
        schema-prefixed elements are present (e.g. schema:digitalSourceType).
        This keeps legacy DB templates valid without requiring reseeding.
        """
        if not isinstance(xml_content, str):
            return xml_content
        if "<schema:" not in xml_content:
            return xml_content
        if "xmlns:schema=" in xml_content:
            return xml_content

        return re.sub(
            r"(<rdf:RDF\b[^>]*)(>)",
            r'\1 xmlns:schema="https://schema.org/"\2',
            xml_content,
            count=1,
        )

    def _build_default_dc_type(self, metadata: Dict[str, Any]) -> str:
        upload_type = ""
        if isinstance(metadata, dict):
            upload_type = str(
                metadata.get("resource_type")
                or metadata.get("upload_type")
                or ""
            ).strip()

        if upload_type:
            return upload_type
        return "Digital object"

    def _reorder_children_by_qname(self, parent, ordered_qnames: List[str]) -> None:
        """
        Reorder direct child elements of `parent` to match schema sequence order.
        Unknown elements are kept after known ones to preserve data.
        """
        ordered_set = set(ordered_qnames)
        grouped = {qname: [] for qname in ordered_qnames}
        unknown = []
        non_element_nodes = []

        for child in list(parent):
            if not isinstance(getattr(child, "tag", None), str):
                non_element_nodes.append(child)
                continue
            if child.tag in ordered_set:
                grouped[child.tag].append(child)
            else:
                unknown.append(child)

        for child in list(parent):
            parent.remove(child)

        for qname in ordered_qnames:
            for child in grouped[qname]:
                parent.append(child)

        for child in unknown:
            parent.append(child)

        for child in non_element_nodes:
            parent.append(child)

    def _normalize_structural_element_order(self, root, ns: Dict[str, str]) -> None:
        """
        Enforce EDM element ordering for key nodes so generated XML remains
        schema-compliant even when legacy templates emit out-of-order elements.
        """
        # edm:ProvidedCHO extends base types and must end with:
        # edm:pid*, edm:type, owl:sameAs*
        cho_pid_tag = f"{{{ns['edm']}}}pid"
        cho_edm_type_tag = f"{{{ns['edm']}}}type"
        cho_same_as_tag = f"{{{ns['owl']}}}sameAs"

        for cho in root.xpath("//edm:ProvidedCHO", namespaces=ns):
            base_children = []
            pid_children = []
            edm_type_children = []
            same_as_children = []
            non_element_nodes = []

            for child in list(cho):
                if not isinstance(getattr(child, "tag", None), str):
                    non_element_nodes.append(child)
                    continue
                if child.tag == cho_pid_tag:
                    pid_children.append(child)
                elif child.tag == cho_edm_type_tag:
                    edm_type_children.append(child)
                elif child.tag == cho_same_as_tag:
                    same_as_children.append(child)
                else:
                    base_children.append(child)

            for child in list(cho):
                cho.remove(child)

            for child in base_children:
                cho.append(child)
            for child in pid_children:
                cho.append(child)
            for child in edm_type_children:
                cho.append(child)
            for child in same_as_children:
                cho.append(child)
            for child in non_element_nodes:
                cho.append(child)

        # Full WebResource order from CONTEXTS.xsd::WebResourceType
        webresource_order = [
            f"{{{ns['edm']}}}pid",
            f"{{{ns['dc']}}}creator",
            f"{{{ns['dc']}}}description",
            f"{{{ns['dc']}}}format",
            f"{{{ns['dc']}}}rights",
            f"{{{ns['dc']}}}source",
            f"{{{ns['dc']}}}type",
            f"{{{ns['dc']}}}title",
            f"{{{ns['dc']}}}language",
            f"{{{ns['dcterms']}}}conformsTo",
            f"{{{ns['dcterms']}}}created",
            f"{{{ns['dcterms']}}}extent",
            f"{{{ns['dcterms']}}}hasPart",
            f"{{{ns['dcterms']}}}isFormatOf",
            f"{{{ns['dcterms']}}}isPartOf",
            f"{{{ns['dcterms']}}}issued",
            f"{{{ns['dcterms']}}}temporal",
            f"{{{ns['edm']}}}isNextInSequence",
            f"{{{ns['edm']}}}rights",
            f"{{{ns['owl']}}}sameAs",
            f"{{{ns['rdf']}}}type",
            f"{{{ns['edm']}}}codecName",
            f"{{{ns['ebucore']}}}hasMimeType",
            f"{{{ns['ebucore']}}}fileByteSize",
            f"{{{ns['ebucore']}}}duration",
            f"{{{ns['ebucore']}}}width",
            f"{{{ns['ebucore']}}}height",
            f"{{{ns['edm']}}}spatialResolution",
            f"{{{ns['ebucore']}}}sampleSize",
            f"{{{ns['ebucore']}}}sampleRate",
            f"{{{ns['ebucore']}}}bitRate",
            f"{{{ns['ebucore']}}}frameRate",
            f"{{{ns['edm']}}}hasColorSpace",
            f"{{{ns['edm']}}}componentColor",
            f"{{{ns['edm']}}}pointCount",
            f"{{{ns['edm']}}}polygonCount",
            f"{{{ns['edm']}}}vertexCount",
            f"{{{ns['rdfs']}}}seeAlso",
            f"{{{ns['ebucore']}}}orientation",
            f"{{{ns['ebucore']}}}audioChannelNumber",
            f"{{{ns['dcterms']}}}isReferencedBy",
            f"{{{ns['edm']}}}preview",
            f"{{{ns['svcs']}}}has_service",
            f"{{{ns['edm']}}}type",
            f"{{{ns['schema']}}}digitalSourceType",
            f"{{{ns['edm']}}}intendedUsage",
        ]

        for web_resource in root.xpath("//edm:WebResource", namespaces=ns):
            self._reorder_children_by_qname(web_resource, webresource_order)

        aggregation_order = [
            f"{{{ns[prefix]}}}{name}" for prefix, name in [
                ("edm", "aggregatedCHO"), ("edm", "dataProvider"), ("edm", "hasView"),
                ("edm", "isShownAt"), ("edm", "isShownBy"), ("edm", "object"),
                ("edm", "provider"), ("dc", "rights"), ("edm", "rights"),
                ("edm", "ugc"), ("edm", "intermediateProvider"),
                ("dcterms", "created"), ("dcterms", "modified"),
            ]
        ]
        for aggregation in root.xpath("//ore:Aggregation", namespaces=ns):
            self._reorder_children_by_qname(aggregation, aggregation_order)

    def _ensure_minimum_viable_edm(self, xml_content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Safety pass that normalizes controlled vocab URIs and injects minimum
        EDM elements so upload workflows always produce a baseline-valid record.
        """
        metadata = metadata if isinstance(metadata, dict) else {}
        try:
            from lxml import etree
        except Exception:
            return xml_content

        try:
            root = etree.fromstring(xml_content.encode("utf-8"))
        except Exception:
            return xml_content

        ns = {
            "rdf": self.namespaces["rdf"],
            "edm": self.namespaces["edm"],
            "dc": self.namespaces["dc"],
            "dcterms": self.namespaces["dcterms"],
            "ore": self.namespaces["ore"],
            "schema": self.namespaces["schema"],
            "owl": "http://www.w3.org/2002/07/owl#",
            "ebucore": "http://www.ebu.ch/metadata/ontologies/ebucore/ebucore#",
            "rdfs": self.namespaces["rdfs"],
            "svcs": self.namespaces["svcs"],
            "skos": self.namespaces["skos"],
        }
        rdf_resource_attr = f"{{{ns['rdf']}}}resource"
        rdf_about_attr = f"{{{ns['rdf']}}}about"

        def _is_missing_text(value: Any) -> bool:
            text = str(value or "").strip()
            if not text:
                return True
            if text.lower() in {"nan", "none", "null", "nat", "<na>"}:
                return True
            if text.startswith("{{ no such element:"):
                return True
            return False

        def _metadata_count(field_name: str) -> Optional[str]:
            raw_value = metadata.get(field_name)
            if _is_missing_text(raw_value):
                return None
            text = str(raw_value).strip().replace(",", "")
            if text.endswith(".0") and text[:-2].isdigit():
                return text[:-2]
            if text.isdigit():
                return text
            return None

        fallback_title = str(metadata.get("title") or metadata.get("record_title") or "Untitled record").strip()
        if _is_missing_text(fallback_title):
            fallback_title = "Untitled record"

        cho_created = None
        for date_field in ("cho_created", "date", "dcterms:created", "created"):
            raw_date = metadata.get(date_field)
            if _is_missing_text(raw_date):
                continue
            cho_created = self.iso_date(str(raw_date).strip())
            break

        vertex_count = _metadata_count("vertex_count")
        polygon_count = _metadata_count("polygon_count")
        point_count = _metadata_count("point_count")

        try:
            default_rights_uri = self._map_license_to_uri(str(metadata.get("license") or ""))
        except Exception:
            default_rights_uri = "http://rightsstatements.org/vocab/CNE/1.0/"

        cho_nodes = root.xpath("//edm:ProvidedCHO", namespaces=ns)
        if not cho_nodes:
            cho = etree.SubElement(root, f"{{{ns['edm']}}}ProvidedCHO")
            cho.set(rdf_about_attr, "#providedCHO")
            cho_nodes = [cho]
        else:
            cho = cho_nodes[0]

        for cho_node in cho_nodes:
            titles = cho_node.xpath("./dc:title", namespaces=ns)
            has_title = False
            for title in titles:
                if _is_missing_text(title.text):
                    title.text = ""
                else:
                    has_title = True
            if not has_title:
                if titles:
                    titles[0].text = fallback_title
                else:
                    title_node = etree.SubElement(cho_node, f"{{{ns['dc']}}}title")
                    title_node.text = fallback_title

            if cho_created:
                created_nodes = cho_node.xpath("./dcterms:created", namespaces=ns)
                if created_nodes:
                    if _is_missing_text(created_nodes[0].text):
                        created_nodes[0].text = cho_created
                else:
                    created_node = etree.SubElement(cho_node, f"{{{ns['dcterms']}}}created")
                    created_node.text = cho_created

            creator_nodes = cho_node.xpath("./dc:creator", namespaces=ns)
            has_creator = any(
                bool(node.get(rdf_resource_attr))
                or not _is_missing_text(node.text)
                for node in creator_nodes
            )
            if not has_creator:
                creator_node = etree.SubElement(cho_node, f"{{{ns['dc']}}}creator")
                creator_node.set(rdf_resource_attr, "#agent_unknown")

            classification_nodes = cho_node.xpath(
                "./dc:subject | ./dc:type | ./dcterms:temporal | ./dcterms:spatial",
                namespaces=ns,
            )
            has_classification = False
            for node in classification_nodes:
                if (node.text or "").strip() or node.get(rdf_resource_attr):
                    has_classification = True
                    break
            if not has_classification:
                dc_type_node = etree.SubElement(cho_node, f"{{{ns['dc']}}}type")
                dc_type_node.text = self._build_default_dc_type(metadata)

            edm_type_nodes = cho_node.xpath("./edm:type", namespaces=ns)
            if not any((node.text or "").strip() for node in edm_type_nodes):
                edm_type_node = etree.SubElement(cho_node, f"{{{ns['edm']}}}type")
                edm_type_node.text = str(metadata.get("edm_type_override") or "TEXT").upper()

        primary_cho = cho_nodes[0]
        cho_about = primary_cho.get(rdf_about_attr) or "#providedCHO"

        agg_nodes = root.xpath("//ore:Aggregation", namespaces=ns)
        if not agg_nodes:
            agg = etree.SubElement(root, f"{{{ns['ore']}}}Aggregation")
            agg.set(rdf_about_attr, f"{cho_about}#aggregation")
            agg_nodes = [agg]
        for agg in agg_nodes:
            if not agg.xpath("./edm:aggregatedCHO", namespaces=ns):
                aggregated_cho = etree.SubElement(agg, f"{{{ns['edm']}}}aggregatedCHO")
                aggregated_cho.set(rdf_resource_attr, cho_about)

            if not agg.xpath("./edm:dataProvider", namespaces=ns):
                provider = etree.SubElement(agg, f"{{{ns['edm']}}}dataProvider")
                provider.text = str(metadata.get("provider") or "Zenodo")

            rights_nodes = agg.xpath("./edm:rights", namespaces=ns)
            if not rights_nodes:
                rights = etree.SubElement(agg, f"{{{ns['edm']}}}rights")
                rights.set(rdf_resource_attr, default_rights_uri)
            else:
                for rights in rights_nodes:
                    if not rights.get(rdf_resource_attr):
                        rights.set(rdf_resource_attr, default_rights_uri)

        for shown_by in root.xpath("//ore:Aggregation/edm:isShownBy", namespaces=ns):
            viewer_uri = shown_by.get(rdf_resource_attr) or ""
            if "3drepo.eu/modelviewer" in viewer_uri.lower():
                shown_by.getparent().remove(shown_by)

        for wr in root.xpath("//edm:WebResource", namespaces=ns):
            wr_uri = wr.get(rdf_about_attr) or ""
            if "3drepo.eu/modelviewer" in wr_uri.lower():
                wr.getparent().remove(wr)

        for service_node in root.xpath("//svcs:Service", namespaces=ns):
            service_uri = service_node.get(rdf_about_attr) or ""
            if "3drepo.eu" in service_uri.lower():
                service_node.getparent().remove(service_node)

        has_view_nodes = root.xpath("//ore:Aggregation/edm:hasView", namespaces=ns)
        has_view_uris = [
            node.get(rdf_resource_attr)
            for node in has_view_nodes
            if node.get(rdf_resource_attr)
        ]
        shown_by_nodes = root.xpath("//ore:Aggregation/edm:isShownBy", namespaces=ns)
        shown_by_uris = [
            node.get(rdf_resource_attr)
            for node in shown_by_nodes
            if node.get(rdf_resource_attr)
        ]

        # Ensure all referenced resources (hasView/isShownBy) are explicitly described.
        for resource_uri in has_view_uris + shown_by_uris:
            wr_nodes = root.xpath(f"//edm:WebResource[@rdf:about='{resource_uri}']", namespaces=ns)
            if wr_nodes:
                continue
            web_resource = etree.SubElement(root, f"{{{ns['edm']}}}WebResource")
            web_resource.set(rdf_about_attr, resource_uri)

        intended_usage_uri = self.normalize_intended_usage_uri(metadata.get("intended_usage"))
        digital_source_type_uri = self.normalize_digital_source_type_uri(metadata.get("digital_source_type"))
        model_type_uri = self.map_3d_type(metadata)
        try:
            from flask import current_app

            emit_3d_advisory_fields = bool(
                current_app.config.get("EMIT_EUROPEANA_3D_ADVISORY_FIELDS", False)
            )
        except RuntimeError:
            emit_3d_advisory_fields = False

        web_resources = root.xpath("//edm:WebResource", namespaces=ns)
        for wr in web_resources:
            about = wr.get(rdf_about_attr, "")
            mime_guess = self._infer_mime_type_from_url(about)
            is_3d_file = self._looks_like_3d_resource_uri(about)
            is_viewer = self.is_oembed_viewer(about)

            if not emit_3d_advisory_fields:
                for advisory_node in wr.xpath(
                    "./schema:digitalSourceType | ./edm:intendedUsage | "
                    "./edm:pointCount | ./edm:polygonCount | ./edm:vertexCount",
                    namespaces=ns,
                ):
                    advisory_node.getparent().remove(advisory_node)

            format_nodes = wr.xpath("./dc:format", namespaces=ns)
            if format_nodes:
                existing_format = (format_nodes[0].text or "").strip().lower()
                if is_viewer:
                    format_nodes[0].text = "text/html"
                elif mime_guess != "application/octet-stream":
                    should_replace = (
                        existing_format in {"", "application/octet-stream"}
                        or (
                            mime_guess.startswith("image/")
                            and existing_format.startswith("image/")
                            and existing_format != mime_guess
                        )
                    )
                    if should_replace:
                        format_nodes[0].text = mime_guess
            elif is_viewer:
                fmt = etree.SubElement(wr, f"{{{ns['dc']}}}format")
                fmt.text = "text/html"
            elif mime_guess != "application/octet-stream":
                fmt = etree.SubElement(wr, f"{{{ns['dc']}}}format")
                fmt.text = mime_guess

            rights_nodes = wr.xpath("./edm:rights", namespaces=ns)
            if not rights_nodes:
                rights_node = etree.SubElement(wr, f"{{{ns['edm']}}}rights")
                rights_node.set(rdf_resource_attr, default_rights_uri)
            else:
                for rights_node in rights_nodes:
                    if not rights_node.get(rdf_resource_attr):
                        rights_node.set(rdf_resource_attr, default_rights_uri)

            if is_3d_file:
                edm_type_nodes = wr.xpath("./edm:type", namespaces=ns)
                if not edm_type_nodes:
                    edm_type_node = etree.SubElement(wr, f"{{{ns['edm']}}}type")
                    edm_type_node.text = "3D"
                elif _is_missing_text(edm_type_nodes[0].text):
                    edm_type_nodes[0].text = "3D"

                dc_type_resource_nodes = wr.xpath("./dc:type[@rdf:resource]", namespaces=ns)
                if not dc_type_resource_nodes:
                    dc_type_node = etree.SubElement(wr, f"{{{ns['dc']}}}type")
                    dc_type_node.set(rdf_resource_attr, model_type_uri)

                if emit_3d_advisory_fields:
                    digital_source_nodes = wr.xpath("./schema:digitalSourceType", namespaces=ns)
                    if digital_source_type_uri and not digital_source_nodes:
                        digital_source_node = etree.SubElement(wr, f"{{{ns['schema']}}}digitalSourceType")
                        digital_source_node.set(rdf_resource_attr, digital_source_type_uri)
                    elif digital_source_type_uri and not digital_source_nodes[0].get(rdf_resource_attr):
                        digital_source_nodes[0].set(rdf_resource_attr, digital_source_type_uri)

                    intended_usage_nodes = wr.xpath("./edm:intendedUsage", namespaces=ns)
                    if intended_usage_uri and not intended_usage_nodes:
                        intended_usage_node = etree.SubElement(wr, f"{{{ns['edm']}}}intendedUsage")
                        intended_usage_node.set(rdf_resource_attr, intended_usage_uri)
                    elif intended_usage_uri and not intended_usage_nodes[0].get(rdf_resource_attr):
                        intended_usage_nodes[0].set(rdf_resource_attr, intended_usage_uri)

                    if vertex_count and not wr.xpath("./edm:vertexCount", namespaces=ns):
                        vertex_node = etree.SubElement(wr, f"{{{ns['edm']}}}vertexCount")
                        vertex_node.text = vertex_count
                    if polygon_count and not wr.xpath("./edm:polygonCount", namespaces=ns):
                        polygon_node = etree.SubElement(wr, f"{{{ns['edm']}}}polygonCount")
                        polygon_node.text = polygon_count
                    if point_count and not wr.xpath("./edm:pointCount", namespaces=ns):
                        point_node = etree.SubElement(wr, f"{{{ns['edm']}}}pointCount")
                        point_node.text = point_count

            if is_viewer:
                service_info = self._resolve_oembed_service(about) or {}
                service_url = service_info.get("endpoint")
                service_label = service_info.get("label") or "3D Viewer"
                conforms_nodes = wr.xpath("./dcterms:conformsTo", namespaces=ns)
                if conforms_nodes:
                    conforms_nodes[0].set(rdf_resource_attr, "https://oembed.com/")
                else:
                    conforms_node = etree.SubElement(wr, f"{{{ns['dcterms']}}}conformsTo")
                    conforms_node.set(rdf_resource_attr, "https://oembed.com/")
                if service_url:
                    has_service_nodes = wr.xpath("./svcs:has_service", namespaces=ns)
                    if has_service_nodes:
                        has_service_nodes[0].set(rdf_resource_attr, service_url)
                    else:
                        has_service = etree.SubElement(wr, f"{{{ns['svcs']}}}has_service")
                        has_service.set(rdf_resource_attr, service_url)

                    service_nodes = root.xpath(f"//svcs:Service[@rdf:about='{service_url}']", namespaces=ns)
                    if service_nodes:
                        service_node = service_nodes[0]
                    else:
                        service_node = etree.SubElement(root, f"{{{ns['svcs']}}}Service")
                        service_node.set(rdf_about_attr, service_url)

                    conforms_nodes = service_node.xpath("./dcterms:conformsTo", namespaces=ns)
                    if conforms_nodes:
                        conforms_nodes[0].set(rdf_resource_attr, "https://oembed.com/")
                    else:
                        conforms_node = etree.SubElement(service_node, f"{{{ns['dcterms']}}}conformsTo")
                        conforms_node.set(rdf_resource_attr, "https://oembed.com/")

                    label_nodes = service_node.xpath("./rdfs:label", namespaces=ns)
                    if label_nodes:
                        if _is_missing_text(label_nodes[0].text):
                            label_nodes[0].text = service_label
                    else:
                        label_node = etree.SubElement(service_node, f"{{{ns['rdfs']}}}label")
                        label_node.text = service_label

        for node in root.xpath("//edm:WebResource/edm:intendedUsage", namespaces=ns):
            normalized_uri = self.normalize_intended_usage_uri(node.get(rdf_resource_attr))
            if normalized_uri:
                node.set(rdf_resource_attr, normalized_uri)
            else:
                node.getparent().remove(node)

        for node in root.xpath("//edm:WebResource/schema:digitalSourceType", namespaces=ns):
            normalized_uri = self.normalize_digital_source_type_uri(node.get(rdf_resource_attr))
            if normalized_uri:
                node.set(rdf_resource_attr, normalized_uri)
            else:
                node.getparent().remove(node)

        # Ensure dcterms:isFormatOf linkage between Viewer and original File
        # Determine the primary 3D file URI (the object being represented)
        primary_file_uri = None
        if has_view_nodes:
            # We usually put the main 3D file first or among the hasView nodes
            for hv in has_view_nodes:
                hv_uri = hv.get(rdf_resource_attr)
                hv_wr = root.xpath(f"//edm:WebResource[@rdf:about='{hv_uri}']", namespaces=ns)
                if (
                    hv_wr
                    and hv_wr[0].xpath("./edm:type", namespaces=ns)
                    and (hv_wr[0].xpath("./edm:type", namespaces=ns)[0].text or "").strip().upper() == "3D"
                ):
                    primary_file_uri = hv_uri
                    break
        if not primary_file_uri:
            for hv_uri in has_view_uris:
                if self._looks_like_3d_resource_uri(hv_uri):
                    primary_file_uri = hv_uri
                    break

        if shown_by_nodes:
            viewer_uri = shown_by_nodes[0].get(rdf_resource_attr)
            if viewer_uri and self.is_oembed_viewer(viewer_uri):
                # Link Viewer to File
                if primary_file_uri:
                    viewer_wr_nodes = root.xpath(f"//edm:WebResource[@rdf:about='{viewer_uri}']", namespaces=ns)
                    if viewer_wr_nodes:
                        viewer_wr = viewer_wr_nodes[0]
                        if not viewer_wr.xpath("./dcterms:isFormatOf", namespaces=ns):
                            is_format_of = etree.SubElement(viewer_wr, f"{{{ns['dcterms']}}}isFormatOf")
                            is_format_of.set(rdf_resource_attr, primary_file_uri)

        # Link all IMAGE WebResources (thumbnails) to the 3D file
        if primary_file_uri:
            all_web_resources = root.xpath("//edm:WebResource", namespaces=ns)
            for wr in all_web_resources:
                wr_uri = wr.get(rdf_about_attr)
                if wr_uri == primary_file_uri:
                    continue

                # If it's an image, link it
                fmt = wr.xpath("./dc:format", namespaces=ns)
                if fmt and "image/" in (fmt[0].text or ""):
                    if not wr.xpath("./dcterms:isFormatOf", namespaces=ns):
                        is_format_of = etree.SubElement(wr, f"{{{ns['dcterms']}}}isFormatOf")
                        is_format_of.set(rdf_resource_attr, primary_file_uri)

        # Ensure fallback "Unknown" agent exists when referenced.
        unknown_agent_ref_used = bool(
            root.xpath("//edm:ProvidedCHO/dc:creator[@rdf:resource='#agent_unknown']", namespaces=ns)
        )
        if unknown_agent_ref_used and not root.xpath("//edm:Agent[@rdf:about='#agent_unknown']", namespaces=ns):
            unknown_agent = etree.SubElement(root, f"{{{ns['edm']}}}Agent")
            unknown_agent.set(rdf_about_attr, "#agent_unknown")
            pref_label = etree.SubElement(unknown_agent, f"{{{ns['skos']}}}prefLabel")
            pref_label.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
            pref_label.text = "Unknown"

        self._normalize_structural_element_order(root, ns)

        repaired = etree.tostring(root, encoding="unicode")
        return self._ensure_schema_namespace(repaired)

    def render_template(
        self,
        template_id: int,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        main_file_key: Optional[str] = None,
        additional_files: Optional[List[Dict[str, Any]]] = None,
        allow_placeholder_thumbnail: bool = False,
    ) -> Optional[str]:
        """
        Renders an EDM XML from a stored Jinja2 template.

        Enhanced with:
        - Template caching
        - Granular error reporting
        - Additional helper functions
        - Main file selection logic
        - Smart Template Switching
        """
        from database.database import db
        from database.models import LodTemplate
        from flask import current_app

        try:
            # Reset URI counters for each render
            self.reset_uri_counters()

            template = db.session.get(LodTemplate, template_id)
            if not template:
                logger.error(f"LodTemplate {template_id} not found.")
                return None

            # 1. Normalize Files
            files = self._normalize_zenodo_files(zenodo_record)

            # Merge additional files (e.g. locally rendered previews not yet uploaded)
            if additional_files:
                files.extend(additional_files)

            # Update zenodo_record with normalized files
            if isinstance(zenodo_record, dict):
                 zenodo_record['files'] = files

            # 2. Determine Main File (Selection OR Fallback)
            main_file = None
            if main_file_key:
                # Find requested file
                main_file = next((f for f in files if (f.get('key') or f.get('filename')) == main_file_key), None)

                # If not found but we have a key, use fallback for THIS key immediately
                # to avoid smart selection picking a thumbnail instead of our intended main file.
                if not main_file:
                     main_file = {'key': main_file_key, 'filename': main_file_key, 'size': 0}

            if not main_file:
                # Smart selection (only if no key was provided)
                main_file = self._select_smart_primary_file(files, metadata)

            # Absolute fallback if still nothing (e.g. no key AND no files)
            if not main_file:
                  main_file = {'key': 'unknown_file', 'filename': 'unknown_file', 'size': 0}
            # ---------------------------------------------------------

            # 3. Select Thumbnail (Must be different from main file)
            thumbnail_files = self._select_thumbnail_files(
                files,
                main_file=main_file,
                metadata=metadata,
                allow_placeholder=allow_placeholder_thumbnail,
            )
            thumbnail_file = thumbnail_files[0] if thumbnail_files else None

            # 4. Enrich Metadata & Generate URLs
            # Main File
            main_file = self._enrich_file_metadata(main_file, metadata)

            # Generate URLs for Main File
            record_id = str(zenodo_record.get('id', ''))

            # Detect Sandbox mode from record links
            is_sandbox_curr = "sandbox.zenodo.org" in zenodo_record.get('links', {}).get('html', '')

            # Content URL
            c_url = self.get_file_content_url(main_file, record_id, is_sandbox=is_sandbox_curr)
            main_file['content_url'] = c_url

            # Viewer URL (for edm:isShownBy) is only used for real oEmbed viewers.
            viewer_url = str(main_file.get('viewer_url') or '').strip()
            main_file['viewer_url'] = viewer_url if self.is_oembed_viewer(viewer_url) else ""

            main_file['url'] = main_file['viewer_url'] or c_url # Legacy compat

            # Thumbnail
            enriched_thumbnail_files: List[Dict[str, Any]] = []
            for thumb in thumbnail_files:
                enriched_thumb = self._enrich_file_metadata(thumb, metadata)
                t_url = self.get_file_content_url(
                    enriched_thumb,
                    record_id,
                    is_sandbox=is_sandbox_curr,
                )
                enriched_thumb['content_url'] = t_url
                enriched_thumb['url'] = t_url
                enriched_thumbnail_files.append(enriched_thumb)

            thumbnail_file = enriched_thumbnail_files[0] if enriched_thumbnail_files else None
            additional_thumbnail_files = enriched_thumbnail_files[1:] if len(enriched_thumbnail_files) > 1 else []

            # Enriched List (for template iteration if needed)
            enriched_files = [self._enrich_file_metadata(f, metadata) for f in files]

            # 5. Smart Template Switching
            # If we have a 3D main file, ensure we use the 3D template regardless of the initial selection.
            if main_file.get('is_3d') and template.name != "3D Model":
                 logger.info(f"Smart Switch: Detected 3D content ({main_file.get('filename')}). Switching to 3D Model Template.")
                 from database.models import LodTemplate
                 template_3d = LodTemplate.query.filter_by(name="3D Model").first()
                 if template_3d:
                     template = template_3d

            if isinstance(metadata, DotDict):
                metadata = dict(metadata)
            if isinstance(metadata, dict):
                metadata = self._normalize_edm_metadata_vocabularies(metadata)

            # 6. Wrap in DotDicts for Template Compatibility
            if isinstance(zenodo_record, dict) or isinstance(zenodo_record, DotDict):
                # We copy to avoid issues with session attached objects or caching
                z_copy = zenodo_record.copy() if isinstance(zenodo_record, dict) else zenodo_record
                z_copy['enriched_files'] = [DotDict(f) for f in enriched_files]
                zenodo_record = DotDict(z_copy)

            if main_file and isinstance(main_file, dict):
                main_file = DotDict(main_file)

            if thumbnail_file and isinstance(thumbnail_file, dict):
                thumbnail_file = DotDict(thumbnail_file)
            thumbnail_files = [DotDict(thumb) for thumb in enriched_thumbnail_files]
            additional_thumbnail_files = [DotDict(thumb) for thumb in additional_thumbnail_files]

            if isinstance(metadata, dict):
                metadata = DotDict(metadata)

            # Get cached environment
            env = self._get_cached_jinja_env()

            # Compile template
            try:
                jinja_template = env.from_string(template.content)
            except jinja2.TemplateSyntaxError as e:
                error_msg = f"Template syntax error at line {e.lineno}: {e.message}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Prepare context
            helpers = self._get_template_helpers()

            # Render
            xml_content = jinja_template.render(
                metadata=metadata,
                zenodo=zenodo_record,
                helpers=helpers,
                main_file=main_file,
                thumbnail_file=thumbnail_file,
                thumbnail_files=thumbnail_files,
                additional_thumbnail_files=additional_thumbnail_files,
            )
            xml_content = self._ensure_schema_namespace(xml_content)

            return xml_content
        except Exception as e:
            logger.error(f"Template rendering failed: {e}", exc_info=True)
            return None

    def validate_edm_business_rules(self, xml_string: str) -> Dict[str, Any]:
        """
        Validates EDM XML against complex business rules using Python (fallback for Schematron).
        Specifically checks rights statements and mandatory fields.
        """
        import re
        from lxml import etree

        result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }

        try:
            doc = etree.fromstring(xml_string.encode('utf-8'))
            ns = {
                'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                'edm': 'http://www.europeana.eu/schemas/edm/',
                'dc': 'http://purl.org/dc/elements/1.1/',
                'ore': 'http://www.openarchives.org/ore/terms/',
                'cc': 'http://creativecommons.org/ns#'
            }

            # 1. Validate edm:rights URIs
            rights_elements = doc.xpath('//edm:rights/@rdf:resource', namespaces=ns)

            # Common patterns from Europeana schematron
            cc_pattern = r'^https?://creativecommons\.org/(licenses|publicdomain)/.*'
            rs_pattern = r'^https?://rightsstatements\.org/(vocab|page)/.*'

            for uri in rights_elements:
                if uri == "None" or not uri:
                    result['valid'] = False
                    result['errors'].append("Invalid Rights Statement: URI cannot be 'None' or empty.")
                elif not (re.match(cc_pattern, uri) or re.match(rs_pattern, uri)):
                    # Check if it's a known non-standard but allowed URI if any, else warning
                    result['warnings'].append(f"Non-standard Rights Statement URI: {uri}. Europeana usually expects CC or RightsStatements.org URIs.")

            # 2. Check for mandatory fields in Proxy (TEXT records need language)
            proxies = doc.xpath('//ore:Proxy', namespaces=ns)
            for proxy in proxies:
                edm_type = proxy.xpath('string(edm:type)', namespaces=ns)
                if edm_type == 'TEXT':
                    languages = proxy.xpath('dc:language', namespaces=ns)
                    if not languages:
                        result['valid'] = False
                        result['errors'].append(f"Mandatory Field Missing: Proxy with edm:type='TEXT' must have a dc:language element.")

            # 3. Check for at least one title or description in Proxy
            for proxy in proxies:
                titles = proxy.xpath('dc:title', namespaces=ns)
                descriptions = proxy.xpath('dc:description', namespaces=ns)
                if not titles and not descriptions:
                    result['valid'] = False
                    result['errors'].append("Mandatory Field Missing: Proxy must have at least a dc:title or dc:description.")

        except Exception as e:
            result['valid'] = False
            result['errors'].append(f"Business Rule Validation Error: {e}")

        return result

    def generate_edm_xml(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        template_id: Optional[int] = None,
        main_file_key: Optional[str] = None,
        validate: bool = True,
        additional_files: Optional[List[Dict[str, Any]]] = None,
        allow_placeholder_thumbnail: bool = False,
    ) -> str:
        """
        Main entry point for generating EDM XML.

        Args:
            metadata: Metadata dictionary.
            zenodo_record: Zenodo record dictionary.
            template_id: Optional template ID override.
            main_file_key: Optional main file key override.
            validate: If True, performs XSD validation on the generated XML.
        """
        result = self.generate_edm_xml_with_report(
            metadata=metadata,
            zenodo_record=zenodo_record,
            template_id=template_id,
            main_file_key=main_file_key,
            validate=validate,
            additional_files=additional_files,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
        )
        return result["content"]

    def generate_edm_xml_with_report(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        template_id: Optional[int] = None,
        main_file_key: Optional[str] = None,
        validate: bool = True,
        additional_files: Optional[List[Dict[str, Any]]] = None,
        allow_placeholder_thumbnail: bool = False,
    ) -> Dict[str, Any]:
        """
        Generates EDM XML and reports whether minimum-viable safeguards altered
        the rendered template output.
        """
        from database.lod_template_bootstrap import ensure_default_lod_templates

        ensure_default_lod_templates()

        # Convert dictionary inputs to DotDict for easier access in Jinja2
        if isinstance(metadata, dict) and not isinstance(metadata, DotDict):
            metadata = DotDict(metadata)
        if isinstance(zenodo_record, dict) and not isinstance(zenodo_record, DotDict):
            zenodo_record = DotDict(zenodo_record)

        # Determine template
        from database.database import db
        from database.models import LodTemplate

        if not template_id:
            # Use default template
            default = LodTemplate.query.filter_by(is_default=True, standard="edm").first()
            if default:
                template_id = default.id
            else:
                # Fallback to first available
                first = LodTemplate.query.filter_by(standard="edm").first()
                if first:
                    template_id = first.id
                else:
                    raise ValueError("No EDM templates found in database")

        # Render
        rendered = self.render_template(
            template_id,
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            additional_files=additional_files,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
        )
        if not rendered:
            raise ValueError("Template rendering returned empty result")
        repaired = self._ensure_minimum_viable_edm(
            rendered,
            metadata if isinstance(metadata, dict) else dict(metadata),
        )
        minimum_viable_applied = repaired != rendered

        # Optional validation
        validation = None
        if validate:
            from flask import current_app
            validation = self.validate_edm_document(
                repaired,
                metadata=metadata,
                include_remote=current_app.config.get(
                    "LOCAL_EDM_VALIDATOR_REQUIRED",
                    False,
                ) or current_app.config.get(
                    "ENABLE_LOCAL_EDM_VALIDATION",
                    current_app.config.get("ENABLE_METIS_VALIDATION", True),
                ),
            )
            if not validation.get("valid", True):
                logger.warning(
                    "Generated EDM XML failed validation for record %s: %s",
                    zenodo_record.get("id"),
                    validation.get("errors", [])[:3],
                )

        return {
            "content": repaired,
            "minimum_viable_applied": minimum_viable_applied,
            "validation": validation,
        }



    # ==========================================================================
    # Configuration Methods
    # ==========================================================================

    def _get_mapping_config(self):
        """
        Retrieves the EDM mapping configuration from the database.
        Returns a dictionary with 'types' and 'licenses' keys.
        """
        from flask import current_app
        from database.database import db
        from database.models import SystemConfig
        import json

        try:
            config_entry = db.session.get(SystemConfig, "edm_mapping_config")
            if config_entry and config_entry.value:
                return json.loads(config_entry.value)
        except Exception as e:
            current_app.logger.warning(f"Failed to load EDM mapping config: {e}")

        return None

    def _map_zenodo_type_to_edm(self, zenodo_type: str) -> str:
        """Maps Zenodo upload types to EDM types."""
        # Default mapping
        mapping = {
            "image": "IMAGE",
            "video": "VIDEO",
            "dataset": "TEXT",
            "publication": "TEXT",
            "poster": "IMAGE",
            "presentation": "TEXT",
            "software": "TEXT",
            "lesson": "TEXT",
            "physicalobject": "3D",
            "3d": "3D",
            "3d model": "3D",
            "3dmodel": "3D",
            "model3d": "3D",
            "model": "3D",
            "audio": "SOUND",
            "sound": "SOUND",
            "document": "TEXT",
            "data": "TEXT",
        }

        # Override with dynamic config if available
        config = self._get_modality_config()
        if config and "zenodo_types" in config:
            mapping.update(config["zenodo_types"])

        if not zenodo_type or not isinstance(zenodo_type, str):
            return "TEXT"

        return mapping.get(zenodo_type.lower(), "TEXT")

    def _map_license_to_uri(self, license_id: str) -> str:
        """Maps Zenodo license IDs to standard Rights Statements or CC URIs."""
        if not license_id:
            return "http://rightsstatements.org/vocab/CNE/1.0/"

        license_id = license_id.lower()

        # Extended mapping including versions
        mapping = {
            # Creative Commons 4.0
            "cc-by-4.0": "http://creativecommons.org/licenses/by/4.0/",
            "cc-by-sa-4.0": "http://creativecommons.org/licenses/by-sa/4.0/",
            "cc-by-nc-4.0": "http://creativecommons.org/licenses/by-nc/4.0/",
            "cc-by-nd-4.0": "http://creativecommons.org/licenses/by-nd/4.0/",
            "cc-by-nc-sa-4.0": "http://creativecommons.org/licenses/by-nc-sa/4.0/",
            "cc-by-nc-nd-4.0": "http://creativecommons.org/licenses/by-nc-nd/4.0/",

            # Creative Commons 4.0 (short codes)
            "cc-by": "http://creativecommons.org/licenses/by/4.0/",
            "cc-by-sa": "http://creativecommons.org/licenses/by-sa/4.0/",
            "cc-by-nc": "http://creativecommons.org/licenses/by-nc/4.0/",
            "cc-by-nd": "http://creativecommons.org/licenses/by-nd/4.0/",
            "cc-by-nc-sa": "http://creativecommons.org/licenses/by-nc-sa/4.0/",
            "cc-by-nc-nd": "http://creativecommons.org/licenses/by-nc-nd/4.0/",

            # Public domain
            "cc-zero": "http://creativecommons.org/publicdomain/zero/1.0/",
            "cc0": "http://creativecommons.org/publicdomain/zero/1.0/",
            "cc0-1.0": "http://creativecommons.org/publicdomain/zero/1.0/",
            "cc-zero-1.0": "http://creativecommons.org/publicdomain/zero/1.0/",
            "pdm": "http://creativecommons.org/publicdomain/mark/1.0/",
            "pdm-1.0": "http://creativecommons.org/publicdomain/mark/1.0/",
            "cc-pdm-1.0": "http://creativecommons.org/publicdomain/mark/1.0/",
            "public domain mark": "http://creativecommons.org/publicdomain/mark/1.0/",
            "publicdomainmark": "http://creativecommons.org/publicdomain/mark/1.0/",

            # RightsStatements.org
            "inc": "http://rightsstatements.org/vocab/InC/1.0/",
            "inc-edu": "http://rightsstatements.org/vocab/InC-EDU/1.0/",
            "inc-nc": "http://rightsstatements.org/vocab/InC-NC/1.0/",
            "noc-nc": "http://rightsstatements.org/vocab/NoC-NC/1.0/",
            "noc-oklr": "http://rightsstatements.org/vocab/NoC-OKLR/1.0/",
        }

        # Override with dynamic config if available
        config = self._get_mapping_config()
        if config and "licenses" in config:
             mapping.update(config["licenses"])

        # If it looks like a URI, just return it
        if license_id.startswith("http"):
            return license_id

        return mapping.get(license_id, "http://rightsstatements.org/vocab/CNE/1.0/") # Default to CNE if unknown

    def get_full_configuration(self):
        """Returns the current full configuration (merged defaults and overrides)."""
        # Valid defaults to show in UI
        default_types = {
            "image": "IMAGE", "video": "VIDEO", "dataset": "TEXT",
            "publication": "TEXT", "poster": "IMAGE", "presentation": "TEXT",
            "software": "TEXT", "lesson": "TEXT", "physicalobject": "3D"
        }
        default_licenses = {
            # Creative Commons 4.0 licenses
            "cc-by": "http://creativecommons.org/licenses/by/4.0/",
            "cc-by-sa": "http://creativecommons.org/licenses/by-sa/4.0/",
            "cc-by-nc": "http://creativecommons.org/licenses/by-nc/4.0/",
            "cc-by-nd": "http://creativecommons.org/licenses/by-nd/4.0/",
            "cc-by-nc-sa": "http://creativecommons.org/licenses/by-nc-sa/4.0/",
            "cc-by-nc-nd": "http://creativecommons.org/licenses/by-nc-nd/4.0/",
            # Public domain
            "cc-zero": "http://creativecommons.org/publicdomain/zero/1.0/",
            "cc0": "http://creativecommons.org/publicdomain/zero/1.0/",
            "pdm": "http://creativecommons.org/publicdomain/mark/1.0/",
            # RightsStatements.org
            "inc": "http://rightsstatements.org/vocab/InC/1.0/",
            "inc-edu": "http://rightsstatements.org/vocab/InC-EDU/1.0/",
            "inc-nc": "http://rightsstatements.org/vocab/InC-NC/1.0/",
            "noc-nc": "http://rightsstatements.org/vocab/NoC-NC/1.0/",
            "noc-oklr": "http://rightsstatements.org/vocab/NoC-OKLR/1.0/",
        }

        config = self._get_mapping_config() or {}

        return {
            "types": {**default_types, **config.get("types", {})},
            "licenses": {**default_licenses, **config.get("licenses", {})},
            "custom_overrides": config # Return raw overrides too if needed
        }

    def _get_modality_config(self):
        """
        Retrieves the modality detection configuration from the database.
        """
        from database.database import db
        from database.models import SystemConfig
        import json

        try:
            config_entry = db.session.get(SystemConfig, "modality_detection_config")
            if config_entry and config_entry.value:
                return json.loads(config_entry.value)
        except Exception as e:
            logger.warning(f"Failed to load modality detection config: {e}")

        return None

    def get_full_modality_configuration(self):
        """Returns the current full modality configuration (merged defaults and overrides)."""
        overrides = self._get_modality_config() or {}

        defaults = {
            "extensions": self.FILE_TYPE_BY_EXTENSION,
            "zenodo_types": {
                "image": "IMAGE", "video": "VIDEO", "dataset": "TEXT",
                "publication": "TEXT", "poster": "IMAGE", "presentation": "TEXT",
                "software": "TEXT", "lesson": "TEXT", "physicalobject": "3D"
            },
            "tiers": {
                "tier1": list(self.THREED_TIER_1),
                "tier2": list(self.THREED_TIER_2),
                "sidecars": self.THREED_SIDECARS
            }
        }

        return {
            "defaults": defaults,
            "overrides": overrides,
            "combined": {
                "extensions": {**defaults["extensions"], **overrides.get("extensions", {})},
                "zenodo_types": {**defaults["zenodo_types"], **overrides.get("zenodo_types", {})}
            },
            "tiers": defaults["tiers"]
        }

    def save_modality_configuration(self, new_config):
        """Saves the new modality configuration to the database."""
        from database.database import db
        from database.models import SystemConfig
        import json

        try:
            json_str = json.dumps(new_config)
            config_entry = db.session.get(SystemConfig, "modality_detection_config")
            if config_entry:
                config_entry.value = json_str
            else:
                config_entry = SystemConfig(key="modality_detection_config", value=json_str)
                db.session.add(config_entry)

            db.session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save modality config: {e}")
            db.session.rollback()
            raise e

    def reset_modality_configuration(self):
        """Resets modality configuration by removing overrides from database."""
        from database.database import db
        from database.models import SystemConfig
        try:
            config_entry = db.session.get(SystemConfig, "modality_detection_config")
            if config_entry:
                db.session.delete(config_entry)
                db.session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to reset modality config: {e}")
            db.session.rollback()
            raise e

    def save_configuration(self, new_config):
        """Saves the new configuration (overrides) to the database."""
        from flask import current_app
        from database.database import db
        from database.models import SystemConfig
        import json

        try:
            # Validate basic structure
            if not isinstance(new_config, dict):
                raise ValueError("Configuration must be a dictionary")

            # Save to DB
            json_str = json.dumps(new_config)
            config_entry = db.session.get(SystemConfig, "edm_mapping_config")
            if config_entry:
                config_entry.value = json_str
            else:
                config_entry = SystemConfig(key="edm_mapping_config", value=json_str)
                db.session.add(config_entry)

            db.session.commit()
            return True
        except Exception as e:
            current_app.logger.error(f"Failed to save EDM config: {e}")
            db.session.rollback()
            raise e
