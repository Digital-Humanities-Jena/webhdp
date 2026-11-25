import json

import pytest
from flask import Flask

from services.iiif_service import IiifService
from services.iiif_validation import (
    CONTEXT,
    PROFILE_VERSION,
    V3_CONTEXT,
    V3_PROFILE_VERSION,
    validate_legacy_v3_manifest,
    validate_manifest,
)

BASE = "https://example.org/iiif"


def manifest_for(kind, content_type, mime_type, **extents):
    container_id = f"{BASE}/container"
    body = {"id": f"{BASE}/media", "type": content_type, "format": mime_type}
    if content_type in {"Audio", "Video"} and "duration" in extents:
        body["duration"] = extents["duration"]
    return {
        "@context": CONTEXT,
        "id": f"{BASE}/manifest",
        "type": "Manifest",
        "label": {"en": ["Example manifest"]},
        "items": [{
            "id": container_id,
            "type": kind,
            **extents,
            "items": [{
                "id": f"{BASE}/page",
                "type": "AnnotationPage",
                "items": [{
                    "id": f"{BASE}/annotation",
                    "type": "Annotation",
                    "motivation": ["painting"],
                    "body": body,
                    "target": {"id": container_id, "type": kind},
                }],
            }],
        }],
    }


def annotation(manifest):
    return manifest["items"][0]["items"][0]["items"][0]


def check(manifest):
    return validate_manifest(json.dumps(manifest))


@pytest.mark.parametrize(
    ("kind", "media_type", "mime_type", "extents"),
    (
        ("Scene", "Model", "model/gltf-binary", {}),
        ("Timeline", "Audio", "audio/mpeg", {"duration": 4.5}),
        ("Canvas", "Image", "image/jpeg", {"width": 200, "height": 150}),
        ("Canvas", "Video", "video/mp4", {"width": 200, "height": 150, "duration": 4.5}),
    ),
)
def test_validates_v4_native_containers(kind, media_type, mime_type, extents):
    result = check(manifest_for(kind, media_type, mime_type, **extents))

    assert result["valid"] is True
    assert result["status"] == "validated"
    assert result["details"]["profile"] == PROFILE_VERSION
    assert result["details"][f"{kind.lower()}_count"] == 1
    assert result["details"]["annotation_page_count"] == 1
    assert result["details"]["annotation_count"] == 1


def test_validates_3d_specific_resources_with_ordered_transforms_and_negative_positions():
    manifest = manifest_for("Scene", "Model", "model/gltf-binary")
    painting = annotation(manifest)
    painting["body"] = {
        "id": f"{BASE}/placed-model",
        "type": "SpecificResource",
        "source": painting["body"],
        "transform": [
            {"type": "RotateTransform", "y": 45},
            {"type": "TranslateTransform", "x": 3, "z": -2},
        ],
    }
    painting["target"] = {
        "id": f"{BASE}/placement",
        "type": "SpecificResource",
        "source": painting["target"],
        "selector": [{"type": "PointSelector", "x": -1, "y": 2, "z": 0}],
    }

    assert check(manifest)["valid"] is True

    painting["body"]["transform"][1]["x"] = True
    result = check(manifest)

    assert result["valid"] is False
    assert any("coordinates must be finite numbers" in error for error in result["errors"])


def test_rejects_legacy_cardinalities_and_wrong_target_source():
    manifest = manifest_for("Scene", "Model", "model/gltf-binary")
    painting = annotation(manifest)
    painting["motivation"] = "painting"
    painting["body"] = [painting["body"]]
    painting["target"] = {"id": f"{BASE}/another-scene", "type": "Scene"}

    result = check(manifest)

    assert result["valid"] is False
    assert result["status"] == "invalid"
    assert any("motivation must be a non-empty array" in error for error in result["errors"])
    assert any("body must be a typed resource object" in error for error in result["errors"])
    assert any("target must reference its Container" in error for error in result["errors"])


