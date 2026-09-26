"""Run in the component test environment, which includes geospatial libraries."""
import json
import struct
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import runner
from geometry import fit_alignment, placement, write_placed_glb


def model(path):
    data = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 0, 1)
    document = {'asset': {'version': '2.0', 'extras': ['preserve']},
        'scenes': [{'nodes': [0]}], 'scene': 0, 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'buffers': [{'byteLength': len(data)}], 'bufferViews': [{'buffer': 0, 'byteLength': len(data)}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3}]}
    payload = json.dumps(document).encode(); payload += b' '*(-len(payload)%4)
    path.write_bytes(struct.pack('<4sIII4s', b'glTF', 2, 28+len(payload)+len(data), len(payload), b'JSON')+payload+struct.pack('<I4s', len(data), b'BIN\x00')+data)
    return path


def reference(path, crs='EPSG:32632', dtype='uint8', transform=None):
    pixels = np.random.default_rng(43).integers(0, 255, (3, 256, 384)).astype(dtype)
    with rasterio.open(path, 'w', driver='GTiff', width=384, height=256, count=3,
        dtype=dtype, crs=crs, transform=transform or from_origin(600000, 5600000, 0.5, 0.5)) as target:
        target.write(pixels)
    return path


def test_ransac_keeps_inliers_not_rejected_matches():
    rng = np.random.default_rng(42)
    source = rng.uniform(0, 200, (200, 2))
    target = source*0.8 + [50, 70] + rng.normal(0, 0.1, source.shape)
    target[:60] = rng.uniform(0, 300, (60, 2))
    matrix, quality = fit_alignment(source, target, (201, 201), (400, 400))
    assert quality['inliers'] >= 135
    assert quality['rmse_reference_pixels'] < 0.3
    np.testing.assert_allclose(matrix[:2], [[0.8, 0, 50], [0, 0.8, 70]], atol=0.1)


@pytest.mark.parametrize('case', ['few', 'unrelated', 'cluster', 'mirror', 'outside', 'nan', 'duplicates'])
def test_rejects_unreliable_matches(case):
    source = np.random.default_rng(2).uniform(0, 200, (200, 2))
    target = source + 50
    if case == 'few': source, target = source[:10], target[:10]
    if case == 'unrelated': target = np.random.default_rng(9).uniform(0, 300, (200, 2))
    if case == 'cluster': source *= 0.05; target = source+50
    if case == 'mirror': target[:, 0] = 300-source[:, 0]
    if case == 'outside': target = source+500
    if case == 'nan': source[0, 0] = np.nan
    if case == 'duplicates': source = np.repeat(source[:3], 70, axis=0); target = source+50
    with pytest.raises(ValueError): fit_alignment(source, target, (200, 200), (400, 400))


def test_axes_pixel_centres_scale_and_large_projected_coordinates():
    pixel_map = np.array([[2, 0, 600000], [0, -2, 5600000], [0, 0, 1]])
    camera = [[10, 0, 0, 99.5], [0, 0, 10, 99.5], [0, 0, 0, 1]]
    matrix, anchor, scale = placement(pixel_map, np.eye(3), camera)
    np.testing.assert_allclose(anchor, [600200, 5599800])
    np.testing.assert_allclose(matrix, np.diag([20, 20, 20, 1]))
    assert scale == pytest.approx(20)


def test_rejects_distortion():
    with pytest.raises(ValueError, match='distort'):
        placement([[2, 0, 0], [0, -8, 0], [0, 0, 1]], np.eye(3),
                  [[1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])


def test_distant_model_origin_is_centered_without_moving_the_site():
    camera = [[10, 0, 0, -99900.5], [0, 0, 10.0001, 200100.5], [0, 0, 0, 1]]
    center = np.array([10000, -20000])
    mapping = np.array([[.1, 0, 600000], [0, -.1, 5600000], [0, 0, 1]])
    matrix, anchor, scale = placement(mapping, np.eye(3), camera, center)
    located = matrix @ [center[0], 0, center[1], 1]
    np.testing.assert_allclose(located[:3], 0, atol=1e-8)
    expected = mapping @ np.array([[1, 0, .5], [0, 1, .5], [0, 0, 1]]) @ np.array(camera) @ [center[0], 0, center[1], 1]
    np.testing.assert_allclose(anchor, expected[:2])
    np.testing.assert_allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3)*scale**2, atol=1e-10)


@pytest.mark.parametrize('turns', range(4))
def test_rotation_uses_original_non_square_dimensions(turns):
    image = np.arange(15).reshape(3, 5)
    rotated = np.rot90(image, turns)
    yy, xx = np.indices(rotated.shape)
    original = runner.inverse_rotation(np.column_stack([xx.ravel(), yy.ravel()]), turns, 5, 3).astype(int)
    np.testing.assert_array_equal(image[original[:, 1], original[:, 0]], rotated.ravel())


