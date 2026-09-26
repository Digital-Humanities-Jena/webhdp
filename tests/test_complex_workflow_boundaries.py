import io
import json
import multiprocessing
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from exceptions import SecurityError, ValidationError
from security import safe_extract_zip
from services.hdpc_scan_service import (
    _find_gltf_external_files,
    _find_texture_files_for_mtl,
    _find_mtl_files_for_obj,
    create_and_scan_hdpc_project,
)
from services.hdpc_local_service import inspect_hdpc_project
from services.msf_service import MSFService
from services.pipeline_execution_lock import (
    session_pipeline_lock,
    PipelineAlreadyRunning,
)


def test_content_url_preserves_unicode_and_reserved_filename_characters():
    from urllib.parse import unquote, urlsplit
    from services.edm_service import EdmService

    filename = "模型 #1? 50%.glb"
    url = EdmService().generate_content_url("123", filename, is_sandbox=True)
    parts = urlsplit(url)
    assert not parts.query and not parts.fragment
    assert unquote(parts.path.split("/")[-2]) == filename


@pytest.mark.parametrize(
    "names",
    [
        ["model.obj", "model.obj"],
        ["Model.obj", "model.obj"],
        ["folder/../escape.obj"],
        ["C:/absolute.obj"],
        ["folder", "folder/model.obj"],
        ["."],
    ],
)
def test_zip_rejects_ambiguous_or_unsafe_paths_before_extraction(tmp_path, names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, b"content")
    buffer.seek(0)
    with (
        zipfile.ZipFile(buffer) as archive,
        pytest.raises((SecurityError, ValidationError)),
    ):
        safe_extract_zip(archive, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("attribute,value", [("flag_bits", 1), ("compress_type", 99)])
def test_zip_rejects_unsupported_encoding_before_writing(tmp_path, attribute, value):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("model.obj", b"mesh")
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive:
        setattr(archive.infolist()[0], attribute, value)
        with pytest.raises(ValidationError):
            safe_extract_zip(archive, tmp_path, validate_only=True)
    assert not list(tmp_path.iterdir())


def test_zip_windows_separators_extract_as_directories(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("nested\\模型.obj", b"mesh")
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive:
        safe_extract_zip(archive, tmp_path)
    assert (tmp_path / "nested" / "模型.obj").read_bytes() == b"mesh"


@pytest.mark.parametrize(
    "reference",
    [
        "textures/albedo image.png",
        '"textures/albedo image.png"',
        '-s 1 1 1 -o 0 0 "textures/albedo image.png"',
        "-clamp on -bm 0.5 textures/albedo image.png",
    ],
)
def test_mtl_paths_with_spaces_and_options(tmp_path, reference):
    texture = tmp_path / "textures" / "albedo image.png"
    texture.parent.mkdir()
    texture.write_bytes(b"fixture")
    mtl = tmp_path / "material.mtl"
    mtl.write_text("map_Kd " + reference + "\n")
    assert _find_texture_files_for_mtl(mtl, tmp_path) == ([texture], [])


def test_gltf_decodes_relative_unicode_uri_and_ignores_embedded_data(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    buffer = shared / "缓冲 file.bin"
    buffer.write_bytes(b"buffer")
    model = tmp_path / "models" / "model.gltf"
    model.parent.mkdir()
    model.write_text(
        json.dumps(
            {
                "buffers": [
                    {"uri": "../shared/%E7%BC%93%E5%86%B2%20file.bin"},
                    {"uri": "data:application/octet-stream;base64,YQ=="},
                ]
            }
        )
    )
    assert _find_gltf_external_files(model, tmp_path) == ([buffer], [])
    model.write_text(json.dumps({"buffers": [{"uri": "../../outside.bin"}]}))
    with pytest.raises(SecurityError):
        _find_gltf_external_files(model, tmp_path)


def test_obj_can_reference_multiple_material_libraries(tmp_path):
    for name in ["first.mtl", "second.mtl"]:
        (tmp_path / name).touch()
    obj = tmp_path / "model.obj"
    obj.write_text("mtllib first.mtl second.mtl\n")
    assert _find_mtl_files_for_obj(obj, tmp_path) == [
        tmp_path / "first.mtl",
        tmp_path / "second.mtl",
    ]


def test_duplicate_dependency_basenames_do_not_make_primary_matching_ambiguous():
    result = MSFService().validate_msf_against_directory(
        pd.DataFrame({"filename": ["first.gltf", "second.gltf"]}),
        ["first.gltf", "second.gltf", "buffer.bin", "buffer.bin"],
        filename_column="filename",
    )
    assert result.is_valid and not result.duplicate_directory_files
    result = MSFService().validate_msf_against_directory(
        pd.DataFrame({"filename": ["first.gltf"]}),
        ["first.gltf", "first.gltf"],
        filename_column="filename",
    )
    assert not result.is_valid and result.duplicate_directory_files == ["first.gltf"]


def test_shared_buffer_is_retained_in_each_model_tree(tmp_path):
    source = tmp_path / "uploads"
    source.mkdir()
    (source / "buffer.bin").write_bytes(b"buffer")
    for name in ["first.gltf", "second.gltf"]:
        (source / name).write_text(json.dumps({"buffers": [{"uri": "buffer.bin"}]}))
    hdpc = tmp_path / "project.hdpc"
    create_and_scan_hdpc_project(
        hdpc_path=str(hdpc),
        data_in_path=str(source),
        data_out_path=str(tmp_path / "out"),
        project_name="Shared buffers",
        batch_entity="hybrid",
        scan_options={
            "extensions": [".gltf", ".bin"],
            "preferred_primary_files": ["first.gltf", "second.gltf"],
            "obj_options": {"add_textures": True},
        },
    )
    tree = inspect_hdpc_project(str(hdpc))["file_tree"]
    models = [node for node in tree if node["filename"].endswith(".gltf")]
    assert len(models) == 2
    assert all(
        any(child["filename"] == "buffer.bin" for child in model["children"])
        for model in models
    )


def _attempt_lock(path, connection):
    try:
        with session_pipeline_lock(path):
            connection.send("acquired")
    except PipelineAlreadyRunning:
        connection.send("conflict")
    finally:
        connection.close()


def test_session_lock_prevents_cross_process_races_and_releases_on_failure(tmp_path):
    path = str(tmp_path / "project.hdpc")
    ctx = multiprocessing.get_context("spawn")
    with pytest.raises(RuntimeError):
        with session_pipeline_lock(path):
            parent, child = ctx.Pipe()
            process = ctx.Process(target=_attempt_lock, args=(path, child))
            process.start()
            assert parent.poll(10) and parent.recv() == "conflict"
            process.join(10)
            assert process.exitcode == 0
            with session_pipeline_lock(str(tmp_path / "other.hdpc")):
                pass
            raise RuntimeError("simulated pipeline failure")
    with session_pipeline_lock(path):
        pass


def test_zip_expansion_limit_is_checked_before_writing(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.txt", b"x" * 10000)
    buffer.seek(0)
    with (
        zipfile.ZipFile(buffer) as archive,
        pytest.raises(ValidationError, match="expanded size"),
    ):
        safe_extract_zip(archive, tmp_path, max_expanded_bytes=100)
    assert not list(tmp_path.iterdir())


def test_multiple_material_libraries_preserve_all_archived_textures(tmp_path):
    source = tmp_path / "uploads"
    source.mkdir()
    textures = source / "textures"
    textures.mkdir()
    (source / "model.obj").write_text("mtllib first.mtl second.mtl\nv 0 0 0\n")
    for stem in ["first", "second"]:
        (source / (stem + ".mtl")).write_text("map_Kd textures/" + stem + ".png\n")
        (textures / (stem + ".png")).write_bytes(stem.encode())
    output = tmp_path / "out"
    create_and_scan_hdpc_project(
        hdpc_path=str(tmp_path / "project.hdpc"),
        data_in_path=str(source),
        data_out_path=str(output),
        project_name="Multiple materials",
        batch_entity="root",
        scan_options={
            "extensions": [".obj"],
            "primarysourceext": ".obj",
            "obj_options": {
                "add_mtl": True,
                "add_textures": True,
                "archive_subdirectories": True,
            },
        },
    )
    archives = list(output.rglob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert set(archive.namelist()) == {"textures/first.png", "textures/second.png"}