@pytest.mark.parametrize(
    ("kind", "media_type", "mime_type", "extents", "message"),
    (
        ("Scene", "Model", "image/jpeg", {}, "MIME type compatible with Model"),
        ("Canvas", "Model", "model/gltf-binary", {"width": 100, "height": 100}, "paint Model into a Scene"),
        ("Canvas", "Video", "video/mp4", {"width": 10, "height": 10}, "painting Video requires a Container duration"),
        ("Timeline", "Audio", "audio/mpeg", {"duration": False}, "duration must be a positive number"),
        ("Timeline", "Image", "image/jpeg", {"duration": 30}, "paint Image into a Canvas"),
    ),
)
def test_rejects_incompatible_content_and_extents(kind, media_type, mime_type, extents, message):
    result = check(manifest_for(kind, media_type, mime_type, **extents))

    assert result["valid"] is False
    assert any(message in error for error in result["errors"])


def test_checks_fragment_and_point_against_their_container_bounds():
    manifest = manifest_for("Timeline", "Audio", "audio/mpeg", duration=6)
    painting = annotation(manifest)
    painting["target"]["id"] += "#t=1,5"
    assert check(manifest)["valid"] is True
    painting["target"]["id"] = f"{BASE}/container#t=1,8"
    assert any("temporal fragment outside" in error for error in check(manifest)["errors"])

    painting["target"] = {
        "id": f"{BASE}/placement",
        "type": "SpecificResource",
        "source": {"id": f"{BASE}/container", "type": "Timeline"},
        "selector": [{"type": "PointSelector", "instant": 4, "z": 1}],
    }
    assert any(".z is outside" in error for error in check(manifest)["errors"])


def test_allows_a_canvas_with_rendering_and_no_painting_items():
    manifest = manifest_for("Canvas", "Image", "image/jpeg", width=200, height=150)
    canvas = manifest["items"][0]
    del canvas["items"]
    canvas["rendering"] = [{
        "id": f"{BASE}/document.pdf",
        "type": "Text",
        "format": "application/pdf",
        "label": {"en": ["Document"]},
    }]

    assert check(manifest)["valid"] is True


def test_retains_explicit_v3_validation_for_historical_manifests():
    manifest = manifest_for("Canvas", "Image", "image/jpeg", width=200, height=150)
    manifest["@context"] = V3_CONTEXT
    painting = annotation(manifest)
    painting["motivation"] = "painting"
    painting["target"] = f"{BASE}/container"

    legacy = validate_legacy_v3_manifest(json.dumps(manifest))
    current = check(manifest)

    assert legacy["valid"] is True
    assert legacy["details"]["profile"] == V3_PROFILE_VERSION
    assert current["valid"] is False
    assert any("must declare the IIIF Presentation v4 context" in error for error in current["errors"])


def test_allows_v4_time_mode_to_fit_media_to_container_duration():
    manifest = manifest_for("Canvas", "Video", "video/mp4", width=200, height=150, duration=5)
    painting = annotation(manifest)
    painting["body"]["duration"] = 10

    assert check(manifest)["valid"] is True

    painting["timeMode"] = "scale"
    assert check(manifest)["valid"] is True


def test_requires_context_on_top_level_and_allows_scoped_extension_contexts():
    manifest = manifest_for("Scene", "Model", "model/gltf-binary")
    manifest["@context"] = [{"custom": {"@id": f"{BASE}/custom", "@context": {"name": f"{BASE}/name"}}}, CONTEXT]
    assert check(manifest)["valid"] is True

    painting = annotation(manifest)
    painting["body"]["@context"] = CONTEXT
    painting["target"] = {
        "id": f"{BASE}/placement",
        "type": "SpecificResource",
        "source": {**painting["target"], "@context": CONTEXT},
    }
    errors = check(manifest)["errors"]
    assert any(".body.@context belongs on the Manifest" in error for error in errors)
    assert any(".target.source.@context belongs on the Manifest" in error for error in errors)


