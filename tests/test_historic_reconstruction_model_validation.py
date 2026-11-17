"""Use real COLMAP binary models to check the research artifact boundary."""
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image
import pytest

from external_code.historic_reconstruction_runtime import upstream as u


@pytest.fixture
def model_scene(tmp_path):
    pc = pytest.importorskip("pycolmap")
    reconstruction = pc.synthesize_dataset(pc.SyntheticDatasetOptions())
    images = tmp_path / "images"
    images.mkdir()
    model = tmp_path / "model"
    model.mkdir()
    for image in reconstruction.images.values():
        camera = reconstruction.cameras[image.camera_id]
        Image.new("RGB", (camera.width, camera.height), "orange").save(images / image.name)
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(Path(pc.__file__).resolve().parent.parent)}
    config = {"_python": Path(sys.executable), "timeout_seconds": 60}
    return reconstruction, images, model, config, env


def validate(scene, tmp_path):
    reconstruction, images, model, config, env = scene
    reconstruction.write(str(model))
    return u._model_report([model], images, config, env, tmp_path)


def test_valid_model_and_cubemap_references_are_accepted(model_scene, tmp_path):
    reconstruction, images, _, _, _ = model_scene
    image = next(iter(reconstruction.images.values()))
    cubemaps = tmp_path / "cubemaps"
    cubemaps.mkdir()
    (images / image.name).replace(cubemaps / image.name)
    report = validate(model_scene, tmp_path)
    assert report[0]["registered_images"] == reconstruction.num_reg_images()
    assert report[0]["points3D"] == reconstruction.num_points3D()
    assert report[0]["registered_input_images"] == reconstruction.num_reg_images() - 1
    assert report[0]["registered_panorama_images"] == 1
    u._require_historic_registration(report)


def test_panorama_only_model_cannot_claim_historic_geolocation(model_scene, tmp_path):
    reconstruction, images, _, _, _ = model_scene
    cubemaps = tmp_path / "cubemaps"
    cubemaps.mkdir()
    for image in reconstruction.images.values():
        (images / image.name).replace(cubemaps / image.name)
    report = validate(model_scene, tmp_path)
    assert report[0]["registered_images"] == reconstruction.num_reg_images()
    assert report[0]["registered_input_images"] == 0
    assert report[0]["registered_panorama_images"] == reconstruction.num_reg_images()
    with pytest.raises(ValueError, match="no registered historic input image"):
        u._require_historic_registration(report)
    # A valid single historical registration is sufficient against panorama support;
    # reference-only models may coexist with the successful scene.
    image = next(iter(reconstruction.images.values()))
    (cubemaps / image.name).replace(images / image.name)
    mixed = validate(model_scene, tmp_path)
    assert mixed[0]["registered_input_images"] == 1
    u._require_historic_registration(report + mixed)


@pytest.mark.parametrize("invalid", ["point", "camera", "pose", "keypoint", "image_size"])
def test_invalid_model_geometry_is_rejected(model_scene, tmp_path, invalid):
    reconstruction, images, _, _, _ = model_scene
    image = next(iter(reconstruction.images.values()))
    expected = {
        "point": "Non-finite COLMAP 3D point",
        "camera": "Invalid COLMAP camera",
        "pose": "Non-finite COLMAP image pose",
        "keypoint": "Non-finite COLMAP image keypoint",
        "image_size": "camera dimensions disagree with image",
    }[invalid]
    if invalid == "point":
        next(iter(reconstruction.points3D.values())).xyz = np.array([np.nan, 0, 0])
    elif invalid == "camera":
        camera = reconstruction.cameras[image.camera_id]
        params = camera.params.copy()
        params[0] = np.inf
        camera.params = params
    elif invalid == "pose":
        frame = reconstruction.frames[image.frame_id]
        pose = frame.rig_from_world
        pose.translation = np.array([np.nan, 0, 0])
        frame.rig_from_world = pose
    elif invalid == "keypoint":
        image.points2D[0].xy = np.array([np.nan, 0])
    else:
        Image.new("RGB", (16, 16), "blue").save(images / image.name)
    with pytest.raises(ValueError, match="Historic research stage failed"):
        validate(model_scene, tmp_path)
    assert expected in (tmp_path / "validation.log").read_text()
