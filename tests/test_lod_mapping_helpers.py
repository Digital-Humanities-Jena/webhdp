import pandas as pd

from routes.lod_mapping_helpers import build_pipeline_aligned_lod_metadata
from services.msf_service import MSFService


def test_build_pipeline_aligned_lod_metadata_uses_zenodo_defaults_for_missing_msf_fields():
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

    metadata = build_pipeline_aligned_lod_metadata(
        msf_service=service,
        row=row,
        zenodo_record={"metadata": {}},
        mapping_config=mapping_config,
        msf_profile={"filename_column": "filename"},
    )

    assert metadata["title"] == "6Kr_2"
    assert metadata["creators"] == [{"name": "Unknown"}]
    assert "cho_created" not in metadata
    assert isinstance(metadata["publication_date"], str)
    assert len(metadata["publication_date"]) == 10


def test_build_pipeline_aligned_lod_metadata_does_not_overwrite_with_empty_static_value():
    service = MSFService()
    row = pd.Series({"filename": "object.glb"})
    mapping_config = {
        "dc:title": {"source": "static", "value": ""},
    }

    metadata = build_pipeline_aligned_lod_metadata(
        msf_service=service,
        row=row,
        zenodo_record={"metadata": {"title": "Base title"}},
        mapping_config=mapping_config,
        msf_profile={"filename_column": "filename"},
    )

    assert metadata["title"] == "Base title"
