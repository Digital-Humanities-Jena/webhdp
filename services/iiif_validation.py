"""Local IIIF Presentation checks, without fetching referenced resources."""
import json
import math
import re
from urllib.parse import parse_qsl, urldefrag, urlsplit

CONTEXT = "http://iiif.io/api/presentation/4/context.json"
PROFILE_VERSION = "presentation-4-rc-media-1"
V3_CONTEXT = "http://iiif.io/api/presentation/3/context.json"
V3_PROFILE_VERSION = "presentation-3-media-2"
MODEL_FORMATS = {"model/gltf-binary", "model/gltf+json", "model/obj", "model/stl",
                 "application/ply", "application/fbx", "application/x-3ds", "application/x-blender",
                 "model/vnd.collada+xml", "application/octet-stream"}
TEXT_FORMATS = {"application/pdf", "application/xml", "application/epub+zip", "application/rtf",
                "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.oasis.opendocument.text"}


def content_type(asset):
    return {"3d_model": "Model", "image": "Image", "audio": "Audio", "video": "Video",
            "document": "Text"}.get(asset.get("content_type"), "Dataset")


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def positive(value, integer=False):
    return finite(value) and value > 0 and (not integer or isinstance(value, int))


def format_matches(kind, mime):
    if kind == "Model":
        return mime in MODEL_FORMATS or mime.startswith("model/")
    if kind == "Text":
        return mime.startswith("text/") or mime in TEXT_FORMATS
    prefix = {"Image": "image/", "Audio": "audio/", "Sound": "audio/", "Video": "video/"}.get(kind)
    return mime.startswith(prefix) if prefix else kind == "Dataset"


