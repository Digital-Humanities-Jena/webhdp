"""Prepare a small, portable 3D publication bundle with CPU-only inspection."""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import stat
import struct
from urllib.parse import quote, unquote
import zipfile
import zlib

from PIL import Image, UnidentifiedImageError


MAX_UPLOAD_BYTES = 24 * 1024 * 1024
MAX_EXPANDED_BYTES = 48 * 1024 * 1024
MAX_DOCUMENT_BYTES = 12 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 250
MAX_TEXTURES = 32
MAX_VERTICES = 2_000_000
MODEL_SUFFIXES = {".glb", ".gltf", ".obj"}
IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png"}
MSF_SUFFIXES = {".csv", ".xlsx"}
MSF_NAMES = {"metadata", "msf"}
MIME_BY_FORMAT = {"PNG": "image/png", "JPEG": "image/jpeg"}
MTL_MAPS = {"bump", "decal", "disp", "norm", "refl"}
MTL_OPTION_LENGTHS = {
    "-blendu": 1, "-blendv": 1, "-boost": 1, "-cc": 1, "-clamp": 1,
    "-texres": 1, "-bm": 1, "-imfchan": 1, "-type": 1, "-mm": 2,
}
OBJ_DIRECTIVES = {"v", "vt", "vn", "vp", "f", "l", "p", "o", "g", "s", "usemtl", "mtllib"}
MTL_VALUES = {"newmtl", "ka", "kd", "ks", "ke", "tf", "tr", "d", "ns", "ni", "illum", "pr", "pm", "ps", "pc", "pcr", "aniso", "anisor"}


def _safe_part(part: str) -> bool:
    return (
        0 < len(part.encode("utf-8")) <= 180
        and part not in {".", ".."}
        and not part.endswith((".", " "))
        and all(character not in '<>:"\\|?*#' and not (ord(character) < 32 or 127 <= ord(character) <= 159) for character in part)
    )


def _archive_members(bundle: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members = bundle.infolist()
    if len(members) > MAX_ENTRIES:
        raise ValueError(f"The ZIP can contain at most {MAX_ENTRIES} entries.")
    result, paths, total = {}, {}, 0
    for item in members:
        parts = item.filename.removesuffix("/").split("/")
        if (
            item.filename != item.orig_filename
            or not all(_safe_part(part) for part in parts)
            or len(parts) > 16
            or item.flag_bits & 1
            or stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG, stat.S_IFDIR}
        ):
            raise ValueError("Use a ZIP with portable filenames and regular, unencrypted files.")
        for index in range(1, len(parts) + 1):
            path = "/".join(parts[:index])
            if paths.setdefault(path.casefold(), path) != path:
                raise ValueError("The ZIP contains paths that differ only by letter case.")
        if item.is_dir():
            continue
        total += item.file_size
        if total > MAX_EXPANDED_BYTES:
            raise ValueError("The unpacked ZIP exceeds 48 MiB.")
        if item.filename in result:
            raise ValueError("The ZIP contains a duplicate path.")
        result[item.filename] = item
    if any(
        "/".join(PurePosixPath(path).parts[:index]) in result
        for path in result for index in range(1, len(PurePosixPath(path).parts))
    ):
        raise ValueError("The ZIP uses the same path for a file and a folder.")
    return result


def _reference(base: str, reference: str, *, uri: bool = False) -> str:
    if uri:
        if re.search(r"%(?![0-9a-fA-F]{2})", reference) or any(c in reference for c in "?#"):
            raise ValueError("A glTF resource has an invalid local URI.")
        reference = unquote(reference, errors="strict")
    parts = reference.split("/")
    if not all(part in {".", ".."} or _safe_part(part) for part in parts):
        raise ValueError("Model dependencies must use local relative paths.")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), reference))
    if resolved in {".", ".."} or resolved.startswith("../"):
        raise ValueError("A model reference leaves the uploaded bundle.")
    return resolved


def _single_typo(expected: str, candidate: str) -> bool:
    if min(len(expected), len(candidate)) < 6 or abs(len(expected) - len(candidate)) > 1:
        return False
    if len(expected) == len(candidate):
        differences = [index for index, character in enumerate(expected) if character != candidate[index]]
        return len(differences) == 1 or (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and expected[differences[0]:differences[1] + 1] == candidate[differences[0]:differences[1] + 1][::-1]
        )
    shorter, longer = sorted((expected, candidate), key=len)
    first = next((index for index, character in enumerate(shorter) if character != longer[index]), len(shorter))
    return shorter[first:] == longer[first + 1:]


class UnreadableTexture(ValueError):
    """A recognizable PNG or JPEG whose contents could not be decoded."""


