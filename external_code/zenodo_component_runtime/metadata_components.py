"""Reviewed file-contract adapters for the three published metadata processors.

The unmodified GPL-3.0-or-later processors live under upstream/. These adapters
add input confinement, portable finite JSON, and explicitly identified fixes.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import struct
import warnings

try:
    from .common import staged_file, safe_unpack, sha256, write_json
except ImportError:
    from common import staged_file, safe_unpack, sha256, write_json


RECORDS = {
    "mtl_metadata_extractor": (16993305, "MTLMetadataProcessor"),
    "glb_metadata_extractor": (16993202, "GLBMetadataProcessor"),
    "image_metadata_extractor": (16944352, "ImageMetadataProcessor"),
}
DEFAULTS = {
    "mtl_metadata_extractor": dict(validate_texture_files=True, include_material_analysis=True,
                                   search_texture_directories=True, parse_advanced_properties=True),
    "glb_metadata_extractor": dict(include_detailed_primitives=True, calculate_volume=True, include_extension_details=True),
    "image_metadata_extractor": dict(remove_address=True, remove_mail=True, include_technical_details=True,
                                     readable_maker_notes_only=True, include_hash=True, remove_gps=True),
}


def _upstream(component):
    source = Path(__file__).parent / "upstream" / component / "processor.py"
    spec = importlib.util.spec_from_file_location("webhdp_published_" + component, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, RECORDS[component][1]), source


def _parameters(component, supplied):
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS[component]):
        raise ValueError("Unknown metadata extraction parameter")
    values = {**DEFAULTS[component], **supplied}
    if any(type(value) is not bool for value in values.values()):
        raise ValueError("Metadata extraction parameters must be booleans")
    return values


def _confined(base, name, root):
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", name):
        raise ValueError("Resource references must be relative staged file paths")
    path = Path(name)
    if path.is_absolute():
        raise ValueError("Absolute resource references are not allowed")
    candidate = base / path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Resource reference escapes the staged input directory")
    if candidate.is_symlink():
        raise ValueError("Resource symlinks are not allowed")
    return resolved


def _source(component, inputs, output):
    path = staged_file(inputs)
    root = Path(os.environ.get("WEBHDP_INPUT_DIR", "/inputs")).resolve()
    if path.suffix.lower() == ".zip":
        if component == "image_metadata_extractor":
            raise ValueError("Image metadata requires a single image, not an archive")
        root = output / "input-bundle"
        safe_unpack(path, root)
        suffixes = {".glb", ".gltf"} if component == "glb_metadata_extractor" else {".obj"}
        candidates = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)
        if not candidates and component == "mtl_metadata_extractor":
            candidates = sorted(root.rglob("*.mtl"))
        if len(candidates) != 1:
            raise ValueError("A metadata bundle must contain exactly one primary model")
        path = candidates[0]
    return path, root


def _clean(value, root):
    """No non-finite JSON numbers or container-local paths in returned metadata."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _clean(item, root) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), ".")
    return value


def _texture_tokens(line):
    tokens = shlex.split(line, comments=True, posix=True)
    options, index = {}, 0
    fixed = {"-blendu": 1, "-blendv": 1, "-boost": 1, "-mm": 2, "-texres": 1,
             "-clamp": 1, "-bm": 1, "-imfchan": 1, "-type": 1, "-cc": 1}
    while index < len(tokens) and tokens[index].startswith("-"):
        key = tokens[index]
        index += 1
        if key in {"-o", "-s", "-t"}:
            values = []
            while index < len(tokens) and len(values) < 3:
                try:
                    float(tokens[index])
                except ValueError:
                    break
                values.append(tokens[index])
                index += 1
            if not values:
                raise ValueError("Texture vector option is missing its values")
        elif key in fixed:
            count = fixed[key]
            values = tokens[index:index + count]
            if len(values) != count:
                raise ValueError("Texture option is missing its values")
            index += count
        else:
            raise ValueError("Unknown texture option: " + key)
        options[key.lstrip("-")] = values[0] if len(values) == 1 else values
    filename = " ".join(tokens[index:])
    if not filename:
        raise ValueError("Texture reference has no filename")
    return filename, options


