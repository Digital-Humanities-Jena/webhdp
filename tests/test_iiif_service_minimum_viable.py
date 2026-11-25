import json

from services.iiif_service import IiifService


def _sample_zenodo_record():
    return {
        "id": "443547",
        "links": {"html": "https://sandbox.zenodo.org/records/443547"},
        "files": [
            {
                "key": "artifact.glb",
                "filename": "artifact.glb",
                "size": 1024,
            },
            {
                "key": "artifact_r000.png",
                "filename": "artifact_r000.png",
                "size": 256,
            },
        ],
    }


def test_minimum_viable_iiif_repairs_sparse_manifest():
    service = IiifService()
    metadata = {
        "title": "Artifact",
        "description": "Preview of the 3D artifact.",
    }

    repaired = service._ensure_minimum_viable_iiif("{}", metadata, _sample_zenodo_record())
    manifest = json.loads(repaired)

    assert manifest["@context"] == "http://iiif.io/api/presentation/4/context.json"
    assert manifest["id"] == "https://sandbox.zenodo.org/api/records/443547/files/iiif.json/content"
    assert manifest["type"] == "Manifest"
    assert manifest["label"]["en"] == ["Artifact"]
    assert manifest["summary"]["en"] == ["Preview of the 3D artifact."]
    assert manifest["thumbnail"][0]["type"] == "Image"

    scene = manifest["items"][0]
    assert scene["type"] == "Scene"
    assert '#' not in scene['id']
    assert 'width' not in scene and 'height' not in scene
    page = scene["items"][0]
    assert page["type"] == "AnnotationPage"
    annotation = page["items"][0]
    assert annotation["type"] == "Annotation"
    assert annotation["body"]["type"] == "Model"
    assert annotation["body"]["format"] == "model/gltf-binary"
    assert annotation["target"] == {"id": scene["id"], "type": "Scene"}

    validation = service.validate_iiif_manifest(repaired)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_minimum_viable_iiif_uses_point_selector_for_scene_coordinates():
    service = IiifService()
    metadata = {
        "title": "Artifact",
        "iiif_point_x": "1.25",
        "iiif_point_y": "2.5",
        "iiif_point_z": "3.75",
    }

    repaired = service._ensure_minimum_viable_iiif("{}", metadata, _sample_zenodo_record())
    manifest = json.loads(repaired)
    annotation = manifest["items"][0]["items"][0]["items"][0]

    assert annotation["target"]["type"] == "SpecificResource"
    assert annotation["target"]["source"]["type"] == "Scene"
    assert annotation["target"]["selector"] == [{"type": "PointSelector", "x": 1.25, "y": 2.5, "z": 3.75}]


def test_iiif_validation_rejects_canvas_without_dimensions():
    service = IiifService()
    manifest = {
        "@context": "http://iiif.io/api/presentation/4/context.json",
        "id": "https://example.org/manifest.json",
        "type": "Manifest",
        "label": {"en": ["Artifact"]},
        "items": [
            {
                "id": "https://example.org/canvas/1",
                "type": "Canvas",
            }
        ],
    }

    validation = service.validate_iiif_manifest(json.dumps(manifest))
    assert validation["valid"] is False
    assert any("width" in error for error in validation["errors"])


def test_iiif_validation_requires_v4_for_new_exports():
    service = IiifService()
    manifest = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": "https://example.org/manifest.json",
        "type": "Manifest",
        "label": {"en": ["Artifact"]},
        "items": [
            {
                "id": "https://example.org/canvas/1",
                "type": "Canvas",
                "width": 800,
                "height": 600,
            }
        ],
    }

    validation = service.validate_iiif_manifest(json.dumps(manifest))
    assert validation["valid"] is False
    assert any("context" in error for error in validation["errors"])