def test_glb_preserves_source_and_binary_data(tmp_path):
    source = model(tmp_path/'model.glb'); original = source.read_bytes()
    output = tmp_path/'aligned.glb'
    write_placed_glb(source, output, np.diag([2, 2, 2, 1]), {'crs': 'EPSG:32632'})
    runner.glb_contract().inspect_glb(output)
    assert source.read_bytes() == original
    size = struct.unpack_from('<I', output.read_bytes(), 12)[0]
    doc = json.loads(output.read_bytes()[20:20+size])
    assert doc['asset']['extras']['source_extras'] == ['preserve']
    assert doc['nodes'][0] == {'mesh': 0}
    assert doc['nodes'][1]['children'] == [0]
    old_size = struct.unpack_from('<I', original, 12)[0]
    assert output.read_bytes()[20+size:] == original[20+old_size:]


@pytest.mark.parametrize('crs,dtype', [(None, 'uint8'), ('EPSG:4326', 'uint8'), ('EPSG:2263', 'uint8'), ('EPSG:32632', 'uint16')])
def test_invalid_reference_fails_before_render(tmp_path, crs, dtype):
    source = model(tmp_path/'site.glb'); ortho = reference(tmp_path/'site.tif', crs=crs, dtype=dtype)
    with patch.object(runner.subprocess, 'run') as process, pytest.raises(ValueError):
        runner.execute({'inputs': {'input_file': str(source), 'reference_files': [str(ortho)]}})
    process.assert_not_called()


def test_missing_ambiguous_reference_and_invalid_model(tmp_path):
    source = model(tmp_path/'site.glb'); a = reference(tmp_path/'a.tif'); b = reference(tmp_path/'b.tif')
    for references in ([], [str(a), str(b)], None):
        with pytest.raises(ValueError): runner.resolve_inputs({'inputs': {'input_file': str(source), 'reference_files': references}})
    source.write_bytes(b'invalid')
    with pytest.raises(ValueError): runner.resolve_inputs({'inputs': {'input_file': str(source), 'reference_files': [str(a)]}})


def test_retries_have_isolated_outputs_and_failed_runs_leave_no_artifacts(tmp_path, monkeypatch):
    source = model(tmp_path/'site.glb'); ortho = reference(tmp_path/'site.tif')
    monkeypatch.setenv('WEBHDP_OUTPUT_DIR', str(tmp_path/'outputs'))
    with patch.object(runner.subprocess, 'run', side_effect=RuntimeError('render failed')):
        for _ in range(2):
            with pytest.raises(RuntimeError): runner.execute({'inputs': {'input_file': str(source), 'reference_files': [str(ortho)]}})
    assert list((tmp_path/'outputs').iterdir()) == []


def test_input_escape_is_rejected(tmp_path, monkeypatch):
    source = model(tmp_path/'source.glb')
    root = tmp_path/'inputs'; root.mkdir(); (root/'link.glb').symlink_to(source)
    monkeypatch.setenv('WEBHDP_INPUT_DIR', str(root))
    with pytest.raises(ValueError, match='staged'): runner.input_path('link.glb')


def test_non_square_raster_resizing_preserves_square_ground_pixels(tmp_path):
    path = tmp_path/'wide.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=1703, height=999, count=1,
        dtype='uint8', crs='EPSG:32632', transform=from_origin(600000, 5600000, 0.1, 0.1)) as target:
        target.write(np.full((1, 999, 1703), 123, dtype='uint8'))
    image, mask, transform, crs = runner.read_reference(path)
    assert image.shape == (601, 1024, 3)
    assert abs(transform[0, 0]) == pytest.approx(abs(transform[1, 1]))
    assert mask[:-1].all()
    assert crs.to_epsg() == 32632


def test_disguised_vrt_cannot_read_external_files(tmp_path):
    path = tmp_path/'unsafe.tif'
    path.write_text('<VRTDataset rasterXSize="256" rasterYSize="256"><VRTRasterBand dataType="Byte" band="1"/></VRTDataset>')
    with pytest.raises(rasterio.errors.RasterioIOError): runner.read_reference(path)


def test_rgba_reference_keeps_transparent_pixels_out_of_matching(tmp_path):
    path = tmp_path/'alpha.tif'
    pixels = np.full((4, 256, 256), 180, dtype='uint8')
    pixels[3] = 255
    pixels[3, 80:160, 80:160] = 0
    with rasterio.open(path, 'w', driver='GTiff', width=256, height=256, count=4,
        dtype='uint8', crs='EPSG:32632', transform=from_origin(600000, 5600000, .1, .1)) as target:
        target.write(pixels)
        target.colorinterp = (rasterio.enums.ColorInterp.red, rasterio.enums.ColorInterp.green,
                              rasterio.enums.ColorInterp.blue, rasterio.enums.ColorInterp.alpha)
    image, mask, _, _ = runner.read_reference(path)
    assert not mask[80:160, 80:160].any()
    assert not image[80:160, 80:160].any()
    assert mask[:80].all()