def _mtl(source, root, parameters, upstream):
    if source.suffix.lower() not in {".mtl", ".obj"}:
        raise ValueError("MTL metadata requires an OBJ, MTL, or model ZIP")
    if source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("Text model metadata input exceeds 128 MiB")
    obj_root = source.parent

    class ConfinedMTL(upstream):
        def _extract_mtl_references(self, obj_path):
            references = []
            for line in obj_path.read_text(encoding="utf-8", errors="strict").splitlines():
                fields = line.strip().split(None, 1)
                if len(fields) != 2 or fields[0] != "mtllib":
                    continue
                whole = fields[1].strip()
                # Preserve an unquoted filename containing spaces when it exists.
                names = [whole] if _confined(obj_path.parent, whole, root).is_file() else shlex.split(whole, comments=True)
                for name in names:
                    _confined(obj_path.parent, name, root)
                    references.append(name)
            return references

        def _parse_mtl_file(self, mtl_path, base_dir):
            _confined(mtl_path.parent, mtl_path.name, root)
            return super()._parse_mtl_file(mtl_path, mtl_path.parent)

        def _find_texture_file(self, filename, base_dir):
            candidate = _confined(base_dir, filename, root)
            if candidate.is_file():
                return candidate
            if self.search_texture_directories:
                for directory in self.common_texture_dirs:
                    try:
                        candidate = _confined(base_dir / directory, filename, root)
                    except ValueError:
                        continue
                    if candidate.is_file():
                        return candidate
            return None

        def _parse_texture_definition(self, line, base_dir):
            filename, options = _texture_tokens(line)
            resolved = _confined(base_dir, filename, root)
            found = self._find_texture_file(filename, base_dir) if self.validate_texture_files else None
            # Aggregate texture analysis in the upstream class uses the OBJ root.
            portable = os.path.relpath(found or resolved, obj_root)
            return {"filename": portable, "original_filename": filename, "exists": bool(found),
                    "full_path": str(found) if found else None, "options": options,
                    "file_size": found.stat().st_size if found else None}

    processor = ConfinedMTL(**parameters, version="0.1.0+webhdp.1")
    references = processor._extract_mtl_references(source) if source.suffix.lower() == ".obj" else [source.name]
    # Preflight every texture reference before the source processor's error
    # collector can turn an unsafe path into an ordinary parsing warning.
    for reference in references:
        mtl = _confined(source.parent, reference, root)
        if not mtl.is_file():
            continue
        for line in mtl.read_text(encoding="utf-8", errors="strict").splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0] in processor.texture_keys:
                filename, _ = _texture_tokens(parts[1])
                _confined(mtl.parent, filename, root)
    if source.suffix.lower() == ".obj":
        report = processor.process(source)
    else:
        report = {"success": True, "input_file": str(source), "errors": [], "warnings": [],
                  "results": processor._process_mtl_files(source.with_suffix(".obj"), [source.name])}
    results = report.get("results", {})
    report.setdefault("warnings", []).extend(
        f"Material library {item['filename']}: {item['error']}" for item in results.get("missing_mtl_files", []))
    report["method_notes"] = ["Published MTL processor with confined resource resolution and corrected texture option/filename parsing."]
    return report, results.get("summary", {})


