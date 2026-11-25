import json
from copy import deepcopy

import pytest
from flask import Flask

from database.database import db
from database.models import LodStandard, LodTemplate
from services.iiif_service import IiifService
from services.iiif_validation import CONTEXT, V3_CONTEXT
from services.lod_reliability import digest, pinned_templates


@pytest.fixture(autouse=True)
def application_context():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", ENABLE_RENDERER=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield


def legacy_canvas(name, body):
    identifier = f"https://example.org/{name}"
    return {
        "id": identifier,
        "type": "Canvas",
        "width": 800,
        "height": 600,
        "items": [{
            "id": f"{identifier}/page",
            "type": "AnnotationPage",
            "items": [{
                "id": f"{identifier}/annotation",
                "type": "Annotation",
                "motivation": "painting",
                "body": body,
                "target": identifier,
            }],
        }],
    }


def legacy_manifest(*items):
    return {
        "@context": V3_CONTEXT,
        "id": "https://example.org/manifest",
        "type": "Manifest",
        "label": {"en": ["Collection record"]},
        "items": items,
    }


def generated_annotation(container):
    return container["items"][0]["items"][0]


def test_saved_legacy_template_migrates_each_authored_container():
    image = legacy_canvas("photo", "https://example.org/curated.jpg")
    sound = legacy_canvas("oral-history", [{"id": "https://example.org/interview.wav", "type": "Sound", "format": "audio/wav"}])
    sound["duration"] = 20
    generated_annotation(sound)["target"] = [{"id": sound["id"], "type": "Canvas"}]
    model = legacy_canvas("model", {"type": "SpecificResource", "source": "https://example.org/original.glb",
                                    "transform": {"type": "ScaleTransform", "x": 2}})
    generated_annotation(model)["target"] = {"type": "SpecificResource", "source": model["id"],
                                             "selector": {"type": "PointSelector", "z": 3}}
    content = json.dumps(legacy_manifest(image, sound, model))
    template = LodTemplate(name="Curated multi-media IIIF", standard=LodStandard.IIIF, format="json", content=content)
    db.session.add(template)
    db.session.commit()

    report = IiifService().generate_iiif_manifest_with_report({}, {"id": 7}, template_id=template.id)

    manifest = json.loads(report["content"])
    assert report["validation"]["valid"]
    assert manifest["@context"] == CONTEXT
    picture, timeline, scene = manifest["items"]
    assert [item["type"] for item in manifest["items"]] == ["Canvas", "Timeline", "Scene"]
    assert [item["id"] for item in manifest["items"]] == [image["id"], sound["id"], model["id"]]
    assert generated_annotation(picture)["body"]["id"] == "https://example.org/curated.jpg"
    assert generated_annotation(timeline)["body"]["type"] == "Audio"
    assert generated_annotation(timeline)["target"]["type"] == "Timeline"
    annotation = generated_annotation(scene)
    assert annotation["body"]["id"].endswith("#body")
    assert annotation["body"]["source"]["id"] == "https://example.org/original.glb"
    assert annotation["target"]["source"]["type"] == "Scene"
    assert annotation["target"]["selector"] == [{"type": "PointSelector", "z": 3}]
    assert db.session.get(LodTemplate, template.id).content == content


def test_legacy_template_reports_ambiguous_painting_resource():
    canvas = legacy_canvas("photo", ["https://example.org/one.jpg", "https://example.org/two.jpg"])
    with pytest.raises(ValueError, match="legacy body array must identify exactly one resource"):
        IiifService().generate_iiif_manifest_with_report({}, {"id": 7}, template_content=json.dumps(legacy_manifest(canvas)))


def test_single_legacy_painting_preserves_the_authored_asset_and_extension_context():
    original = "https://example.org/curated.jpeg"
    manifest = legacy_manifest(legacy_canvas("photo", original))
    scope = "https://example.org/curated-context.json"
    manifest["@context"] = [scope, V3_CONTEXT]

    result = IiifService().generate_iiif_manifest_with_report(
        {}, {"id": 7, "files": [{"key": "other.jpg"}]}, template_content=json.dumps(manifest),
    )

    data = json.loads(result["content"])
    assert data["@context"] == [scope, CONTEXT]
    assert generated_annotation(data["items"][0])["body"]["id"] == original