def _image_mime(raw: bytes) -> str:
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("A texture exceeds 8 MiB.")
    try:
        with Image.open(io.BytesIO(raw), formats=tuple(MIME_BY_FORMAT)) as image:
            if image.width * image.height > 8_000_000 or getattr(image, "n_frames", 1) != 1:
                raise ValueError("A texture must be a still image with at most 8 million pixels.")
            mime = MIME_BY_FORMAT[image.format]
            image.verify()
        with Image.open(io.BytesIO(raw), formats=tuple(MIME_BY_FORMAT)) as image:
            image.load()
    except Image.DecompressionBombError as error:
        raise ValueError("A texture exceeds the supported pixel limit.") from error
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        if raw.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
            raise UnreadableTexture("A PNG or JPEG texture is damaged.") from error
        raise ValueError("A texture must be a readable PNG or JPEG image.") from error
    return mime


class _Bundle:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.output = {}
        self.repairs = []
        self.warnings = []
        self.image_mimes = {}
        self.texture_count = 0
        self.images = [PurePosixPath(path) for path in files if PurePosixPath(path).suffix.lower() in IMAGE_SUFFIXES]

    def texture(self, base: str, reference: str, *, uri: bool = False) -> tuple[str | None, str | None]:
        self.texture_count += 1
        if self.texture_count > MAX_TEXTURES:
            raise ValueError(f"A model may reference at most {MAX_TEXTURES} texture maps.")
        requested = _reference(base, reference, uri=uri)
        if PurePosixPath(requested).suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError("External model textures must use PNG or JPEG filenames.")
        actual = requested if requested in self.files else None
        if not actual:
            expected = PurePosixPath(requested)
            candidates = [image for image in self.images if image.name.casefold() == expected.name.casefold()]
            if not candidates:
                candidates = [image for image in self.images if image.stem.casefold() == expected.stem.casefold()]
            if not candidates:
                candidates = [
                    image for image in self.images
                    if str(image.parent).casefold() == str(expected.parent).casefold()
                    and image.suffix.casefold() == expected.suffix.casefold()
                    and _single_typo(expected.stem.casefold(), image.stem.casefold())
                ]
            if len(candidates) == 1:
                actual = str(candidates[0])
            else:
                reason = "Several possible matches" if candidates else "No matching file"
                self.warnings.append(f"{reason} for {reference}. A fallback material is used.")
                self.repairs.append({"kind": "material_fallback", "source": base, "reference": reference, "replacement": None})
                return None, None
        raw = self.files[actual]
        if actual not in self.image_mimes:
            try:
                mime = _image_mime(raw)
            except UnreadableTexture:
                self.warnings.append(f"{actual} could not be decoded. The damaged map was omitted.")
                self.repairs.append({"kind": "material_fallback", "source": base, "reference": reference,
                                     "replacement": None, "reason": "unreadable_texture"})
                return None, None
            expected_mime = "image/png" if PurePosixPath(actual).suffix.lower() == ".png" else "image/jpeg"
            if mime != expected_mime:
                raise ValueError("A texture's contents do not match its filename extension.")
            self.image_mimes[actual] = mime
        if actual != requested:
            self.repairs.append({"kind": "relinked", "source": base, "reference": reference, "replacement": actual})
        self.output[actual] = raw
        return actual, self.image_mimes[actual]


def _text(raw: bytes) -> str:
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("A model or material document exceeds 12 MiB.")
    return raw.decode("utf-8-sig")


def _tokens(line: str) -> list[str]:
    if "\\" in line.partition("#")[0]:
        raise ValueError("Use forward slashes in Wavefront references.")
    return shlex.split(line, comments=True)


def _map_options(tokens: list[str]) -> tuple[list[str], str]:
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index].lower()
        index += 1
        if option in {"-o", "-s", "-t"}:
            start = index
            while index < len(tokens) and index - start < 3:
                try:
                    value = float(tokens[index])
                except ValueError:
                    break
                if not math.isfinite(value):
                    raise ValueError("Invalid numeric Wavefront texture option.")
                index += 1
            if index == start:
                raise ValueError("Missing value for a Wavefront texture option.")
        elif option in MTL_OPTION_LENGTHS:
            index += MTL_OPTION_LENGTHS[option]
        else:
            raise ValueError("Unsupported Wavefront texture map option.")
    if index >= len(tokens):
        raise ValueError("A Wavefront texture map does not name a file.")
    return tokens[:index], " ".join(tokens[index:])


