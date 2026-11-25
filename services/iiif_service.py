# services/iiif_service.py
import logging
import json
import math
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urlsplit
import jinja2
from services.edm_service import EdmService, DotDict
from services.iiif_publication import published_manifest_id
from services.iiif_validation import (
    CONTEXT, V3_CONTEXT, content_type, is_machine_readable, positive, validate_manifest, valid_rights_uri,
)
from services.lod_reliability import public_url

logger = logging.getLogger(__name__)

class IiifService:
    """Generate IIIF Presentation 4 release-candidate manifests."""

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
        if metadata.get("iiif_manifest_id"):
            return str(metadata["iiif_manifest_id"])
        record_url = self.edm_service.get_record_html_url(zenodo_record)
        record_id = zenodo_record.get("id")
        if record_id:
            return published_manifest_id(record_id, is_sandbox=urlsplit(record_url).hostname == "sandbox.zenodo.org")
        return record_url.rstrip("/") + "/manifest.json"

    @staticmethod
    def _embedded_id(uri: str, name: str) -> str:
        base, _, fragment = uri.partition("#")
        return f"{base}#{fragment + '-' if fragment else ''}{name}"

    @staticmethod
    def _mapped_coordinate(metadata, name):
        value = metadata.get(f"iiif_{name}")
        if value in (None, ""):
            return None
        label = name.replace("_", " ").capitalize()
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"IIIF {label} must be a finite number") from None
        if isinstance(value, bool) or not math.isfinite(number):
            raise ValueError(f"IIIF {label} must be a finite number")
        return number

    def _nav_place(self, metadata, manifest_id):
        longitude, latitude, altitude = (self._mapped_coordinate(metadata, axis)
                                         for axis in ("longitude", "latitude", "altitude"))
        if longitude is None and latitude is None and altitude is None:
            return None
        if longitude is None or latitude is None:
            raise ValueError("Supply both IIIF longitude and latitude for a geographic location")
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError("IIIF longitude must be within ±180° and latitude within ±90°")
        coordinates = [longitude, latitude] if altitude is None else [longitude, latitude, altitude]
        return {
            "id": self._embedded_id(manifest_id, "place"),
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": coordinates}, "properties": {}}],
        }

    @staticmethod
    def _requires_legacy_template_migration(resource: Dict[str, Any]) -> bool:
        for _ in range(3):
            if resource.get("annotations") or resource.get("rendering"):
                return True
            items = resource.get("items")
            if not isinstance(items, list) or not items:
                return False
            if len(items) > 1:
                return True
            resource = items[0]
            if not isinstance(resource, dict):
                return False
        return "body" in resource

    @staticmethod
    def _uses_pre_rc_painting_shape(manifest: Dict[str, Any]) -> bool:
        def items(owner):
            entries = owner.get("items")
            return (item for item in entries if isinstance(item, dict)) if isinstance(entries, list) else ()

        for container in items(manifest):
            for page in items(container):
                for annotation in items(page):
                    if isinstance(annotation.get("motivation"), str):
                        return True
                    for field in ("body", "target"):
                        value = annotation.get(field)
                        if isinstance(value, (list, str)):
                            return True
                        if isinstance(value, dict) and value.get("type") == "SpecificResource" and (
                            not value.get("id") or isinstance(value.get("source"), (list, str))
                            or isinstance(value.get("selector"), dict) or isinstance(value.get("transform"), dict)
                        ):
                            return True
        return False

    def _migrate_legacy_template(self, manifest: Dict[str, Any]) -> None:
        """Convert authored legacy painting structures without replacing their assets."""
        def unsupported(reason):
            return ValueError(f"Update this legacy IIIF template to Presentation 4. {reason}.")

        def single_resource(value, name):
            if isinstance(value, list):
                if len(value) != 1:
                    raise unsupported(f"A legacy {name} array must identify exactly one resource")
                return value[0]
            return value

        def convert_body(value, annotation_id):
            body = single_resource(value, "body")
            wrapper = body if isinstance(body, dict) and body.get("type") == "SpecificResource" else None
            resource = single_resource(wrapper.get("source"), "body source") if wrapper is not None else body
            if isinstance(resource, str):
                mime = self.edm_service._infer_mime_type_from_url(resource)
                family = mime.split("/", 1)[0]
                kind = {"image": "Image", "audio": "Audio", "video": "Video", "text": "Text"}.get(family)
                if self.edm_service._looks_like_3d_resource_uri(resource):
                    kind = "Model"
                if kind is None:
                    raise unsupported("An untyped painting body has no recognizable media type")
                resource = {"id": resource, "type": kind, "format": mime}
            if not isinstance(resource, dict) or not isinstance(resource.get("type"), str) or resource["type"] == "SpecificResource":
                raise unsupported("A painting body must identify a single typed resource")
            if resource["type"] == "Sound":
                resource["type"] = "Audio"
            if wrapper is None:
                return resource, resource["type"]
            wrapper.setdefault("id", self._embedded_id(annotation_id, "body"))
            wrapper["source"] = resource
            for key in ("selector", "transform"):
                if isinstance(wrapper.get(key), dict):
                    wrapper[key] = [wrapper[key]]
            return wrapper, resource["type"]

        def convert_target(value, annotation_id, container_type):
            target = single_resource(value, "target")
            wrapper = target if isinstance(target, dict) and target.get("type") == "SpecificResource" else None
            source = single_resource(wrapper.get("source"), "target source") if wrapper is not None else target
            if isinstance(source, str):
                source = {"id": source, "type": container_type}
            if not isinstance(source, dict) or source.get("type") not in (None, "Canvas", container_type):
                raise unsupported("A legacy painting target must reference its Canvas or a specific part of it")
            source["type"] = container_type
            if wrapper is None:
                return source
            wrapper.setdefault("id", self._embedded_id(annotation_id, "target"))
            wrapper["source"] = source
            if isinstance(wrapper.get("selector"), dict):
                wrapper["selector"] = [wrapper["selector"]]
            return wrapper

        for owner in (manifest, *manifest["items"]):
            if not isinstance(owner, dict):
                raise unsupported("All legacy Canvas items must be embedded objects")
            if owner.get("annotations"):
                raise unsupported("Supplemental AnnotationPages need explicit migration")
            renderings = owner.get("rendering", [])
            if not isinstance(renderings, list):
                raise unsupported("Rendering links must be an array")
            for rendering in renderings:
                if isinstance(rendering, dict) and rendering.get("type") == "Sound":
                    rendering["type"] = "Audio"

        for container in manifest["items"]:
            kind_before_migration = container.get("type")
            if kind_before_migration not in ("Canvas", "Scene", "Timeline"):
                raise unsupported("Legacy containers must identify a Canvas, Scene or Timeline")
            annotations = []
            kinds = set()
            pages = container.get("items", [])
            if not isinstance(pages, list):
                raise unsupported("Canvas items must be an array of AnnotationPages")
            for page in pages:
                if not isinstance(page, dict) or page.get("type") != "AnnotationPage" or not isinstance(page.get("items"), list):
                    raise unsupported("Painting AnnotationPages must be embedded")
                if page.get("annotations"):
                    raise unsupported("Supplemental AnnotationPages need explicit migration")
                for annotation in page["items"]:
                    if not isinstance(annotation, dict) or not isinstance(annotation.get("id"), str):
                        raise unsupported("Each painting annotation needs an identifier")
                    motivation = annotation.get("motivation")
                    if isinstance(motivation, str):
                        motivation = [motivation]
                    if not isinstance(motivation, list) or "painting" not in motivation:
                        raise unsupported("Each legacy container item must contain a painting annotation")
                    annotation["motivation"] = motivation
                    annotation["body"], kind = convert_body(annotation.get("body"), annotation["id"])
                    kinds.add(kind)
                    annotations.append(annotation)

            if kind_before_migration == "Canvas":
                if "Model" in kinds and kinds != {"Model"}:
                    raise unsupported("A Canvas with a model and other painted media needs an authored Scene")
                if kinds == {"Model"}:
                    container["type"] = "Scene"
                elif kinds == {"Audio"} and container.get("duration"):
                    container["type"] = "Timeline"
            if container["type"] != "Canvas":
                if container["type"] != kind_before_migration and (manifest.get("structures") or manifest.get("start")):
                    raise unsupported("Scene or Timeline references in legacy navigation need explicit migration")
                container.pop("width", None)
                container.pop("height", None)
            elif "width" not in container and "height" not in container:
                container.update(width=1000, height=1000)
            if container.get("items") == []:
                del container["items"]
            for annotation in annotations:
                annotation["target"] = convert_target(annotation.get("target"), annotation["id"], container["type"])

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

        context = manifest.get("@context")
        declared_context = context[-1] if isinstance(context, list) and context else context
        native_template = declared_context in (CONTEXT, CONTEXT.replace("http://", "https://", 1))
        legacy_contexts = (V3_CONTEXT, V3_CONTEXT.replace("http://", "https://", 1))
        legacy_template = declared_context in legacy_contexts
        if not native_template:
            extensions = []
            if legacy_template and isinstance(context, list):
                extensions = [entry for entry in context[:-1] if entry not in legacy_contexts]
            manifest["@context"] = [*extensions, CONTEXT] if extensions else CONTEXT
        record_url = zenodo_context["zenodo_url"].rstrip("/")

        def authored_id(resource, legacy_suffix):
            value = resource.get("id")
            return None if not native_template and value == f"{record_url}/{legacy_suffix}" else value

        manifest["id"] = str(authored_id(manifest, "manifest.json")
                             or self._default_manifest_id(metadata, zenodo_context))
        manifest["type"] = "Manifest"
        manifest["label"] = self._normalize_lang_map(
            manifest.get("label") or metadata.get("title"),
            fallback=str(metadata.get("title") or "Untitled"),
        )

        description = str(metadata.get("description") or "").strip()
        if description and not manifest.get("summary"):
            manifest["summary"] = self.lang_map(description)

        license_id = metadata.get("license")
        if isinstance(license_id, dict):
            license_id = license_id.get("id")
        if isinstance(license_id, str) and license_id and "rights" not in manifest:
            rights = license_id if public_url(license_id) else self.edm_service._map_license_to_uri(license_id)
            if valid_rights_uri(rights):
                manifest["rights"] = rights

        provider = metadata.get("provider")
        if "provider" not in manifest and isinstance(provider, str) and provider.strip():
            manifest["provider"] = [{"id": self._embedded_id(manifest["id"], "provider"), "type": "Agent",
                                     "label": self.lang_map(provider.strip())}]

        if "navPlace" not in manifest:
            nav_place = self._nav_place(metadata, manifest["id"])
            if nav_place is not None:
                manifest["navPlace"] = nav_place

        if "metadata" not in manifest:
            creators = metadata.get("creators")
            keywords = metadata.get("keywords") or []
            entries = {
                "Creator": self.join_creators([item for item in creators if isinstance(item, dict)]) if isinstance(creators, list) else "",
                "Keywords": ", ".join(str(value) for value in keywords) if isinstance(keywords, list) else str(keywords),
            }
            labels = [{"label": self.lang_map(label), "value": self.lang_map(value)} for label, value in entries.items() if value]
            if labels:
                manifest["metadata"] = labels

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

        template_items = manifest.get("items")
        if native_template and template_items:
            if self._uses_pre_rc_painting_shape(manifest):
                self._migrate_legacy_template(manifest)
            # Current authored v4 containers are validated in place.
            return json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)
        if legacy_template and self._requires_legacy_template_migration(manifest):
            self._migrate_legacy_template(manifest)
            return json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)

        kind = content_type(main_file)
        content_id = metadata.get("iiif_content_id") or (metadata.get("iiif_model_id") if kind == "Model" else None)
        source_entry = {
            "id": str(content_id or main_file.get("content_url")),
            "type": kind,
            "format": str(
                (metadata.get("iiif_model_format") if kind == "Model" else None)
                or main_file.get("format")
                or ("model/gltf-binary" if kind == "Model" else "application/octet-stream")
            ),
        }

        def dimension(name, integer=False, fallback=None):
            value = next((value for value in (metadata.get(f"iiif_{name}"), metadata.get(name), fallback) if value not in (None, "")), None)
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

        duration = dimension("duration", fallback=main_file.get("duration")) if kind in {"Audio", "Video"} else None
        container_type = "Canvas"
        if kind == "Model":
            container_type = "Scene"
        elif kind == "Audio" and duration is not None:
            container_type = "Timeline"
        if legacy_template and container_type != "Canvas" and (manifest.get("structures") or manifest.get("start")):
            raise ValueError("Update this IIIF Presentation 3 template to Presentation 4. Scene or Timeline references in legacy navigation need explicit migration.")
        mapped_prefixes = {
            "Scene": ("scene", "canvas"),
            "Timeline": ("timeline", "canvas", "scene"),
            "Canvas": ("canvas", "scene"),
        }[container_type]

        def mapped_container_value(field):
            return next((metadata[f"iiif_{prefix}_{field}"] for prefix in mapped_prefixes
                         if metadata.get(f"iiif_{prefix}_{field}")), None)

        items = manifest.get("items")
        if not isinstance(items, list) or not items:
            items = [{}]
        manifest["items"] = items
        container = items[0] if isinstance(items[0], dict) else {}
        items[0] = container
        container["id"] = str(authored_id(container, "canvas/1") or mapped_container_value("id")
                              or f"{record_url}/iiif/{container_type.lower()}/1")
        container["type"] = container_type
        container["label"] = self._normalize_lang_map(
            container.get("label") or mapped_container_value("label") or metadata.get("title"),
            fallback=container_type,
        )
        if container_type == "Canvas":
            width, height = dimension("width", True), dimension("height", True)
            if (width is None) != (height is None):
                raise ValueError("Supply both IIIF width and height, or leave both unset")
            pixel_width, pixel_height = main_file.get("width"), main_file.get("height")
            if kind in {"Image", "Video"} and positive(pixel_width, integer=True) and positive(pixel_height, integer=True):
                source_entry.update(width=pixel_width, height=pixel_height)
            container["width"] = width or container.get("width") or source_entry.get("width") or 1000
            container["height"] = height or container.get("height") or source_entry.get("height") or 1000
        else:
            container.pop("width", None)
            container.pop("height", None)
        if duration is not None:
            container["duration"] = duration
            source_entry["duration"] = duration

        annotation_pages = container.get("items")
        if not isinstance(annotation_pages, list) or not annotation_pages:
            annotation_pages = [{}]
        container["items"] = annotation_pages
        annotation_page = annotation_pages[0] if isinstance(annotation_pages[0], dict) else {}
        annotation_pages[0] = annotation_page
        annotation_page["id"] = str(authored_id(annotation_page, "page/1") or metadata.get("iiif_annotation_page_id")
                                    or self._embedded_id(manifest["id"], "page-1"))
        annotation_page["type"] = "AnnotationPage"

        annotations = annotation_page.get("items")
        if not isinstance(annotations, list) or not annotations:
            annotations = [{}]
        annotation_page["items"] = annotations
        annotation = annotations[0] if isinstance(annotations[0], dict) else {}
        annotations[0] = annotation
        annotation["id"] = str(authored_id(annotation, "annotation/1") or metadata.get("iiif_annotation_id")
                                or self._embedded_id(manifest["id"], "annotation-1"))
        annotation["type"] = "Annotation"
        motivation = annotation.get("motivation")
        if isinstance(motivation, str):
            annotation["motivation"] = [motivation]
        elif not isinstance(motivation, list) or not motivation:
            annotation["motivation"] = ["painting"]

        target = {"id": container["id"], "type": container_type}
        machine_readable = is_machine_readable(source_entry)
        if machine_readable or kind == "Text" or (kind in {"Audio", "Video"} and duration is None):
            property_name = "seeAlso" if machine_readable else "rendering"
            link = {**source_entry, "label": self.lang_map(str(main_file.get("filename") or "Open source file"))}
            if machine_readable:
                link["type"] = "Dataset"
            existing = container.get(property_name, [])
            if isinstance(existing, list):
                container[property_name] = [link, *[item for item in existing if not isinstance(item, dict) or item.get("id") != link["id"]]]
            if thumbnail_files:
                cover = thumbnail_files[0]
                annotation["body"] = {"id": cover["content_url"], "type": "Image", "format": cover["mime_type"]}
                annotation["target"] = target
            else:
                del annotations[0]
                if not annotations:
                    del annotation_pages[0]
                if not annotation_pages:
                    del container["items"]
            return json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)

        model_label = self._normalize_lang_map(metadata.get("iiif_model_label"), fallback="") if kind == "Model" else {}
        if model_label:
            source_entry["label"] = model_label

        def _coordinate(name: str) -> Optional[float]:
            number = self._mapped_coordinate(metadata, name) if kind == "Model" else None
            if name.startswith("scale_") and number == 0:
                raise ValueError(f"IIIF {name.replace('_', ' ')} must be non-zero")
            return number

        transforms = []
        for operation, default in (("translate", 0.0), ("rotate", 0.0), ("scale", 1.0)):
            coordinates = {axis: _coordinate(f"{operation}_{axis}") for axis in "xyz"}
            if any(value not in (None, default) for value in coordinates.values()):
                transforms.append({"type": f"{operation.title()}Transform",
                                   **{axis: default if value is None else value for axis, value in coordinates.items()}})

        annotation["body"] = source_entry
        if transforms:
            annotation["body"] = {"id": self._embedded_id(annotation["id"], "body"), "type": "SpecificResource",
                                  "source": source_entry, "transform": transforms}

        point = {axis: _coordinate(f"point_{axis}") for axis in "xyz"}
        annotation["target"] = target
        if any(value is not None for value in point.values()):
            annotation["target"] = {
                "id": self._embedded_id(annotation["id"], "target"),
                "type": "SpecificResource",
                "source": target,
                "selector": [{"type": "PointSelector", **{axis: value or 0.0 for axis, value in point.items()}}],
            }

        return json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)

    def validate_iiif_manifest(self, manifest_json: str) -> Dict[str, Any]:
        return validate_manifest(manifest_json)

    def render_template(
        self,
        template_id: Optional[int],
        metadata: Dict[str, Any],
        zenodo_record: Dict[str, Any],
        main_file_key: Optional[str] = None,
        allow_placeholder_thumbnail: bool = False,
        additional_files: Optional[List[Dict[str, Any]]] = None,
        *,
        template_content: Optional[str] = None,
    ) -> Optional[str]:
        """Render saved or supplied IIIF Jinja2 content."""
        from services.lod_reliability import normalize_record
        zenodo_record = normalize_record(zenodo_record)
        try:
            if template_content is None:
                from database.seed_iiif_templates import IIIF_PRESENTATION_TEMPLATE, is_legacy_bundled_iiif_template
                from services.lod_reliability import resolve_template
                template = resolve_template("iiif", template_id)
                if not template:
                    logger.error("IIIF template %s was not found", template_id)
                    return None
                template_content = IIIF_PRESENTATION_TEMPLATE if is_legacy_bundled_iiif_template(template) else template.content

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
                'get_spatial_ref': self.get_spatial_ref,
                'manifest_id': self._default_manifest_id,
                'presentation_context': CONTEXT,
            }

            jinja_template = env.from_string(template_content)

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
                logger.error("Rendered IIIF Manifest is not valid JSON: %s", e)
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
        Main entry point for generating IIIF Presentation 4 release-candidate manifests.

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
        *,
        template_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates a IIIF manifest and reports whether minimum-viable safeguards
        altered the rendered template output.
        """
        if template_content is not None and template_id is not None:
            raise ValueError("Supply a saved IIIF template ID or template content")
        if template_content is None:
            from database.lod_template_bootstrap import ensure_default_lod_templates
            from services.lod_reliability import resolve_template

            ensure_default_lod_templates()
            template_id = resolve_template("iiif", template_id).id

        rendered = self.render_template(
            template_id,
            metadata,
            zenodo_record,
            main_file_key=main_file_key,
            allow_placeholder_thumbnail=allow_placeholder_thumbnail,
            additional_files=additional_files,
            template_content=template_content,
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