def test_pre_rc_wrappers_unwrap_a_single_source_without_changing_it():
    manifest = json.loads(pre_rc_scene_template())
    scene = manifest["items"][0]
    annotation = generated_annotation(scene)
    model = annotation["body"][0]
    target = {"id": scene["id"], "type": "Scene"}
    annotation["motivation"] = ["painting"]
    annotation["body"] = {"id": f"{annotation['id']}#src", "type": "SpecificResource", "source": [model]}
    annotation["target"] = {"id": f"{annotation['id']}#tgt", "type": "SpecificResource", "source": [target]}

    result = IiifService().generate_iiif_manifest_with_report(
        {}, {"id": 7}, template_content=json.dumps(manifest),
    )

    generated = generated_annotation(json.loads(result["content"])["items"][0])
    assert generated["body"]["source"] == model
    assert generated["target"]["source"] == target


def test_legacy_supplemental_annotations_require_explicit_migration():
    canvas = legacy_canvas("photo", "https://example.org/photo.jpg")
    canvas["annotations"] = [{"id": "https://example.org/supplemental", "type": "AnnotationPage"}]
    with pytest.raises(ValueError, match="Supplemental AnnotationPages need explicit migration"):
        IiifService().generate_iiif_manifest_with_report({}, {"id": 7}, template_content=json.dumps(legacy_manifest(canvas)))


def pre_rc_scene_template():
    scene = legacy_canvas("scene", [{"id": "https://example.org/curated.glb", "type": "Model", "format": "model/gltf-binary"}])
    scene["type"] = "Scene"
    manifest = legacy_manifest(scene)
    manifest["@context"] = CONTEXT
    return json.dumps(manifest)


def test_retry_reads_pinned_legacy_bundle_through_the_current_seed(monkeypatch):
    content = pre_rc_scene_template()
    monkeypatch.setattr("database.seed_iiif_templates.LEGACY_IIIF_BUNDLE_HASHES", {digest(content)})
    snapshot = {"iiif": {"id": 81, "name": "IIIF v4 3D Scene", "standard": "iiif", "content": content}}
    original = deepcopy(snapshot)
    record = {"id": 7, "files": [{"key": "current.glb"}]}

    with pinned_templates(snapshot):
        report = IiifService().generate_iiif_manifest_with_report({}, record, template_id=81)

    assert snapshot == original
    data = json.loads(report["content"])
    assert data["id"] == "https://zenodo.org/api/records/7/files/iiif.json/content"
    assert generated_annotation(data["items"][0])["body"]["id"].endswith("/current.glb/content")


def test_custom_pre_rc_scene_with_legacy_bundle_name_keeps_its_assets():
    content = pre_rc_scene_template()
    template = LodTemplate(name="IIIF v4 3D Scene", standard=LodStandard.IIIF, format="json",
                           content=content, is_default=True)
    db.session.add(template)
    db.session.commit()

    report = IiifService().generate_iiif_manifest_with_report({}, {"id": 7}, template_id=template.id)

    data = json.loads(report["content"])
    scene = data["items"][0]
    assert scene["type"] == "Scene"
    assert generated_annotation(scene)["body"]["id"] == "https://example.org/curated.glb"
    assert generated_annotation(scene)["target"] == {"id": "https://example.org/scene", "type": "Scene"}
    assert db.session.get(LodTemplate, template.id).content == content


@pytest.mark.parametrize("pixel_dimensions", [{"width": 320, "height": 240}, {"width": 320}])
def test_canvas_frame_extents_and_asset_pixel_dimensions_are_distinct(pixel_dimensions):
    record = {"id": 7, "files": [{"key": "photo.jpg", **pixel_dimensions}]}
    result = IiifService().generate_iiif_manifest_with_report(
        {"iiif_width": 1600, "iiif_height": 900}, record, template_content="{}",
    )

    canvas = json.loads(result["content"])["items"][0]
    assert (canvas["width"], canvas["height"]) == (1600, 900)
    body = generated_annotation(canvas)["body"]
    if "height" in pixel_dimensions:
        assert (body["width"], body["height"]) == (320, 240)
    else:
        assert "width" not in body and "height" not in body


@pytest.mark.parametrize(("filename", "kind"), [("image.jpg", "Image"), ("interview.wav", "Audio")])
def test_model_overrides_do_not_replace_other_media(filename, kind):
    service = IiifService()
    result = service.generate_iiif_manifest_with_report(
        {"iiif_model_id": "https://example.org/incorrect.glb", "iiif_model_label": "Model label", "iiif_duration": 10},
        {"id": 7, "files": [{"key": filename}]},
        template_content="{}",
    )
    body = generated_annotation(json.loads(result["content"])["items"][0])["body"]
    assert body["id"] == f"https://zenodo.org/api/records/7/files/{filename}/content"
    assert body["type"] == kind
    assert "label" not in body
