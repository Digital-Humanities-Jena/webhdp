from external_code.fast_renderer.processor import select_cycles_backend


def test_select_cycles_backend_skips_optix_without_matching_devices():
    selection = select_cycles_backend(
        {
            "OPTIX": [{"name": "CPU", "type": "CPU"}],
            "CUDA": [{"name": "NVIDIA A100", "type": "CUDA"}],
        }
    )

    assert selection["backend"] == "CUDA"
    assert len(selection["matched_devices"]) == 1
    assert selection["matched_devices"][0]["type"] == "CUDA"


def test_select_cycles_backend_returns_none_when_only_cpu_is_available():
    selection = select_cycles_backend(
        {
            "OPTIX": [{"name": "CPU", "type": "CPU"}],
            "CUDA": [{"name": "CPU", "type": "CPU"}],
        }
    )

    assert selection["backend"] is None
    assert selection["matched_devices"] == []


def test_texture_validation_rejects_unreadable_images_and_accepts_decoded_images():
    from types import SimpleNamespace
    import pytest
    from external_code.fast_renderer.processor import OPTIMIZED_BATCH_TEMPLATE
    source = OPTIMIZED_BATCH_TEMPLATE.split('def validate_texture_images():', 1)[1].split('def import_model', 1)[0]
    image = SimpleNamespace(source='FILE', has_data=False, size=(0, 0), name='broken.jpg', reload=lambda: None)
    namespace = {'bpy': SimpleNamespace(data=SimpleNamespace(images=[image]))}
    exec('def validate_texture_images():' + source, namespace)
    with pytest.raises(RuntimeError, match='Texture could not be decoded: broken.jpg'):
        namespace['validate_texture_images']()
    # Blender can load image pixels lazily after reload().
    image.has_data = False
    image.size = (32, 32)
    image.pixels = [0.0] * (32 * 32 * 4)
    namespace['validate_texture_images']()


def test_obj_material_normalization_preserves_source_and_relative_dependencies(tmp_path):
    from pathlib import Path
    from external_code.fast_renderer.processor import prepare_obj_material_libraries
    for name in ["first.mtl", "second library.mtl"]:
        (tmp_path / name).touch()
    source = tmp_path / "model.obj"
    original = 'mtllib first.mtl "second library.mtl"\nv 0 0 0\n'
    source.write_text(original)
    prepared = Path(prepare_obj_material_libraries(str(source)))
    try:
        assert prepared != source and prepared.parent == source.parent
        assert prepared.read_text() == "mtllib first.mtl\nmtllib second library.mtl\nv 0 0 0\n"
        assert source.read_text() == original
    finally:
        prepared.unlink()


def test_obj_material_normalization_keeps_existing_space_named_library(tmp_path):
    from external_code.fast_renderer.processor import prepare_obj_material_libraries
    (tmp_path / "one library.mtl").touch()
    source = tmp_path / "model.obj"
    source.write_text("mtllib one library.mtl\nv 0 0 0\n")
    assert prepare_obj_material_libraries(str(source)) == str(source)


def test_obj_material_normalization_rejects_missing_library(tmp_path):
    import pytest
    from external_code.fast_renderer.processor import prepare_obj_material_libraries
    source = tmp_path / "model.obj"
    source.write_text("mtllib missing.mtl\nv 0 0 0\n")
    with pytest.raises(RuntimeError, match="Material library not found"):
        prepare_obj_material_libraries(str(source))
    assert not list(tmp_path.glob(".materials-*.obj"))