def validate_legacy_v3_manifest(content):
    """Validate historical Presentation 3 artifacts under their original profile."""
    result = {"valid": False, "errors": [], "warnings": [], "details": {
        "profile": V3_PROFILE_VERSION, "scope": "Local structure, media types, extents and annotation targets; referenced files and viewer support are not checked.",
        "canvas_count": 0, "annotation_page_count": 0, "annotation_count": 0}}
    errors = result["errors"]
    try:
        manifest = json.loads(content, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (TypeError, ValueError) as exc:
        errors.append(f"JSON Syntax Error: {exc}")
        return result
    if not isinstance(manifest, dict):
        errors.append("Manifest root must be a JSON object.")
        return result
    seen = set()

    def identifier(value, path, unique=False):
        try:
            parsed = urlsplit(value) if isinstance(value, str) else None
            valid = (parsed and parsed.scheme in {"http", "https"} and parsed.hostname
                     and not parsed.username and not parsed.password and not any(c.isspace() for c in value))
        except ValueError:
            valid = False
        if not valid:
            errors.append(f"{path} must be an HTTP(S) identifier without credentials.")
            return
        if unique:
            if value in seen:
                errors.append(f"{path} duplicates another resource identifier.")
            seen.add(value)

    def language_map(value, path):
        if not (isinstance(value, dict) and value and all(
            isinstance(key, str) and key.strip() and isinstance(values, list) and values
            and all(isinstance(text, str) and text.strip() for text in values)
            for key, values in value.items())):
            errors.append(f"{path} must be a non-empty IIIF language map.")

    def resource(value, path, canvas=None):
        if not isinstance(value, dict):
            errors.append(f"{path} must be a content resource object.")
            return
        if value.get("type") == "SpecificResource":
            if isinstance(value.get("source"), dict) and value["source"].get("type") == "SpecificResource":
                errors.append(f"{path}.source must be a content resource, not another SpecificResource.")
                return
            resource(value.get("source"), f"{path}.source", canvas)
            if 'transform' in value:
                transforms = value['transform']
                if not isinstance(value.get('source'), dict) or value['source'].get('type') != 'Model':
                    errors.append(f"{path}.transform is supported only for Model resources.")
                if not isinstance(transforms, list) or not transforms:
                    errors.append(f"{path}.transform must be a non-empty array.")
                else:
                    for transform in transforms:
                        if not isinstance(transform, dict) or transform.get('type') not in {'TranslateTransform', 'RotateTransform', 'ScaleTransform'} or not all(
                            finite(transform.get(axis)) for axis in ('x', 'y', 'z')):
                            errors.append(f"{path}.transform requires supported types and finite x, y and z values.")
                        elif transform['type'] == 'ScaleTransform' and any(transform[axis] == 0 for axis in ('x', 'y', 'z')):
                            errors.append(f"{path}.transform scale values must be non-zero.")
                result['warnings'].append('Model placement requires compatible viewer support; JSON-LD extension semantics are not checked.')
            return
        kind = value.get("type")
        if kind not in {"Image", "Model", "Sound", "Video", "Text", "Dataset"}:
            errors.append(f"{path}.type is not a supported content resource type.")
        identifier(value.get("id"), f"{path}.id")
        mime = value.get("format")
        if not isinstance(mime, str) or not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", mime) or not format_matches(kind, mime.lower()):
            errors.append(f"{path}.format must be a MIME type compatible with {kind}.")
        for dimension in ("width", "height", "duration"):
            if dimension in value and not positive(value[dimension], dimension != "duration"):
                errors.append(f"{path}.{dimension} must be positive {'integer' if dimension != 'duration' else 'number'}.")
        if canvas is not None:
            required = {"Image": ("width", "height"), "Sound": ("duration",), "Video": ("width", "height", "duration")}.get(kind, ())
            for dimension in required:
                if not positive(canvas.get(dimension), dimension != "duration"):
                    errors.append(f"{path}: painting {kind} requires Canvas {dimension}.")
            if kind in {"Sound", "Video"} and not positive(value.get("duration")):
                errors.append(f"{path}: supply a duration for painted {kind}, or use rendering.")
            if positive(value.get("duration")) and positive(canvas.get("duration")) and value["duration"] > canvas["duration"]:
                errors.append(f"{path}.duration exceeds the Canvas duration.")

    def renderings(owner, path):
        values = owner.get("rendering", [])
        if not isinstance(values, list):
            errors.append(f"{path}.rendering must be an array.")
            return
        for index, value in enumerate(values):
            subpath = f"{path}.rendering[{index}]"
            resource(value, subpath)
            if isinstance(value, dict):
                language_map(value.get("label"), f"{subpath}.label")

    contexts = manifest.get("@context")
    if contexts != V3_CONTEXT and not (isinstance(contexts, list) and contexts and contexts[-1] == V3_CONTEXT):
        errors.append("Manifest must declare the IIIF Presentation v3 context.")
    if manifest.get("type") != "Manifest":
        errors.append("Manifest type must be 'Manifest'.")
    identifier(manifest.get("id"), "Manifest.id", True)
    language_map(manifest.get("label"), "Manifest.label")
    renderings(manifest, "Manifest")
    if "summary" in manifest:
        language_map(manifest["summary"], "Manifest.summary")
    thumbnails = manifest.get("thumbnail", [])
    if not isinstance(thumbnails, list):
        errors.append("Manifest.thumbnail must be an array.")
    else:
        for index, thumbnail in enumerate(thumbnails):
            resource(thumbnail, f"Manifest.thumbnail[{index}]")
            if isinstance(thumbnail, dict) and thumbnail.get("type") != "Image":
                errors.append("Manifest thumbnails must be Images.")
    canvases = manifest.get("items")
    if not isinstance(canvases, list) or not canvases:
        errors.append("Manifest must contain at least one Canvas in items.")
        return result
    for ci, canvas in enumerate(canvases):
        path = f"Canvas[{ci}]"
        if not isinstance(canvas, dict) or canvas.get("type") != "Canvas":
            errors.append(f"{path} must be a Canvas object.")
            continue
        result["details"]["canvas_count"] += 1
        if 'label' in canvas:
            language_map(canvas['label'], f'{path}.label')
        identifier(canvas.get("id"), f"{path}.id", True)
        if isinstance(canvas.get("id"), str) and "#" in canvas["id"]:
            errors.append(f"{path}.id must not contain a fragment.")
        spatial = positive(canvas.get("width"), True) and positive(canvas.get("height"), True)
        if not spatial and not positive(canvas.get("duration")):
            errors.append(f"{path} requires positive width and height and/or duration.")
        for dimension in ("width", "height", "duration"):
            if dimension in canvas and not positive(canvas[dimension], dimension != "duration"):
                errors.append(f"{path}.{dimension} is invalid.")
        if ("width" in canvas) != ("height" in canvas):
            errors.append(f"{path} must supply width and height together.")
        renderings(canvas, path)
        pages = canvas.get("items")
        if not isinstance(pages, list) or (not pages and not canvas.get("rendering")):
            errors.append(f"{path} must contain an AnnotationPage or a rendering link.")
            continue
        for pi, page in enumerate(pages):
            ppath = f"{path}.AnnotationPage[{pi}]"
            if not isinstance(page, dict) or page.get("type") != "AnnotationPage":
                errors.append(f"{ppath} must be an AnnotationPage object.")
                continue
            identifier(page.get("id"), f"{ppath}.id", True)
            result["details"]["annotation_page_count"] += 1
            annotations = page.get("items")
            if not isinstance(annotations, list) or not annotations:
                errors.append(f"{ppath} must contain at least one Annotation.")
                continue
            for ai, annotation in enumerate(annotations):
                apath = f"{ppath}.Annotation[{ai}]"
                if not isinstance(annotation, dict) or annotation.get("type") != "Annotation":
                    errors.append(f"{apath} must be an Annotation object.")
                    continue
                identifier(annotation.get("id"), f"{apath}.id", True)
                result["details"]["annotation_count"] += 1
                motivation = annotation.get("motivation")
                if motivation != "painting" and motivation != ["painting"]:
                    errors.append(f"{apath}.motivation must be painting in Canvas items.")
                bodies = annotation.get("body")
                bodies = bodies if isinstance(bodies, list) else [bodies]
                if not bodies:
                    errors.append(f"{apath}.body must contain a content resource.")
                for bi, body in enumerate(bodies):
                    resource(body, f"{apath}.body[{bi}]", canvas)
                targets = annotation.get("target")
                targets = targets if isinstance(targets, list) else [targets]
                if not targets:
                    errors.append(f"{apath}.target must reference the Canvas.")
                for target in targets:
                    source = target.get("source") if isinstance(target, dict) and target.get("type") == "SpecificResource" else target
                    target_id = source.get("id") if isinstance(source, dict) else source
                    if target_id != canvas.get("id"):
                        errors.append(f"{apath}.target must reference its Canvas.")
                    if isinstance(source, dict) and source.get('type') != 'Canvas':
                        errors.append(f"{apath}.target source must be a Canvas.")
                    if isinstance(target, dict) and 'selector' in target:
                        selectors = target["selector"]
                        selectors = selectors if isinstance(selectors, list) else [selectors]
                        for selector in selectors:
                            if not isinstance(selector, dict) or selector.get("type") != "PointSelector" or not all(
                                finite(selector.get(axis)) for axis in ("x", "y", "z")):
                                errors.append(f"{apath}.target selector must be a finite PointSelector.")
    if not thumbnails:
        result["warnings"].append("Manifest has no thumbnail.")
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    result["valid"] = not errors
    return result


_CONTAINERS = {"Canvas", "Timeline", "Scene"}
_AGGREGATES = {"Choice", "Composite", "List", "Independents"}
_MEDIA_TYPES = {"Image", "Model", "Audio", "Video", "Text", "Dataset"}
_SCENE_COMPONENTS = {
    "PerspectiveCamera", "OrthographicCamera",
    "AmbientLight", "DirectionalLight", "PointLight", "SpotLight", "ImageBasedLight",
    "AmbientAudio", "PointAudio", "SpotAudio",
}
_TRANSFORMS = {"TranslateTransform", "RotateTransform", "ScaleTransform"}
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")
_MACHINE_READABLE_FORMATS = {
    "application/gzip", "application/json", "application/ld+json", "application/rdf+xml", "application/x-7z-compressed",
    "application/x-tar", "application/xml", "application/zip", "text/csv", "text/tab-separated-values", "text/xml",
}


def is_machine_readable(resource):
    mime = resource.get("format")
    return resource.get("type") == "Dataset" or (isinstance(mime, str) and mime.lower() in _MACHINE_READABLE_FORMATS)


def _reject_json_constant(value):
    raise ValueError(f"{value} is not a JSON number")


def _http_identifier(value):
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


_CC_LICENSE = re.compile(r"/licenses/(?:by(?:-nc)?(?:-sa|-nd)?)/(?:1\.0|2\.0|2\.5|3\.0|4\.0)(?:/[a-z]{2})?/?")
_CC_PUBLIC_DOMAIN = re.compile(r"/publicdomain/(?:zero|mark)/1\.0/?")
_RIGHTS_STATEMENTS = {
    "InC", "InC-EDU", "InC-NC", "InC-OW-EU", "InC-RUU", "NoC-CR",
    "NoC-NC", "NoC-OKLR", "NoC-US", "CNE", "UND", "NKC",
}


def valid_rights_uri(value):
    if not _http_identifier(value):
        return False
    uri = urlsplit(value)
    if uri.query or uri.fragment:
        return False
    if uri.netloc in {"creativecommons.org", "www.creativecommons.org"}:
        return bool(_CC_LICENSE.fullmatch(uri.path) or _CC_PUBLIC_DOMAIN.fullmatch(uri.path))
    if uri.netloc in {"rightsstatements.org", "www.rightsstatements.org"}:
        match = re.fullmatch(r"/vocab/([A-Za-z-]+)/1\.0/?", uri.path)
        return bool(match and match[1] in _RIGHTS_STATEMENTS)
    return False


def _geo_position(values):
    return (isinstance(values, list) and len(values) in (2, 3)
            and all(finite(value) for value in values)
            and -180 <= values[0] <= 180 and -90 <= values[1] <= 90)


def _geo_sequence(values, member, minimum=1):
    return isinstance(values, list) and len(values) >= minimum and all(member(value) for value in values)


def _geo_line(values):
    return _geo_sequence(values, _geo_position, 2)


def _geo_polygon(rings):
    def closed_ring(ring):
        return _geo_sequence(ring, _geo_position, 4) and ring[0] == ring[-1]

    return _geo_sequence(rings, closed_ring)


def _geo_geometry(geometry):
    pending = [geometry]
    coordinate_checks = {
        "Point": _geo_position,
        "MultiPoint": lambda values: _geo_sequence(values, _geo_position),
        "LineString": _geo_line,
        "MultiLineString": lambda values: _geo_sequence(values, _geo_line),
        "Polygon": _geo_polygon,
        "MultiPolygon": lambda values: _geo_sequence(values, _geo_polygon),
    }
    while pending:
        entry = pending.pop()
        kind = entry.get("type") if isinstance(entry, dict) else None
        if kind == "GeometryCollection":
            geometries = entry.get("geometries")
            if not isinstance(geometries, list):
                return False
            pending.extend(geometries)
        elif not isinstance(kind, str) or kind not in coordinate_checks or not coordinate_checks[kind](entry.get("coordinates")):
            return False
    return True


class _Presentation4Validator:
    """Check the manifest and media structures produced by WebHDP."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.identifiers = set()
        self.details = {
            "profile": PROFILE_VERSION,
            "scope": (
                "Local IIIF Presentation 4.0 release-candidate checks for manifest structure, "
                "media types, extents, placements and painting targets. JSON-LD expansion, "
                "referenced resources and viewer support are outside these checks."
            ),
            **dict.fromkeys(("canvas_count", "timeline_count", "scene_count",
                             "annotation_page_count", "annotation_count"), 0),
        }

    def finish(self):
        return {
            "valid": not self.errors,
            "status": "invalid" if self.errors else "validated",
            "errors": self.errors,
            "warnings": list(dict.fromkeys(self.warnings)),
            "details": self.details,
        }

    def identifier(self, value, path, *, unique=False):
        if not _http_identifier(value):
            self.errors.append(f"{path} must be an HTTP(S) identifier without credentials.")
        elif unique:
            if value in self.identifiers:
                self.errors.append(f"{path} duplicates another structural resource identifier.")
            self.identifiers.add(value)

    def language_map(self, value, path):
        if not (isinstance(value, dict) and value and all(
            isinstance(key, str) and key.strip() and isinstance(values, list) and values
            and all(isinstance(text, str) and text.strip() for text in values)
            for key, values in value.items()
        )):
            self.errors.append(f"{path} must be a non-empty IIIF language map.")

    def dimensions(self, owner, path, required=()):
        for key in ("width", "height", "duration"):
            if (key in owner or key in required) and not positive(owner.get(key), key != "duration"):
                requirement = "a positive integer" if key != "duration" else "a positive number"
                self.errors.append(f"{path}.{key} must be {requirement}.")

    def descriptive_fields(self, owner, path):
        if "metadata" in owner:
            metadata = owner["metadata"]
            if not isinstance(metadata, list):
                self.errors.append(f"{path}.metadata must be an array of label/value objects.")
            else:
                for index, entry in enumerate(metadata):
                    self.language_statement(entry, f"{path}.metadata[{index}]")
        if "requiredStatement" in owner:
            self.language_statement(owner["requiredStatement"], f"{path}.requiredStatement")
        if "rights" in owner and not valid_rights_uri(owner["rights"]):
            self.errors.append(f"{path}.rights must be a registered Creative Commons or RightsStatements.org URI.")
        if "provider" in owner:
            providers = owner["provider"]
            if not isinstance(providers, list) or not providers:
                self.errors.append(f"{path}.provider must be a non-empty array of Agents.")
                return
            for index, provider in enumerate(providers):
                self.provider(provider, f"{path}.provider[{index}]")

    def language_statement(self, entry, path):
        if not isinstance(entry, dict):
            self.errors.append(f"{path} must be a label/value object.")
            return
        for key in ("label", "value"):
            self.language_map(entry.get(key), f"{path}.{key}")

    def provider(self, provider, path):
        if not isinstance(provider, dict) or provider.get("type") != "Agent":
            self.errors.append(f"{path} must be an Agent object.")
            return
        self.identifier(provider.get("id"), f"{path}.id")
        self.language_map(provider.get("label"), f"{path}.label")
        if "summary" in provider:
            self.language_map(provider["summary"], f"{path}.summary")
        self.resource_lists(provider, path, keys=("homepage", "logo", "seeAlso"))

    def resource_lists(self, owner, path, keys=("rendering", "thumbnail", "seeAlso")):
        for key in keys:
            if key not in owner:
                continue
            values = owner[key]
            if not isinstance(values, list):
                self.errors.append(f"{path}.{key} must be an array of resources.")
                continue
            for index, resource in enumerate(values):
                entry_path = f"{path}.{key}[{index}]"
                self.resource(resource, entry_path)
                if not isinstance(resource, dict):
                    continue
                if key in {"rendering", "homepage"}:
                    self.language_map(resource.get("label"), f"{entry_path}.label")
                if key == "rendering" and is_machine_readable(resource):
                    self.errors.append(f"{entry_path} must be directly viewable. Link machine-readable datasets with seeAlso.")
                if key == "logo" and resource.get("type") != "Image":
                    self.errors.append(f"{entry_path} must be an Image.")

    def check_embedded_contexts(self, manifest):
        service_keys = {"service", "services"}
        pending = [(value, f"Manifest.{key}", key in service_keys) for key, value in manifest.items() if key != "@context"]
        while pending:
            value, path, is_service = pending.pop()
            if isinstance(value, dict):
                if "@context" in value:
                    context = value["@context"]
                    entries = context if isinstance(context, list) else [context]
                    presentation_context = any(entry in (CONTEXT, CONTEXT.replace("http:", "https:", 1)) for entry in entries)
                    messages = self.warnings if is_service and not presentation_context else self.errors
                    messages.append(f"{path}.@context belongs on the Manifest.")
                pending.extend((item, f"{path}.{key}", key in service_keys) for key, item in value.items() if key != "@context")
            elif isinstance(value, list):
                pending.extend((item, f"{path}[{index}]", is_service) for index, item in enumerate(value))

    def nav_place(self, owner, path):
        if "navPlace" not in owner:
            return
        place = owner["navPlace"]
        path = f"{path}.navPlace"
        if not isinstance(place, dict) or place.get("type") != "FeatureCollection":
            self.errors.append(f"{path} must be a GeoJSON FeatureCollection.")
            return
        if "id" in place or "features" not in place:
            self.identifier(place.get("id"), f"{path}.id")
        if "features" not in place:
            return
        features = place["features"]
        if not isinstance(features, list) or not features:
            self.errors.append(f"{path}.features must be a non-empty array.")
            return
        for index, feature in enumerate(features):
            entry = f"{path}.features[{index}]"
            if not isinstance(feature, dict) or feature.get("type") != "Feature" or "geometry" not in feature:
                self.errors.append(f"{entry} must be a GeoJSON Feature with geometry.")
                continue
            if "properties" not in feature or (feature["properties"] is not None and not isinstance(feature["properties"], dict)):
                self.errors.append(f"{entry}.properties must be a JSON object or null.")
            geometry = feature["geometry"]
            if geometry is not None and not _geo_geometry(geometry):
                self.errors.append(f"{entry}.geometry must be valid GeoJSON using longitude, latitude and optional altitude.")

    def validate(self, content):
        try:
            manifest = json.loads(content, parse_constant=_reject_json_constant)
        except (TypeError, ValueError, RecursionError) as exc:
            self.errors.append(f"JSON Syntax Error: {exc}")
            return self.finish()
        if not isinstance(manifest, dict):
            self.errors.append("Manifest root must be a JSON object.")
            return self.finish()
        context = manifest.get("@context")
        main_context = context[-1] if isinstance(context, list) and context else context
        context_uris = (CONTEXT, CONTEXT.replace("http:", "https:", 1))
        if main_context not in context_uris:
            self.errors.append("Manifest must declare the IIIF Presentation v4 context.")
        elif isinstance(context, list) and any(entry in context_uris for entry in context[:-1]):
            self.errors.append("The IIIF Presentation v4 context must appear only once.")
        self.check_embedded_contexts(manifest)
        if "@graph" in manifest:
            self.errors.append("Manifest must not use a top-level @graph.")
        if manifest.get("type") != "Manifest":
            self.errors.append("Manifest type must be 'Manifest'.")
        self.identifier(manifest.get("id"), "Manifest.id", unique=True)
        self.language_map(manifest.get("label"), "Manifest.label")
        if "summary" in manifest:
            self.language_map(manifest["summary"], "Manifest.summary")
        self.descriptive_fields(manifest, "Manifest")
        self.nav_place(manifest, "Manifest")
        self.resource_lists(manifest, "Manifest")
        if not manifest.get("thumbnail"):
            self.warnings.append("Manifest has no thumbnail.")
        items = manifest.get("items")
        if not isinstance(items, list) or not items:
            self.errors.append("Manifest must contain at least one Canvas, Timeline or Scene in items.")
        else:
            for index, item in enumerate(items):
                self.container(item, f"Manifest.items[{index}]")
        return self.finish()

    def container(self, container, path):
        kind = container.get("type") if isinstance(container, dict) else None
        if not isinstance(kind, str) or kind not in _CONTAINERS:
            self.errors.append(f"{path} must be a Canvas, Timeline or Scene object.")
            return
        self.details[f"{kind.lower()}_count"] += 1
        identifier = container.get("id")
        self.identifier(identifier, f"{path}.id", unique=True)
        if isinstance(identifier, str) and "#" in identifier:
            self.errors.append(f"{path}.id must not contain a fragment.")
        if "label" in container:
            self.language_map(container["label"], f"{path}.label")
        self.descriptive_fields(container, path)
        self.nav_place(container, path)
        required = {"Canvas": ("width", "height"), "Timeline": ("duration",)}.get(kind, ())
        self.dimensions(container, path, required)
        if kind != "Canvas" and any(key in container for key in ("width", "height")):
            self.errors.append(f"{path}: {kind} does not have bounded width or height.")
        self.resource_lists(container, path)
        if "items" not in container:
            return
        pages = container["items"]
        if not isinstance(pages, list) or not pages:
            self.errors.append(f"{path}.items must be a non-empty array of AnnotationPages when supplied.")
            return
        for index, page in enumerate(pages):
            self.page(page, f"{path}.items[{index}]", container)

    def page(self, page, path, container):
        if not isinstance(page, dict) or page.get("type") != "AnnotationPage":
            self.errors.append(f"{path} must be an AnnotationPage object.")
            return
        self.identifier(page.get("id"), f"{path}.id", unique=True)
        self.descriptive_fields(page, path)
        self.details["annotation_page_count"] += 1
        if "items" not in page:
            self.warnings.append("Referenced AnnotationPages are not fetched by local validation.")
            return
        annotations = page["items"]
        if not isinstance(annotations, list):
            self.errors.append(f"{path}.items must be an array of Annotations.")
            return
        for index, annotation in enumerate(annotations):
            self.annotation(annotation, f"{path}.items[{index}]", container)

    def annotation(self, annotation, path, container):
        if not isinstance(annotation, dict) or annotation.get("type") != "Annotation":
            self.errors.append(f"{path} must be an Annotation object.")
            return
        self.identifier(annotation.get("id"), f"{path}.id", unique=True)
        self.descriptive_fields(annotation, path)
        self.nav_place(annotation, path)
        self.details["annotation_count"] += 1
        motivation = annotation.get("motivation")
        if not isinstance(motivation, list) or not motivation or not all(
            isinstance(value, str) and value for value in motivation
        ):
            self.errors.append(f"{path}.motivation must be a non-empty array of strings.")
        elif "painting" not in motivation:
            self.errors.append(f"{path}.motivation must include painting in Container items.")
        if "bodyValue" in annotation:
            self.errors.append(f"{path}.bodyValue is unavailable in IIIF. Use a TextualBody.")
        self.resource(annotation.get("body"), f"{path}.body", container)
        self.painting_target(annotation.get("target"), f"{path}.target", container)

    def resource(self, value, path, container=None):
        kind = value.get("type") if isinstance(value, dict) else None
        if not isinstance(kind, str) or not kind:
            self.errors.append(f"{path} must be a typed resource object.")
            return
        self.descriptive_fields(value, path)
        if kind == "Sound":
            self.errors.append(f"{path}.type must use Audio for IIIF Presentation 4.")
        if kind in _AGGREGATES:
            items = value.get("items")
            if not isinstance(items, list) or not items:
                self.errors.append(f"{path}.items must be a non-empty resource array.")
                return
            for index, item in enumerate(items):
                self.resource(item, f"{path}.items[{index}]", container)
            return
        if kind == "SpecificResource":
            self.identifier(value.get("id"), f"{path}.id")
            self.selectors(value, path)
            self.transforms(value, path, container)
            source = value.get("source")
            if isinstance(source, dict):
                reference = source.get("id")
                if not _http_identifier(reference):
                    self.errors.append(f"{path}.source requires a typed source with an HTTP(S) id.")
                else:
                    self.require_unfragmented_source(reference, path)
            self.resource(source, f"{path}.source", container)
            self.dimensions(value, path)
            self.require_temporal_container(value, path, container)
            return
        if kind == "TextualBody":
            if not isinstance(value.get("value"), str):
                self.errors.append(f"{path}.value must be a string.")
            return
        # Typed extension resources can be referenced by HTTP(S) identifier. Check
        # MIME compatibility only where the type's media family is known.
        if kind not in _SCENE_COMPONENTS or "id" in value:
            self.identifier(value.get("id"), f"{path}.id")
        mime = value.get("format")
        if "format" in value and (not isinstance(mime, str) or not _MEDIA_TYPE.fullmatch(mime)
                                  or (kind in _MEDIA_TYPES and not format_matches(kind, mime.lower()))):
            self.errors.append(f"{path}.format must be a MIME type compatible with {kind}.")
        self.dimensions(value, path)
        if container is None:
            return
        target_kind = container["type"]
        if kind in {"Model", "Scene"} | _SCENE_COMPONENTS and target_kind != "Scene":
            self.errors.append(f"{path}: paint {kind} into a Scene.")
        if kind in {"Image", "Video"} and target_kind != "Canvas":
            self.errors.append(f"{path}: paint {kind} into a Canvas before placing it in a Scene.")
        if kind == "Canvas" and target_kind == "Timeline":
            self.errors.append(f"{path}: a Timeline does not have spatial dimensions for Canvas.")
        if kind in {"Audio", "Video", "Timeline"} and not positive(container.get("duration")):
            self.errors.append(f"{path}: painting {kind} requires a Container duration.")
        if kind in {"Audio", "Timeline"} and target_kind == "Scene":
            self.errors.append(f"{path}: use an audio emitter to place {kind} in a Scene.")
        self.require_temporal_container(value, path, container)

    def require_temporal_container(self, resource, path, container):
        if container is not None and positive(resource.get("duration")) and not positive(container.get("duration")):
            self.errors.append(f"{path}: timed content requires a Container duration.")

    def require_unfragmented_source(self, reference, path):
        fragment = urldefrag(reference).fragment
        if any(key in {"t", "xywh"} for key, _ in parse_qsl(fragment)):
            self.errors.append(f"{path}.source id must not include a media fragment. Use a selector.")

    def transforms(self, value, path, container):
        if "transform" not in value:
            return
        if container is not None and container["type"] != "Scene":
            self.errors.append(f"{path}.transform requires a Scene for painting.")
        transforms = value["transform"]
        if not isinstance(transforms, list) or not transforms:
            self.errors.append(f"{path}.transform must be a non-empty array.")
            return
        for index, transform in enumerate(transforms):
            entry = f"{path}.transform[{index}]"
            kind = transform.get("type") if isinstance(transform, dict) else None
            if not isinstance(kind, str) or kind not in _TRANSFORMS:
                self.errors.append(f"{entry} must be a supported transform object.")
                continue
            axes = [transform[axis] for axis in ("x", "y", "z") if axis in transform]
            if not all(finite(axis) for axis in axes):
                self.errors.append(f"{entry} coordinates must be finite numbers.")
            elif kind == "ScaleTransform" and 0 in axes:
                self.errors.append(f"{entry} scale values must be non-zero.")

    def painting_target(self, target, path, container):
        kind = target.get("type") if isinstance(target, dict) else None
        if not isinstance(kind, str) or not kind:
            self.errors.append(f"{path} must be a typed target object.")
            return
        if kind in _AGGREGATES:
            items = target.get("items")
            if not isinstance(items, list) or not items:
                self.errors.append(f"{path}.items must be a non-empty target array.")
                return
            for index, item in enumerate(items):
                self.painting_target(item, f"{path}.items[{index}]", container)
            return
        if kind == "SpecificResource":
            self.identifier(target.get("id"), f"{path}.id")
            self.selectors(target, path, container)
            source = target.get("source")
        else:
            source = target
        if not isinstance(source, dict) or source.get("type") != container.get("type"):
            self.errors.append(f"{path} source must be its {container['type']}.")
            return
        reference = source.get("id")
        self.identifier(reference, f"{path} source id")
        if not _http_identifier(reference):
            return
        base, fragment = urldefrag(reference)
        if base != container.get("id"):
            self.errors.append(f"{path} must reference its Container.")
        if kind == "SpecificResource":
            self.require_unfragmented_source(reference, path)
        elif fragment:
            self.media_fragment(fragment, path, container)

    def selectors(self, value, path, container=None):
        if "selector" not in value:
            return
        selectors = value["selector"]
        if not isinstance(selectors, list) or not selectors:
            self.errors.append(f"{path}.selector must be a non-empty array of Selector objects.")
            return
        for index, selector in enumerate(selectors):
            entry = f"{path}.selector[{index}]"
            kind = selector.get("type") if isinstance(selector, dict) else None
            if not isinstance(kind, str) or not kind:
                self.errors.append(f"{entry} must be a typed Selector object.")
            elif kind == "PointSelector":
                for axis in ("x", "y", "z", "instant"):
                    if axis not in selector:
                        continue
                    coordinate = selector[axis]
                    if not finite(coordinate) or (axis == "instant" and coordinate < 0):
                        self.errors.append(f"{entry}.{axis} must be a finite coordinate.")
                    elif container is not None and not self.point_in_bounds(axis, coordinate, container):
                        self.errors.append(f"{entry}.{axis} is outside the extent of its Container.")
            elif kind == "FragmentSelector":
                fragment = selector.get("value")
                if not isinstance(fragment, str) or not fragment:
                    self.errors.append(f"{entry}.value must be a fragment string.")
                elif container is not None:
                    self.media_fragment(fragment.removeprefix("#"), entry, container)

    @staticmethod
    def point_in_bounds(axis, coordinate, container):
        if axis == "instant":
            duration = container.get("duration")
            return positive(duration) and coordinate <= duration
        if container["type"] == "Scene":
            return True
        dimension = container.get({"x": "width", "y": "height"}.get(axis))
        return positive(dimension) and 0 <= coordinate <= dimension

    def media_fragment(self, fragment, path, container):
        for key, raw in parse_qsl(fragment):
            if key == "t":
                extent = container.get("duration")
                try:
                    parts = raw.removeprefix("npt:").split(",")
                    start = float(parts[0]) if parts[0] else 0
                    end = float(parts[1]) if len(parts) == 2 and parts[1] else extent
                    valid = (len(parts) <= 2 and positive(extent) and finite(start) and finite(end)
                             and 0 <= start <= end <= extent)
                except ValueError:
                    valid = False
                if not valid:
                    self.errors.append(f"{path} has a temporal fragment outside its Container extent.")
            elif key == "xywh":
                width, height = container.get("width"), container.get("height")
                if raw.startswith("percent:") and positive(width) and positive(height):
                    width, height = 100, 100
                try:
                    x, y, w, h = map(float, raw.removeprefix("pixel:").removeprefix("percent:").split(","))
                    valid = (all(finite(number) for number in (x, y, w, h))
                             and positive(width) and positive(height)
                             and x >= 0 and y >= 0 and w > 0 and h > 0
                             and x + w <= width and y + h <= height)
                except ValueError:
                    valid = False
                if not valid:
                    self.errors.append(f"{path} has a spatial fragment outside its Container extent.")


def validate_manifest(content):
    """Validate a WebHDP manifest against the local Presentation 4 RC profile."""
    return _Presentation4Validator().validate(content)