def _prepare_mtl(library: str, bundle: _Bundle) -> None:
    lines = []
    for line in _text(bundle.files[library]).splitlines(keepends=True):
        content = line.partition("#")[0].strip()
        directive = content.split(maxsplit=1)[0].lower() if content else ""
        if directive.startswith("map_") or directive in MTL_MAPS:
            options, reference = _map_options(_tokens(line))
            actual, _ = bundle.texture(library, reference)
            if not actual:
                continue
            if actual != _reference(library, reference):
                relative = posixpath.relpath(actual, posixpath.dirname(library) or ".")
                if relative.startswith("-"):
                    relative = "./" + relative
                line = " ".join([*options, relative]) + "\n"
        elif directive:
            values = content.split()
            if (directive not in MTL_VALUES or "\\" in content
                    or (directive in {"ka", "kd", "ks", "ke", "tf"} and values[1:2] == ["spectral"])):
                raise ValueError("An unsupported Wavefront material directive was used.")
        lines.append(line)
    bundle.output[library] = "".join(lines).encode("utf-8")


def _prepare_obj(model: str, bundle: _Bundle) -> None:
    vertices = faces = highest_index = 0
    for line in _text(bundle.files[model]).splitlines():
        stripped = line.partition("#")[0].split()
        if not stripped:
            continue
        directive = stripped[0]
        if directive not in OBJ_DIRECTIVES or "\\" in line.partition("#")[0]:
            raise ValueError("Use a polygonal OBJ without external commands or line continuations.")
        if directive == "mtllib":
            names = _tokens(line)[1:]
            if not names:
                raise ValueError("An OBJ material library has no filename.")
            combined = " ".join(names)
            if _reference(model, combined) in bundle.files:
                names = [combined]
            for name in names:
                library = _reference(model, name)
                if PurePosixPath(library).suffix.lower() != ".mtl" or library not in bundle.files:
                    raise ValueError(f"Include the referenced OBJ material library {name} in the ZIP.")
                if library not in bundle.output:
                    _prepare_mtl(library, bundle)
        elif directive == "v":
            try:
                coordinates = [float(value) for value in stripped[1:4]]
            except ValueError as error:
                raise ValueError("The OBJ has an invalid vertex position.") from error
            if len(coordinates) != 3 or not all(math.isfinite(value) for value in coordinates):
                raise ValueError("The OBJ has an invalid vertex position.")
            vertices += 1
        elif directive == "f":
            if len(stripped) < 4:
                raise ValueError("The OBJ has a face with fewer than three vertices.")
            for corner in stripped[1:]:
                try:
                    index = int(corner.partition("/")[0])
                except ValueError as error:
                    raise ValueError("The OBJ face has an invalid vertex index.") from error
                if not index or index < -vertices:
                    raise ValueError("The OBJ face has an invalid vertex index.")
                highest_index = max(highest_index, index)
            faces += 1
    if highest_index > vertices:
        raise ValueError("An OBJ face references a vertex that is missing.")
    if not 3 <= vertices <= MAX_VERTICES or not faces:
        raise ValueError("Use an OBJ with polygon faces and at most two million vertices.")
    bundle.output[model] = bundle.files[model]


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"A glTF document contains the unsupported number {value}.")