def test_warns_about_inner_service_context_but_rejects_repeated_presentation_context():
    manifest = manifest_for("Canvas", "Image", "image/jpeg", width=200, height=150)
    service = {"@context": "http://iiif.io/api/image/3/context.json", "id": f"{BASE}/image", "type": "ImageService3"}
    annotation(manifest)["body"]["service"] = [service]

    result = check(manifest)
    assert result["valid"] is True
    assert any(".service[0].@context belongs on the Manifest" in warning for warning in result["warnings"])

    service["@context"] = [service["@context"], CONTEXT]
    assert check(manifest)["valid"] is False


@pytest.mark.parametrize(("property_name", "value", "error_path"), [
    ("metadata", None, ".metadata must be an array"),
    ("metadata", [{"label": {"en": ["Attribution"]}}], ".metadata[0].value must be"),
    ("requiredStatement", [{"label": {"en": ["Credit"]}}], ".requiredStatement must be a label/value object"),
    ("requiredStatement", {"label": "Attribution", "value": {"en": ["Museum"]}}, ".requiredStatement.label must be"),
    ("rights", "https://example.org/some-license", ".rights must be a registered"),
    ("rights", "https://creativecommons.org/licenses/by-nc-sa/9.0/", ".rights must be a registered"),
    ("provider", {"type": "Agent"}, ".provider must be a non-empty array"),
    ("provider", [{"type": "Place"}], ".provider[0] must be an Agent"),
    ("provider", [{"id": f"{BASE}/provider", "type": "Agent"}], ".provider[0].label must be"),
    ("rendering", [{"id": f"{BASE}/archive", "type": "Text", "label": {"en": ["ZIP"]},
                    "format": "application/zip"}], "Link machine-readable datasets with seeAlso"),
])
def test_rejects_malformed_authored_presentation_fields(property_name, value, error_path):
    manifest = manifest_for("Canvas", "Image", "image/jpeg", width=200, height=150)
    manifest[property_name] = value

    result = check(manifest)

    assert result["valid"] is False
    assert any(error_path in error for error in result["errors"])


def test_validates_geojson_feature_collection_and_optional_nested_geometry():
    manifest = manifest_for("Canvas", "Image", "image/jpeg", width=200, height=150)
    point = {"type": "Point", "coordinates": [11, 51]}
    polygon = {"type": "Polygon", "coordinates": [[[11, 51], [12, 51], [11, 52], [11, 51]]]}
    manifest["navPlace"] = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "GeometryCollection", "geometries": [point, polygon]}, "properties": None},
    ]}
    assert check(manifest)["valid"] is True

    point["coordinates"] = [181, -90]
    assert any(".geometry must be valid GeoJSON" in error for error in check(manifest)["errors"])
    point["coordinates"] = [11, 51, -100]
    polygon["coordinates"][0][-1] = [10, 50]
    assert any(".geometry must be valid GeoJSON" in error for error in check(manifest)["errors"])
    polygon["coordinates"][0][-1] = [11, 51]
    del manifest["navPlace"]["features"][0]["properties"]
    assert any(".properties must be a JSON object or null" in error for error in check(manifest)["errors"])


@pytest.mark.parametrize(("filename", "mime"), [("archive.zip", "application/zip"), ("catalog.csv", "text/csv"),
                                                  ("catalog.xml", "application/xml")])
def test_generator_links_machine_readable_files_without_painting_them(filename, mime):
    with Flask(__name__).app_context():
        result = IiifService().generate_iiif_manifest_with_report(
            {"title": "Research data"}, {"id": 123, "files": [{"key": filename, "format": mime}]},
            template_content="{}",
        )
    assert result["validation"]["valid"] is True
    container = json.loads(result["content"])["items"][0]
    assert "rendering" not in container and "items" not in container
    assert container["seeAlso"][0]["format"] == mime
    assert container["seeAlso"][0]["type"] == "Dataset"
