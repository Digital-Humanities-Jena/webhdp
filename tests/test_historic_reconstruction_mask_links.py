"""Materialize only the author's known mask aliases, never arbitrary symlinks."""
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from external_code.historic_reconstruction_runtime import upstream as u


def mask_scene(tmp_path, provided=False):
    dataset = tmp_path / "dataset"
    images = dataset / "images"
    images.mkdir(parents=True)
    Image.new("RGB", (24, 16), "orange").save(images / "historic.jpg")
    source = dataset / ("masks" if provided else "workspace/masks_semantic") / "historic.png"
    source.parent.mkdir(parents=True)
    pixels = np.zeros((16, 24), dtype=np.uint8)
    pixels[3:12, 4:19] = 255
    Image.fromarray(pixels).save(source)
    destination = dataset / "workspace/masks/historic.png"
    destination.parent.mkdir(parents=True)
    return dataset, source, destination, pixels


@pytest.mark.parametrize("provided", [False, True])
@pytest.mark.parametrize("relative", [False, True])
def test_exact_upstream_mask_alias_preserves_real_png_bytes_and_pixels(tmp_path, provided, relative):
    import os
    dataset, source, destination, pixels = mask_scene(tmp_path, provided)
    original = source.read_bytes()
    target = os.path.relpath(source, destination.parent) if relative else source
    destination.symlink_to(target)
    assert u._materialize_upstream_masks(dataset, ["historic.jpg"]) == ["workspace/masks/historic.png"]
    assert not destination.is_symlink() and destination.read_bytes() == original == source.read_bytes()
    with Image.open(destination) as image:
        assert image.mode == "L" and image.size == (24, 16)
        assert np.array_equal(np.asarray(image), pixels)


def test_existing_regular_mask_needs_no_materialization(tmp_path):
    dataset, source, destination, _ = mask_scene(tmp_path)
    destination.write_bytes(source.read_bytes())
    assert u._materialize_upstream_masks(dataset, ["historic.jpg"]) == []
    assert destination.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("invalid", ["external", "wrong_image", "unexpected_path", "broken", "directory", "linked_target"])
def test_unexpected_mask_link_cannot_escape_or_mislabel_the_bundle(tmp_path, invalid):
    dataset, source, destination, _ = mask_scene(tmp_path)
    if invalid == "external":
        other = tmp_path / "historic.png"
        other.write_bytes(source.read_bytes())
        destination.symlink_to(other)
    elif invalid == "wrong_image":
        other = source.with_name("another.png")
        other.write_bytes(source.read_bytes())
        destination.symlink_to(other)
    elif invalid == "unexpected_path":
        (dataset / "workspace/unexpected.png").symlink_to(source)
    elif invalid == "broken":
        source.unlink()
        destination.symlink_to(source)
    elif invalid == "directory":
        destination.parent.rmdir()
        destination.parent.symlink_to(source.parent, target_is_directory=True)
    else:
        other = tmp_path / "historic.png"
        source.replace(other)
        source.symlink_to(other)
        destination.symlink_to(source)
    with pytest.raises(ValueError):
        u._materialize_upstream_masks(dataset, ["historic.jpg"])


def test_alias_for_an_image_outside_current_input_list_is_rejected(tmp_path):
    dataset, source, destination, _ = mask_scene(tmp_path)
    destination.symlink_to(source)
    with pytest.raises(ValueError):
        u._materialize_upstream_masks(dataset, ["different.jpg"])


@pytest.mark.parametrize("invalid", ["mode", "dimensions", "corrupt_png"])
def test_mask_alias_requires_valid_pixels_matching_original_image(tmp_path, invalid):
    dataset, source, destination, _ = mask_scene(tmp_path)
    if invalid == "mode":
        Image.new("RGB", (24, 16), "white").save(source)
    elif invalid == "dimensions":
        Image.new("L", (12, 8), 255).save(source)
    else:
        source.write_bytes(b"not a PNG")
    destination.symlink_to(source)
    with pytest.raises((ValueError, OSError)):
        u._materialize_upstream_masks(dataset, ["historic.jpg"])