def _embedded_uri(uri: str, media_types: set[str], limit: int) -> tuple[bytes, str]:
    header, _, encoded = uri.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if header != f"data:{mime};base64" or mime not in media_types or len(encoded) > 4 * ((limit + 2) // 3):
        raise ValueError("A glTF data URI has an unsupported type or size.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except binascii.Error as error:
        raise ValueError("A glTF data URI is not valid base64.") from error
    if len(data) > limit:
        raise ValueError("A glTF data URI exceeds its size limit.")
    return data, mime


def _rows(document: dict, field: str) -> list[dict]:
    rows = document.get(field, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"The glTF {field} field must be an array of objects.")
    return rows


def _index(rows: list, index: int):
    if type(index) is not int or not 0 <= index < len(rows):
        raise ValueError("A glTF resource index is out of range.")
    return rows[index]


def _unpack_glb(raw: bytes) -> tuple[bytes, bytes | None]:
    if len(raw) < 20 or struct.unpack_from("<4sII", raw) != (b"glTF", 2, len(raw)):
        raise ValueError("Use a valid glTF 2.0 binary file.")
    size, tag = struct.unpack_from("<I4s", raw, 12)
    offset = 20 + size
    if tag != b"JSON" or size % 4 or offset > len(raw):
        raise ValueError("The GLB JSON chunk is invalid.")
    if offset == len(raw):
        return raw[20:offset], None
    if len(raw) < offset + 8:
        raise ValueError("The GLB buffer chunk is incomplete.")
    size, tag = struct.unpack_from("<I4s", raw, offset)
    if tag != b"BIN\x00" or size % 4 or offset + 8 + size != len(raw):
        raise ValueError("The GLB buffer chunk is invalid.")
    return raw[20:offset], raw[offset + 8:]


def _verify_gltf_uris(document: dict, resources: list[dict]) -> None:
    allowed = {id(resource) for resource in resources}
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if "uri" in value and id(value) not in allowed:
                raise ValueError("Unsupported URI outside the glTF buffers or images.")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("A glTF number is outside the supported range.")


def _gltf_buffers(document: dict, model: str, bundle: _Bundle, binary: bytes | None, *, glb: bool) -> list[bytes]:
    buffers = []
    for index, entry in enumerate(_rows(document, "buffers")):
        uri = entry.get("uri")
        declared_size = entry.get("byteLength")
        if type(declared_size) is not int or not 0 < declared_size <= MAX_EXPANDED_BYTES:
            raise ValueError("A glTF buffer has an invalid byte length.")
        if uri is None and glb and binary is not None and index == 0:
            data = binary
            length_ok = 0 <= len(data) - declared_size <= 3
        elif isinstance(uri, str) and uri.startswith("data:"):
            data, _ = _embedded_uri(uri, {"application/octet-stream", "application/gltf-buffer"}, MAX_DOCUMENT_BYTES)
            length_ok = len(data) == declared_size
        elif isinstance(uri, str) and not glb:
            path = _reference(model, uri, uri=True)
            if PurePosixPath(path).suffix.lower() != ".bin" or path not in bundle.files:
                raise ValueError("Include the referenced glTF .bin geometry buffer in the ZIP.")
            data = bundle.files[path]
            length_ok = len(data) == declared_size
            bundle.output[path] = data
        else:
            raise ValueError("GLB geometry and textures must be embedded. Package glTF dependencies in a ZIP.")
        if not length_ok:
            raise ValueError("A glTF geometry buffer does not match its declared size.")
        buffers.append(data[:declared_size])
    return buffers


def _fallback_uri(*, normal: bool) -> str:
    result = io.BytesIO()
    Image.new("RGB", (1, 1), (128, 128, 255) if normal else (255, 255, 255)).save(result, format="PNG")
    return "data:image/png;base64," + base64.b64encode(result.getvalue()).decode("ascii")


def _gltf_view_bytes(view: dict, buffers: list[bytes]) -> tuple[bytes, int, int]:
    data = _index(buffers, view.get("buffer"))
    offset, size = view.get("byteOffset", 0), view.get("byteLength")
    if type(offset) is not int or type(size) is not int or not 0 <= offset < offset + size <= len(data):
        raise ValueError("A glTF buffer view is outside its buffer.")
    return data, offset, size


def _check_gltf_geometry(document: dict, views: list[dict], buffers: list[bytes]) -> None:
    accessors = _rows(document, "accessors")
    meshes = _rows(document, "meshes")
    if not meshes:
        raise ValueError("The glTF must contain a mesh.")
    for accessor in accessors:
        count = accessor.get("count")
        if type(count) is not int or not 0 < count <= MAX_VERTICES * 3:
            raise ValueError("The glTF contains an unsupported geometry accessor size.")
    for mesh in meshes:
        primitives = _rows(mesh, "primitives")
        if not primitives:
            raise ValueError("A glTF mesh does not contain any geometry primitives.")
        for primitive in primitives:
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise ValueError("A glTF mesh primitive does not contain vertex positions.")
            position = _index(accessors, attributes["POSITION"])
            if position.get("type") != "VEC3" or not 3 <= position["count"] <= MAX_VERTICES:
                raise ValueError("Use a glTF mesh with at least three positions and at most two million vertices.")
    for view in views:
        _gltf_view_bytes(view, buffers)


def _prepare_gltf(model: str, bundle: _Bundle, *, glb: bool) -> None:
    raw = bundle.files[model]
    json_document, binary = _unpack_glb(raw) if glb else (raw, None)
    document = json.loads(_text(json_document), parse_constant=_reject_nonfinite)
    if not isinstance(document, dict) or not isinstance(document.get("asset"), dict) or document["asset"].get("version") != "2.0":
        raise ValueError("Use a glTF 2.0 model.")
    images = _rows(document, "images")
    if len(images) > MAX_TEXTURES:
        raise ValueError(f"A model may reference at most {MAX_TEXTURES} texture maps.")
    _verify_gltf_uris(document, _rows(document, "buffers") + images)
    buffers = _gltf_buffers(document, model, bundle, binary, glb=glb)
    views = _rows(document, "bufferViews")
    _check_gltf_geometry(document, views, buffers)
    textures = _rows(document, "textures")
    normal_images = set()
    for material in _rows(document, "materials"):
        if "normalTexture" in material:
            normal = material["normalTexture"]
            if not isinstance(normal, dict):
                raise ValueError("A glTF normal texture reference is invalid.")
            source = _index(textures, normal.get("index")).get("source")
            if type(source) is int:
                normal_images.add(source)
    for index, image in enumerate(images):
        if "bufferView" in image:
            if "uri" in image:
                raise ValueError("A glTF image must use a buffer view or a URI.")
            view = _index(views, image["bufferView"])
            data, offset, size = _gltf_view_bytes(view, buffers)
            if size > MAX_IMAGE_BYTES:
                raise ValueError("A texture exceeds 8 MiB.")
            mime = _image_mime(data[offset:offset + size])
        else:
            uri = image.get("uri")
            if not isinstance(uri, str):
                raise ValueError("A glTF image has no local source.")
            if uri.startswith("data:"):
                data, expected_mime = _embedded_uri(uri, set(MIME_BY_FORMAT.values()), MAX_IMAGE_BYTES)
                mime = _image_mime(data)
                if mime != expected_mime:
                    raise ValueError("An embedded image does not match its media type.")
            elif not glb:
                actual, mime = bundle.texture(model, uri, uri=True)
                if actual:
                    relative = posixpath.relpath(actual, posixpath.dirname(model) or ".")
                    image["uri"] = quote(relative, safe="/")
                else:
                    mime = "image/png"
                    image["uri"] = _fallback_uri(normal=index in normal_images)
                image["mimeType"] = mime
            else:
                raise ValueError("GLB textures must be embedded. Package glTF dependencies in a ZIP.")
        if image.get("mimeType", mime) != mime:
            raise ValueError("A glTF image does not match its declared media type.")
    if glb or not images:
        bundle.output[model] = raw
    else:
        bundle.output[model] = (json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _read_bundle(archive: Path) -> dict[str, bytes]:
    if archive.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError("Upload a ZIP or GLB of at most 24 MiB.")
    if archive.suffix.lower() == ".glb" and _safe_part(archive.name):
        return {archive.name: archive.read_bytes()}
    if archive.suffix.lower() != ".zip":
        raise ValueError("Upload a ZIP containing one OBJ or glTF model, or a self-contained GLB.")
    try:
        with zipfile.ZipFile(archive) as source:
            return {
                name: source.read(member)
                for name, member in _archive_members(source).items()
                if not name.startswith("__MACOSX/") and not PurePosixPath(name).name.startswith("._")
                and PurePosixPath(name).suffix.lower() in MODEL_SUFFIXES | IMAGE_SUFFIXES | MSF_SUFFIXES | {".bin", ".mtl"}
            }
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, OSError, zlib.error) as error:
        raise ValueError("The upload is not a readable, unencrypted ZIP.") from error


def prepare_model(archive: Path, output_dir: Path) -> dict:
    """Write the selected model and local dependencies to a private output directory."""
    bundle = _Bundle(_read_bundle(Path(archive)))
    models = [name for name in bundle.files if PurePosixPath(name).suffix.lower() in MODEL_SUFFIXES]
    if len(models) != 1:
        raise ValueError("The upload must contain exactly one OBJ, glTF or GLB model.")
    model = models[0]
    model_format = PurePosixPath(model).suffix.lower()[1:]
    try:
        if model_format == "obj":
            _prepare_obj(model, bundle)
        else:
            _prepare_gltf(model, bundle, glb=model_format == "glb")
    except UnicodeDecodeError as error:
        raise ValueError("Model and material documents must contain valid UTF-8 text.") from error
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("The glTF document is damaged or incomplete. Export the model again.") from error
    msf_files = [
        name for name in bundle.files if PurePosixPath(name).stem.lower() in MSF_NAMES
        and PurePosixPath(name).suffix.lower() in MSF_SUFFIXES
    ]
    if len(msf_files) > 1:
        raise ValueError("Use one metadata.csv, metadata.xlsx, msf.csv or msf.xlsx per model bundle.")
    msf = msf_files[0] if msf_files else None
    output = dict(bundle.output)
    if msf:
        output[msf] = bundle.files[msf]
    for name, data in output.items():
        target = Path(output_dir) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    return {
        "model": model,
        "format": model_format,
        "files": sorted(bundle.output),
        "repairs": bundle.repairs,
        "warnings": bundle.warnings,
        "msf": msf,
    }
