import pandas as pd

from services.msf_service import MSFService


def test_apply_lod_mapping_supports_zenodo_tags():
    service = MSFService()
    row = pd.Series(
        {
            "title": "Mapped title",
            "description": "Mapped description",
            "creator": "Alice Doe, Bob Doe",
            "keywords": "3d, heritage",
            "dcterms:created": "2024-02-01",
        }
    )
    zenodo_record = {
        "metadata": {
            "license": "cc-by-4.0",
            "access_right": "open",
        }
    }
    mapping_config = {
        "zenodo:title": {"source": "msf", "field": "title"},
        "zenodo:description": {"source": "msf", "field": "description"},
        "zenodo:upload_type": {"source": "options", "value": "dataset"},
        "zenodo:publication_date": {"source": "msf", "field": "dcterms:created"},
        "zenodo:creators": {"source": "msf", "field": "creator"},
        "zenodo:access_right": {"source": "zenodo", "field": "metadata.access_right"},
        "zenodo:license": {"source": "zenodo", "field": "metadata.license"},
        "zenodo:communities": {"source": "static", "value": "3d-big-data-space,other-community"},
        "zenodo:keywords": {"source": "msf", "field": "keywords"},
    }

    mapped = service.apply_lod_mapping(row, zenodo_record, mapping_config, include_defaults=False)

    assert mapped["title"] == "Mapped title"
    assert mapped["description"] == "Mapped description"
    assert mapped["upload_type"] == "dataset"
    assert mapped["publication_date"] == "2024-02-01"
    assert mapped["cho_created"] == "2024-02-01"
    assert mapped["access_right"] == "open"
    assert mapped["license"] == "cc-by-4.0"
    assert mapped["creators"] == [{"name": "Alice Doe"}, {"name": "Bob Doe"}]
    assert mapped["communities"] == [
        {"identifier": "3d-big-data-space"},
        {"identifier": "other-community"},
    ]
    assert mapped["keywords"] == ["3d", "heritage"]


def test_apply_lod_mapping_derives_cho_created_from_created_alias_when_mapping_zenodo_publication_date():
    service = MSFService()
    row = pd.Series(
        {
            "date": "1998-06-12",
        }
    )
    mapping_config = {
        "zenodo:publication_date": {"source": "msf", "field": "date"},
    }

    mapped = service.apply_lod_mapping(row, {"metadata": {}}, mapping_config, include_defaults=False)

    assert mapped["publication_date"] == "1998-06-12"
    assert mapped["cho_created"] == "1998-06-12"


def test_apply_lod_mapping_ignores_nan_and_applies_defaults_for_mandatory_fields():
    service = MSFService()
    row = pd.Series(
        {
            "filename": "6Kr_2.glb",
            "title": float("nan"),
            "creator": float("nan"),
            "date": float("nan"),
        }
    )
    mapping_config = {
        "dc:title": {"source": "msf", "field": "title"},
        "dc:creator": {"source": "msf", "field": "creator"},
        "dcterms:created": {"source": "msf", "field": "date"},
    }

    mapped = service.apply_lod_mapping(row, {"metadata": {}}, mapping_config, include_defaults=True)

    assert mapped["title"] == "6Kr_2.glb"
    assert mapped["creators"] == [{"name": "Unknown"}]
    assert "cho_created" not in mapped
    assert isinstance(mapped["publication_date"], str)
    assert len(mapped["publication_date"]) == 10


def test_apply_lod_mapping_preserves_surname_first_creator_notation():
    service = MSFService()
    row = pd.Series({"creator": "Schild, Romuald"})
    mapping_config = {
        "dc:creator": {"source": "msf", "field": "creator"},
    }

    mapped = service.apply_lod_mapping(row, {"metadata": {}}, mapping_config, include_defaults=False)

    assert mapped["creators"] == [{"name": "Schild, Romuald"}]


def test_iiif_mappings_keep_timeline_and_geographic_values_distinct_from_scene_coordinates():
    values = {
        "iiif:timelineId": "https://example.org/timeline/1",
        "iiif:timelineLabel": "Oral history",
        "iiif:latitude": "50",
        "iiif:longitude": "11",
        "iiif:altitude": "26",
        "iiif:pointX": "0",
    }
    mapping = {key: {"source": "static", "value": value} for key, value in values.items()}
    assert MSFService().apply_lod_mapping(pd.Series(dtype=object), {}, mapping, include_defaults=False) == {
        "iiif_timeline_id": "https://example.org/timeline/1",
        "iiif_timeline_label": "Oral history",
        "iiif_latitude": "50",
        "iiif_longitude": "11",
        "iiif_altitude": "26",
        "iiif_point_x": "0",
    }


def test_iiif_content_id_keeps_legacy_template_value_and_prefers_current_mapping():
    old = {"iiif:modelId": {"source": "static", "value": "https://example.org/model.glb"}}
    updated = {"iiif:contentId": {"source": "static", "value": "https://example.org/replacement.glb"}}
    service = MSFService()
    row = pd.Series(dtype=object)

    legacy = service.apply_lod_mapping(row, {}, old, include_defaults=False)
    current = service.apply_lod_mapping(row, {}, {**old, **updated}, include_defaults=False)

    assert legacy["iiif_model_id"] == legacy["iiif_content_id"] == old["iiif:modelId"]["value"]
    assert current["iiif_model_id"] == legacy["iiif_model_id"]
    assert current["iiif_content_id"] == updated["iiif:contentId"]["value"]


def test_get_metadata_for_file_passes_through_3d_analysis_fields():
    service = MSFService()
    df = pd.DataFrame(
        [
            {
                "filename": "cloud.ply",
                "title": "Survey cloud",
                "model type": "point_cloud",
                "edm:pointCount": "12345",
                "edm:polygonCount": "0",
                "vertex count": "12345",
            }
        ]
    )

    metadata = service.get_metadata_for_file(df, "cloud.ply", "filename")

    assert metadata["model_type"] == "point_cloud"
    assert metadata["point_count"] == "12345"
    assert metadata["polygon_count"] == "0"
    assert metadata["vertex_count"] == "12345"


def test_get_metadata_for_file_uses_affiliation_when_creator_is_missing():
    service = MSFService()
    df = pd.DataFrame(
        [
            {
                "filename": "piec1_gotycki.glb",
                "title": "",
                "creator": "",
                "creator_affiliation": "RCIN / IAE PAN",
                "identifier": "piec1_gotycki",
            }
        ]
    )

    metadata = service.get_metadata_for_file(df, "piec1_gotycki.glb", "filename")

    assert metadata["creators"] == [{"name": "RCIN / IAE PAN"}]
    assert metadata["_affiliations_raw"] == "RCIN / IAE PAN"
    assert metadata["_external_identifier"] == "piec1_gotycki"


def test_get_metadata_for_file_leaves_creators_unset_when_creator_and_affiliation_are_missing():
    service = MSFService()
    df = pd.DataFrame(
        [
            {
                "filename": "Gr_149_Naczynie_1.glb",
                "title": "Pottery, grave no. 149",
                "description": "Pottery",
                "creator": "",
                "creator_affiliation": "",
                "identifier": "oai:rcin.org.pl:243927",
            }
        ]
    )

    metadata = service.get_metadata_for_file(df, "Gr_149_Naczynie_1.glb", "filename")

    assert "creators" not in metadata
    assert metadata["_external_identifier"] == "oai:rcin.org.pl:243927"
