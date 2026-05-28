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

    assert manifest["@context"] == "http://iiif.io/api/presentation/3/context.json"
    assert manifest["type"] == "Manifest"
    assert manifest["label"]["en"] == ["Artifact"]
    assert manifest["summary"]["en"] == ["Preview of the 3D artifact."]
    assert manifest["thumbnail"][0]["type"] == "Image"

    canvas = manifest["items"][0]
    assert canvas["type"] == "Canvas"
    page = canvas["items"][0]
    assert page["type"] == "AnnotationPage"
    annotation = page["items"][0]
    assert annotation["type"] == "Annotation"
    assert annotation["body"][0]["type"] == "Model"
    assert annotation["body"][0]["format"] == "model/gltf-binary"
    assert annotation["target"] == [canvas["id"]]

    validation = service.validate_iiif_manifest(repaired)
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_minimum_viable_iiif_uses_point_selector_for_canvas_coordinates():
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

    assert annotation["target"][0]["type"] == "SpecificResource"
    assert annotation["target"][0]["source"]["type"] == "Canvas"
    assert annotation["target"][0]["selector"][0]["type"] == "PointSelector"
    assert annotation["target"][0]["selector"][0]["x"] == 1.25
    assert annotation["target"][0]["selector"][0]["y"] == 2.5
    assert annotation["target"][0]["selector"][0]["z"] == 3.75


def test_iiif_validation_rejects_missing_canvas_model():
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
                "items": [],
            }
        ],
    }

    validation = service.validate_iiif_manifest(json.dumps(manifest))
    assert validation["valid"] is False
    assert any("AnnotationPage" in error for error in validation["errors"])


def test_iiif_validation_rejects_legacy_v4_scene_manifest():
    service = IiifService()
    manifest = {
        "@context": "http://iiif.io/api/presentation/4/context.json",
        "id": "https://example.org/manifest.json",
        "type": "Manifest",
        "label": {"en": ["Artifact"]},
        "items": [
            {
                "id": "https://example.org/scene/1",
                "type": "Scene",
                "items": [],
            }
        ],
    }

    validation = service.validate_iiif_manifest(json.dumps(manifest))
    assert validation["valid"] is False
    assert any("Presentation v3 context" in error for error in validation["errors"])
    assert any("Canvas" in error for error in validation["errors"])
