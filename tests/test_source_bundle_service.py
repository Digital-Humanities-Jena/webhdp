import hashlib
import json
from pathlib import Path
from urllib.parse import unquote
import zipfile

from services.source_bundle_service import create_source_bundle


def test_source_bundle_preserves_parent_paths_and_duplicate_dependency_names(tmp_path):
    source = tmp_path / "input" / "模型" / "model.gltf"
    source.parent.mkdir(parents=True)
    references = [
        "../shared/buffer.bin",
        "textures/first/image.jpg",
        "textures/second/image.jpg",
    ]
    content = json.dumps(
        {
            "buffers": [{"uri": references[0]}],
            "images": [{"uri": name} for name in references[1:]],
        }
    )
    source.write_text(content)
    children = []
    for index, reference in enumerate(references):
        path = (source.parent / reference).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes([index + 1]))
        children.append({"absolute_path": str(path)})
    tree = [{"absolute_path": str(source), "children": children}]
    bundle = create_source_bundle(str(source), tree, tmp_path / "output")
    with zipfile.ZipFile(bundle) as archive:
        assert len(archive.namelist()) == 4
        assert not any(
            name.startswith("/") or ".." in Path(name).parts
            for name in archive.namelist()
        )
        archive.extractall(tmp_path / "download")
    downloaded = tmp_path / "download" / "模型" / "model.gltf"
    assert downloaded.read_text() == content
    for index, reference in enumerate(references):
        assert (downloaded.parent / unquote(reference)).read_bytes() == bytes(
            [index + 1]
        )
    checksum = hashlib.sha256(Path(bundle).read_bytes()).hexdigest()
    assert create_source_bundle(str(source), tree, tmp_path / "output") == bundle
    assert hashlib.sha256(Path(bundle).read_bytes()).hexdigest() == checksum
    assert source.read_text() == content


def test_flat_model_dependencies_do_not_need_an_additional_archive(tmp_path):
    source = tmp_path / "model.gltf"
    source.write_text("{}")
    dependency = tmp_path / "buffer.bin"
    dependency.write_bytes(b"buffer")
    tree = [
        {"absolute_path": str(source), "children": [{"absolute_path": str(dependency)}]}
    ]
    assert create_source_bundle(str(source), tree, tmp_path / "output") is None


def test_source_bundle_includes_original_archived_textures(tmp_path):
    source = tmp_path / "model.obj"
    source.write_text("mtllib material.mtl\n")
    texture = tmp_path / "textures" / "image.jpg"
    texture.parent.mkdir()
    texture.write_bytes(b"texture")
    archive = tmp_path / "output" / "textures.zip"
    archive.parent.mkdir()
    archive.write_bytes(b"existing archive")
    tree = [
        {
            "absolute_path": str(source),
            "children": [
                {
                    "absolute_path": str(archive),
                    "children": [{"absolute_path": str(texture)}],
                }
            ],
        }
    ]
    bundle = create_source_bundle(str(source), tree, tmp_path / "output")
    with zipfile.ZipFile(bundle) as uploaded:
        assert set(uploaded.namelist()) == {"model.obj", "textures/image.jpg"}
