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
