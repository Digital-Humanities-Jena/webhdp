"""Local Presentation 3 profile checks, without fetching referenced resources."""
import json
import math
import re
from urllib.parse import urlsplit

CONTEXT = "http://iiif.io/api/presentation/3/context.json"
PROFILE_VERSION = "presentation-3-media-2"
MODEL_FORMATS = {"model/gltf-binary", "model/gltf+json", "model/obj", "model/stl",
                 "application/ply", "application/fbx", "application/x-3ds", "application/x-blender",
                 "model/vnd.collada+xml", "application/octet-stream"}
TEXT_FORMATS = {"application/pdf", "application/xml", "application/epub+zip", "application/rtf",
                "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.oasis.opendocument.text"}


def content_type(asset):
    return {"3d_model": "Model", "image": "Image", "audio": "Sound", "video": "Video",
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
    prefix = {"Image": "image/", "Sound": "audio/", "Video": "video/"}.get(kind)
    return mime.startswith(prefix) if prefix else kind == "Dataset"


def validate_manifest(content):
    result = {"valid": False, "errors": [], "warnings": [], "details": {
        "profile": PROFILE_VERSION, "scope": "Local structure, media types, extents and annotation targets; referenced files and viewer support are not checked.",
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
    if contexts != CONTEXT and not (isinstance(contexts, list) and contexts and contexts[-1] == CONTEXT):
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
