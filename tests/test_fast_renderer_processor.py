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