def _glb(source, root, parameters, upstream):
    if source.suffix.lower() not in {".gltf", ".glb"}:
        raise ValueError("GLB metadata requires GLB, glTF, or a model ZIP")
    if source.suffix.lower() == ".glb":
        with source.open("rb") as stream:
            header = stream.read(20)
            if len(header) != 20:
                raise ValueError("Incomplete GLB header")
            magic, version, length, json_length, chunk_type = struct.unpack("<5I", header)
            if magic != 0x46546C67 or version != 2 or length != source.stat().st_size or chunk_type != 0x4E4F534A or json_length > length - 20:
                raise ValueError("Invalid GLB header or JSON chunk")
            data = json.loads(stream.read(json_length).decode("utf-8"))
    else:
        data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or str((data.get("asset") or {}).get("version")) != "2.0":
        raise ValueError("A glTF 2.0 asset is required")
    for resource in [*data.get("buffers", []), *data.get("images", [])]:
        uri = resource.get("uri")
        if uri and not uri.startswith("data:"):
            from urllib.parse import unquote
            _confined(source.parent, unquote(uri), root)
    report = upstream(**parameters).process(source)
    stats = report.get("results", {})
    triangle_count = 0
    for mesh in data.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            accessor = primitive.get("indices", (primitive.get("attributes") or {}).get("POSITION"))
            if accessor is None:
                continue
            if type(accessor) is not int or not 0 <= accessor < len(data.get("accessors", [])):
                raise ValueError("Primitive references an invalid accessor")
            count = data["accessors"][accessor].get("count", 0)
            if type(count) is not int or count < 0:
                raise ValueError("Accessor count must be a nonnegative integer")
            mode = primitive.get("mode", 4)
            triangle_count += count // 3 if mode == 4 else max(0, count - 2) if mode in {5, 6} else 0
    if stats:
        stats.setdefault("summary", {})["total_triangles"] = triangle_count
        bounds = stats.get("bounding_box", {})
        available = all(type(v) in (int, float) and math.isfinite(v) for values in bounds.values() for v in values) if bounds else False
        stats["bounds_available"] = available
        if not available:
            stats["bounding_box"] = None
            stats["dimensions"] = None
            stats["bounding_box_diagonal"] = None
            if parameters["calculate_volume"]:
                stats["approximate_volume"] = None
        stats["bounding_box_coordinate_space"] = "mesh-local declared accessor bounds; scene transforms are not applied"
        stats["volume_interpretation"] = "axis-aligned bounding-box product, not enclosed mesh volume"
    report["method_notes"] = ["Published GLB processor with non-indexed/strip/fan triangle counts and finite missing-bounds reporting.",
                              "Metadata extraction is not a full glTF conformance validation; counts describe stored primitives rather than scene instances."]
    return report, {key: stats.get(key) for key in ("meshes", "nodes", "materials", "total_vertices")} | {"triangles": triangle_count}


def _image(source, root, parameters, upstream):
    from PIL import Image
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source) as image:
            image.verify()
    settings = {key: value for key, value in parameters.items() if key not in {"include_hash", "remove_gps"}}
    class PortableExif(upstream):
        def _extract_exif_data(self, image):
            # Pillow's public EXIF API also covers TIFF/PNG; the upstream private
            # JPEG-specific method silently discards EXIF for those formats.
            class ExifView:
                def _getexif(self):
                    values = image.getexif()
                    combined = dict(values)
                    if 34665 in values:
                        combined.update(values.get_ifd(34665))
                    if 34853 in values:
                        combined[34853] = values.get_ifd(34853)
                    return combined
            return super()._extract_exif_data(ExifView())

    report = PortableExif(**settings, version="0.1.1+webhdp.1").process(source)
    values = report.get("results", {})
    exif = values.get("exif_data", {})
    if parameters["remove_gps"]:
        exif["data"] = {key: value for key, value in exif.get("data", {}).items() if not key.startswith("GPS")}
        if "categorized" in exif:
            exif["categorized"].pop("location", None)
        if "total_fields" in exif:
            exif["total_fields"] = len(exif["data"])
    values.setdefault("privacy_applied", {})["gps_removed"] = parameters["remove_gps"]
    if parameters["include_hash"]:
        values.setdefault("basic_info", {})["sha256"] = sha256(source)
    report["method_notes"] = ["Published image/EXIF processor with portable Pillow EXIF access; GPS fields may additionally be withheld from this report.",
                              "Text filtering is heuristic and does not guarantee anonymization. The source image is never rewritten."]
    return report, {key: values.get("basic_info", {}).get(key) for key in ("width", "height", "format", "mode")}


def run(component, inputs, parameters, output):
    if component not in RECORDS:
        raise ValueError("Unknown metadata component")
    settings = _parameters(component, parameters)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source, root = _source(component, inputs, output)
    upstream, processor_source = _upstream(component)
    report, summary = {"mtl_metadata_extractor": _mtl, "glb_metadata_extractor": _glb,
                       "image_metadata_extractor": _image}[component](source, root, settings, upstream)
    if not report.get("success"):
        raise ValueError("; ".join(report.get("errors") or ["Metadata extraction failed"]))
    report["source_provenance"] = {"doi": f"10.5281/zenodo.{RECORDS[component][0]}",
                                   "processor_sha256": sha256(processor_source), "license": "GPL-3.0-or-later"}
    report["input_sha256"] = sha256(source)
    report["parameters"] = settings
    report_path = output / f"{component}-report.json"
    write_json(report_path, _clean(report, root))
    return {"metadata_report": report_path}, _clean(summary, root)
