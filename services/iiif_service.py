# services/iiif_service.py
import logging
import json
import math
from datetime import datetime
from typing import Dict, Any, List, Optional
import jinja2
from services.edm_service import EdmService, DotDict
from services.iiif_validation import content_type, validate_manifest

logger = logging.getLogger(__name__)

class IiifService:
    """
    Service for generating IIIF Presentation API v3 JSON Manifests.
    """

    IIIF_V3_CONTEXT = "http://iiif.io/api/presentation/3/context.json"

    def __init__(self):
        self.edm_service = EdmService()
        self.allowed_model_formats = {
            "model/gltf-binary",
            "model/gltf+json",
            "model/obj",
            "model/stl",
            "application/ply",
            "application/fbx",
            "model/vnd.collada+xml",
            "application/x-3ds",
            "application/x-blender",
            "application/octet-stream",
        }

    def lang_map(self, text: str, lang: str = "en") -> Dict[str, List[str]]:
        """Wraps text in a IIIF Language Map."""
        return {lang: [text]} if text else {}

    def join_creators(self, creators: Optional[List[Dict[str, str]]]) -> str:
        """Joins creators into a single string: 'Name (Affiliation), Name (Affiliation)'."""
        if not creators:
            return ""
        parts = []
        for c in creators:
            name = c.get('name', '')
            aff = c.get('affiliation', '')
            if name and aff:
                parts.append(f"{name} ({aff})")
            elif name:
                parts.append(name)
        return ", ".join(parts)

    def get_spatial_ref(self, metadata: Dict[str, Any]) -> str:
        """Combines reference system and units."""
        ref = metadata.get('reference_system')
        units = metadata.get('units')
        if ref and units:
            return f"{ref} ({units})"
        return ref or units or ""

    def _default_manifest_id(self, metadata: Dict[str, Any], zenodo_record: Dict[str, Any]) -> str:
        return str(
            metadata.get("iiif_manifest_id")
            or zenodo_record.get("zenodo_url")
            or self.edm_service.get_record_html_url(zenodo_record)
            or "https://example.invalid/iiif/manifest"
        ).rstrip("/") + "/manifest.json"

    def _default_canvas_id(self, metadata: Dict[str, Any], zenodo_record: Dict[str, Any]) -> str:
        return str(
            metadata.get("iiif_canvas_id")
            or metadata.get("iiif_scene_id")
            or self._default_manifest_id(metadata, zenodo_record).replace("/manifest.json", "/canvas/1")
        )

    def _default_scene_id(self, metadata: Dict[str, Any], zenodo_record: Dict[str, Any]) -> str:
        """Backward-compatible alias for earlier 3D scene-oriented templates."""
        return self._default_canvas_id(metadata, zenodo_record)

    def _default_annotation_page_id(self, metadata: Dict[str, Any], zenodo_record: Dict[str, Any]) -> str:
        return str(metadata.get("iiif_annotation_page_id") or self._default_manifest_id(metadata, zenodo_record).replace("/manifest.json", "/page/1"))

    def _default_annotation_id(self, metadata: Dict[str, Any], zenodo_record: Dict[str, Any]) -> str:
        return str(metadata.get("iiif_annotation_id") or self._default_manifest_id(metadata, zenodo_record).replace("/manifest.json", "/annotation/1"))

    def _normalize_lang_map(self, value: Any, fallback: str = "Untitled") -> Dict[str, List[str]]:
        if isinstance(value, dict):
            normalized: Dict[str, List[str]] = {}
            for key, entries in value.items():
                if not isinstance(key, str):
                    continue
                if isinstance(entries, list):
                    texts = [str(item).strip() for item in entries if str(item).strip()]
                else:
                    texts = [str(entries).strip()] if str(entries).strip() else []
                if texts:
                    normalized[key] = texts
            if normalized:
                return normalized

        text = str(value or "").strip() or fallback
        return self.lang_map(text)

    def _prepare_manifest_assets(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        main_file_key: Optional[str] = None,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        files = self.edm_service._normalize_zenodo_files(zenodo_record)
        if additional_files:
            files.extend(additional_files)

        z_copy = zenodo_record.copy() if isinstance(zenodo_record, dict) else {}
        z_copy["files"] = files

        main_file = None
        if main_file_key:
            main_file = next(
                (f for f in files if (f.get("key") or f.get("filename")) == main_file_key),
                None,
            )
            if not main_file:
                main_file = {"key": main_file_key, "filename": main_file_key, "size": 0}

        if not main_file:
            main_file = self.edm_service._select_smart_primary_file(files, metadata)
        if not main_file:
            main_file = {"key": "unknown_file", "filename": "unknown_file", "size": 0}

        thumbnail_files = self.edm_service._select_thumbnail_files(
            files,
            main_file=main_file,
            metadata=metadata,
            allow_placeholder=allow_placeholder_thumbnail,
        )

        main_file = self.edm_service._enrich_file_metadata(main_file, metadata)
        record_id = str(z_copy.get("id", ""))
        zenodo_url = self.edm_service.get_record_html_url(z_copy)
        z_copy["zenodo_url"] = zenodo_url
        is_sandbox_mode = "sandbox.zenodo.org" in zenodo_url

        content_url = self.edm_service.get_file_content_url(
            main_file,
            record_id,
            is_sandbox=is_sandbox_mode,
        )
        main_file["content_url"] = content_url
        main_file["viewer_url"] = content_url

        enriched_thumbnail_files: List[Dict[str, Any]] = []
        for thumb in thumbnail_files:
            enriched_thumb = self.edm_service._enrich_file_metadata(thumb, metadata)
            enriched_thumb["content_url"] = self.edm_service.get_file_content_url(
                enriched_thumb,
                record_id,
                is_sandbox=is_sandbox_mode,
            )
            enriched_thumbnail_files.append(enriched_thumb)

        return {
            "zenodo_record": z_copy,
            "main_file": main_file,
            "thumbnail_files": enriched_thumbnail_files,
            "thumbnail_file": enriched_thumbnail_files[0] if enriched_thumbnail_files else None,
        }

    def _ensure_minimum_viable_iiif(
        self,
        rendered_json: str,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        *,
        main_file_key: Optional[str] = None,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        try:
            manifest = json.loads(rendered_json)
        except json.JSONDecodeError:
            return rendered_json

        if not isinstance(manifest, dict):
            manifest = {}

        assets = self._prepare_manifest_assets(
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        main_file = assets["main_file"]
        thumbnail_files = assets["thumbnail_files"]
        zenodo_context = assets["zenodo_record"]

        manifest["@context"] = self.IIIF_V3_CONTEXT
        manifest["id"] = str(manifest.get("id") or self._default_manifest_id(metadata, zenodo_context))
        manifest["type"] = "Manifest"
        manifest["label"] = self._normalize_lang_map(
            manifest.get("label") or metadata.get("title"),
            fallback=str(metadata.get("title") or "Untitled"),
        )

        description = str(metadata.get("description") or "").strip()
        if description and not manifest.get("summary"):
            manifest["summary"] = self.lang_map(description)

        if thumbnail_files and not manifest.get("thumbnail"):
            manifest["thumbnail"] = [
                {
                    "id": thumb.get("content_url"),
                    "type": "Image",
                    "format": thumb.get("mime_type") or "image/png",
                }
                for thumb in thumbnail_files
                if thumb.get("content_url")
            ]

        items = manifest.get("items")
        if not isinstance(items, list) or not items:
            items = [{}]
            manifest["items"] = items

        canvas = items[0] if isinstance(items[0], dict) else {}
        items[0] = canvas
        canvas["id"] = str(canvas.get("id") or self._default_canvas_id(metadata, zenodo_context))
        canvas["type"] = "Canvas"
        canvas["label"] = self._normalize_lang_map(
            canvas.get("label") or metadata.get("iiif_canvas_label") or metadata.get("iiif_scene_label") or metadata.get("title"),
            fallback="Canvas",
        )

        annotation_pages = canvas.get("items")
        if not isinstance(annotation_pages, list) or not annotation_pages:
            annotation_pages = [{}]
            canvas["items"] = annotation_pages

        annotation_page = annotation_pages[0] if isinstance(annotation_pages[0], dict) else {}
        annotation_pages[0] = annotation_page
        annotation_page["id"] = str(
            annotation_page.get("id") or self._default_annotation_page_id(metadata, zenodo_context)
        )
        annotation_page["type"] = "AnnotationPage"

        annotation_items = annotation_page.get("items")
        if not isinstance(annotation_items, list) or not annotation_items:
            annotation_items = [{}]
            annotation_page["items"] = annotation_items

        annotation = annotation_items[0] if isinstance(annotation_items[0], dict) else {}
        annotation_items[0] = annotation
        annotation["id"] = str(annotation.get("id") or self._default_annotation_id(metadata, zenodo_context))
        annotation["type"] = "Annotation"
        motivation = annotation.get("motivation")
        if isinstance(motivation, str):
            annotation["motivation"] = [motivation]
        elif not isinstance(motivation, list) or not motivation:
            annotation["motivation"] = ["painting"]

        source_entry = {
            "id": str(metadata.get("iiif_model_id") or main_file.get("content_url")),
            "type": content_type(main_file),
            "format": str(
                (metadata.get("iiif_model_format") if content_type(main_file) == "Model" else None)
                or main_file.get("format")
                or "model/gltf-binary"
            ),
        }
        def dimension(name, integer=False):
            value = next((value for value in (metadata.get(f"iiif_{name}"), metadata.get(name), main_file.get(name)) if value not in (None, "")), None)
            if value in (None, ""):
                return None
            if isinstance(value, bool):
                raise ValueError(f"IIIF {name} must be a positive {'integer' if integer else 'number'}")
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"IIIF {name} must be numeric") from None
            if not math.isfinite(number) or number <= 0 or (integer and not number.is_integer()):
                raise ValueError(f"IIIF {name} must be a positive {'integer' if integer else 'number'}")
            return int(number) if integer else number

        width, height, duration = dimension("width", True), dimension("height", True), dimension("duration")
        if (width is None) != (height is None):
            raise ValueError("Supply both IIIF width and height, or leave both unset")
        kind = source_entry["type"]
        # Canvas dimensions describe a virtual presentation frame, not measured asset dimensions.
        canvas["width"] = width or canvas.get("width") or 1000
        canvas["height"] = height or canvas.get("height") or 1000
        if duration is not None and kind in {"Sound", "Video"}:
            canvas["duration"] = duration
            source_entry["duration"] = duration
        if width and height and kind in {"Image", "Video"}:
            source_entry.update(width=width, height=height)
        if kind in {"Text", "Dataset"} or (kind in {"Sound", "Video"} and duration is None):
            rendering = {**source_entry, "label": self.lang_map(str(main_file.get("filename") or "Open source file"))}
            existing = canvas.get("rendering") if isinstance(canvas.get("rendering"), list) else []
            canvas["rendering"] = [rendering, *[item for item in existing if item.get("id") != rendering["id"]]]
            # Downloads and media with unknown duration remain linked instead of inventing time extents.
            canvas["items"] = []
            if thumbnail_files:
                cover = thumbnail_files[0]
                annotation["body"] = [{"id": cover["content_url"], "type": "Image", "format": cover["mime_type"]}]
                annotation["target"] = [canvas["id"]]
                canvas["items"] = [annotation_page]
            return json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)

        model_label = self._normalize_lang_map(
            metadata.get("iiif_model_label"),
            fallback="",
        ) if metadata.get("iiif_model_label") else {}
        if model_label:
            source_entry["label"] = model_label

        def _coordinate(name: str) -> Optional[float]:
            value = metadata.get(name) if kind == "Model" else None
            if value in (None, ""):
                return None
            label = name.removeprefix("iiif_").replace("_", " ").title()
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"IIIF {label} must be a finite number") from None
            if isinstance(value, bool) or not math.isfinite(number):
                raise ValueError(f"IIIF {label} must be a finite number")
            if name.startswith("iiif_scale_") and number == 0:
                raise ValueError(f"IIIF {label} must be non-zero")
            return number

        translate = {
            "x": _coordinate("iiif_translate_x"),
            "y": _coordinate("iiif_translate_y"),
            "z": _coordinate("iiif_translate_z"),
        }
        rotate = {
            "x": _coordinate("iiif_rotate_x"),
            "y": _coordinate("iiif_rotate_y"),
            "z": _coordinate("iiif_rotate_z"),
        }
        scale = {
            "x": _coordinate("iiif_scale_x"),
            "y": _coordinate("iiif_scale_y"),
            "z": _coordinate("iiif_scale_z"),
        }

        transforms = []
        if any(value not in (None, 0.0) for value in translate.values()):
            transforms.append(
                {
                    "type": "TranslateTransform",
                    "x": translate["x"] or 0.0,
                    "y": translate["y"] or 0.0,
                    "z": translate["z"] or 0.0,
                }
            )
        if any(value not in (None, 0.0) for value in rotate.values()):
            transforms.append(
                {
                    "type": "RotateTransform",
                    "x": rotate["x"] or 0.0,
                    "y": rotate["y"] or 0.0,
                    "z": rotate["z"] or 0.0,
                }
            )
        if any(value not in (None, 1.0) for value in scale.values()):
            transforms.append(
                {
                    "type": "ScaleTransform",
                    "x": scale["x"] if scale["x"] is not None else 1.0,
                    "y": scale["y"] if scale["y"] is not None else 1.0,
                    "z": scale["z"] if scale["z"] is not None else 1.0,
                }
            )

        if transforms:
            annotation["body"] = [
                {
                    "type": "SpecificResource",
                    "source": source_entry,
                    "transform": transforms,
                }
            ]
        else:
            annotation["body"] = [source_entry]

        point_x = _coordinate("iiif_point_x")
        point_y = _coordinate("iiif_point_y")
        point_z = _coordinate("iiif_point_z")
        if any(value is not None for value in (point_x, point_y, point_z)):
            annotation["target"] = [
                {
                    "type": "SpecificResource",
                    "source": {
                        "id": canvas["id"],
                        "type": "Canvas",
                    },
                    "selector": [
                        {
                            "type": "PointSelector",
                            "x": point_x or 0.0,
                            "y": point_y or 0.0,
                            "z": point_z or 0.0,
                        }
                    ],
                }
            ]
        else:
            annotation["target"] = [canvas["id"]]

        return json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)

    def validate_iiif_manifest(self, manifest_json: str) -> Dict[str, Any]:
        return validate_manifest(manifest_json)

    def render_template(
        self,
        template_id: int,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        main_file_key: Optional[str] = None,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """
        Renders a IIIF JSON Manifest from a stored Jinja2 template.
        """
        from database.database import db
        from database.models import LodTemplate

        from services.lod_reliability import normalize_record
        zenodo_record = normalize_record(zenodo_record)
        try:
            from services.lod_reliability import resolve_template
            template = resolve_template("iiif", template_id)
            if not template:
                logger.error(f"LodTemplate {template_id} not found.")
                return None

            assets = self._prepare_manifest_assets(
                metadata,
                zenodo_record,
                main_file_key=main_file_key,
                allow_placeholder_thumbnail=allow_placeholder_thumbnail,
                additional_files=additional_files,
            )
            zenodo_record = assets["zenodo_record"]
            main_file = assets["main_file"]
            enriched_thumbnail_files = assets["thumbnail_files"]
            thumbnail_file = assets["thumbnail_file"]

            # Prepare Jinja2 Environment
            env = jinja2.Environment(autoescape=False, undefined=jinja2.DebugUndefined)

            # Context and Helpers
            helpers = {
                'lang_map': self.lang_map,
                'iso_date': self.edm_service.iso_date,
                'generate_uri': self.edm_service.generate_uri,
                'join_creators': self.join_creators,
                'get_spatial_ref': self.get_spatial_ref
            }

            jinja_template = env.from_string(template.content)

            # Wrap in DotDicts
            z_copy = zenodo_record.copy() if isinstance(zenodo_record, dict) else zenodo_record
            zenodo_dict = DotDict(z_copy)
            meta_dict = DotDict(metadata) if isinstance(metadata, dict) else metadata
            main_dict = DotDict(main_file) if isinstance(main_file, dict) else main_file
            thumb_dict = DotDict(thumbnail_file) if isinstance(thumbnail_file, dict) and thumbnail_file else None
            thumb_list_dict = [DotDict(thumb) for thumb in enriched_thumbnail_files]

            rendered_json = jinja_template.render(
                metadata=meta_dict,
                zenodo=zenodo_dict,
                helpers=helpers,
                main_file=main_dict,
                thumbnail_file=thumb_dict,
                thumbnail_files=thumb_list_dict,
            )

            # Validate JSON
            try:
                json.loads(rendered_json)
                return rendered_json
            except json.JSONDecodeError as e:
                logger.error(f"Rendered IIIF Manifest is not valid JSON: {e}\n{rendered_json}")
                return None

        except Exception as e:
            logger.error(f"IIIF Template rendering failed: {e}", exc_info=True)
            return None
    def generate_iiif_manifest(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        template_id: Optional[int] = None,
        main_file_key: Optional[str] = None,
        validate: bool = True,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Main entry point for generating IIIF Presentation API v3 JSON Manifests.

        Args:
            metadata: Metadata dictionary.
            zenodo_record: Zenodo record dictionary.
            template_id: Optional template ID override.
            main_file_key: Optional main file key override.
            validate: If True, performs JSON validation.
        """
        result = self.generate_iiif_manifest_with_report(
            metadata=metadata,
            zenodo_record=zenodo_record,
            template_id=template_id,
            main_file_key=main_file_key,
            validate=validate,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        return result["content"]

    def generate_iiif_manifest_with_report(
        self,
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        template_id: Optional[int] = None,
        main_file_key: Optional[str] = None,
        validate: bool = True,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generates a IIIF manifest and reports whether minimum-viable safeguards
        altered the rendered template output.
        """
        from database.lod_template_bootstrap import ensure_default_lod_templates
        from database.database import db
        from database.models import LodTemplate

        ensure_default_lod_templates()

        from services.lod_reliability import resolve_template
        template_id = resolve_template("iiif", template_id).id

        rendered = self.render_template(
            template_id,
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        if not rendered:
            raise ValueError("IIIF Template rendering returned empty result")

        repaired = self._ensure_minimum_viable_iiif(
            rendered,
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
        )
        from services.lod_reliability import assert_public_document
        assert_public_document(repaired)
        from services.metadata_adjustments import document_adjustments
        adjustments = document_adjustments(rendered, repaired, "iiif")
        minimum_viable_applied = bool(adjustments)

        validation = None
        if validate:
            validation = self.validate_iiif_manifest(repaired)
            if not validation["valid"]:
                error_summary = "; ".join(validation["errors"][:3])
                raise ValueError(f"IIIF validation failed: {error_summary}")

        return {
            "content": repaired,
            "minimum_viable_applied": minimum_viable_applied,
            "adjustments": adjustments,
            "validation": validation,
        }
