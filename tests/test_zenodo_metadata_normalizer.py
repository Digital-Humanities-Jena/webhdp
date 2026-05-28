from datetime import date, datetime

from services.zenodo_metadata_normalizer import normalize_publication_date, normalize_zenodo_metadata


def test_normalize_publication_date_strips_time_component():
    assert normalize_publication_date("2025-12-17 00:00:00") == "2025-12-17"
    assert normalize_publication_date("2025-12-17T14:25:33Z") == "2025-12-17"
    assert normalize_publication_date(date(2025, 12, 17)) == "2025-12-17"
    assert normalize_publication_date(datetime(2025, 12, 17, 10, 30, 1)) == "2025-12-17"


def test_normalizer_without_defaults_keeps_shape_and_filters_unknown():
    metadata = {
        "title": "Record title",
        "publication_date": "2025-12-17 00:00:00",
        "creators": '[{"name":"A. User"}]',
        "communities": "3d-big-data-space;another-community",
        "unknown_field": "drop me",
    }

    normalized = normalize_zenodo_metadata(metadata, apply_defaults=False)

    assert normalized["title"] == "Record title"
    assert normalized["publication_date"] == "2025-12-17"
    assert normalized["creators"] == [{"name": "A. User"}]
    assert normalized["communities"] == [
        {"identifier": "3d-big-data-space"},
        {"identifier": "another-community"},
    ]
    assert "unknown_field" not in normalized


def test_normalizer_with_defaults_prevents_common_validation_failures():
    normalized = normalize_zenodo_metadata(
        {
            "upload_type": "invalid_type",
            "access_right": "INVALID",
            "creators": "",
            "description": "",
            "publication_date": "",
        },
        apply_defaults=True,
        fallback_title="file_stem",
    )

    assert normalized["title"] == "file_stem"
    assert normalized["upload_type"] == "dataset"
    assert normalized["access_right"] == "open"
    assert normalized["license"] == "cc-by-4.0"
    assert normalized["creators"] == [{"name": "Unknown"}]
    assert normalized["description"] == "No description provided."
    assert isinstance(normalized["publication_date"], str)


def test_normalizer_with_defaults_uses_custom_description_and_creator_fallbacks():
    normalized = normalize_zenodo_metadata(
        {
            "creators": "",
            "description": "",
            "publication_date": "",
        },
        apply_defaults=True,
        fallback_title="file_stem",
        fallback_description="No item-specific description provided.",
        fallback_creators=[{"name": "RCIN / IAE PAN"}],
    )

    assert normalized["title"] == "file_stem"
    assert normalized["description"] == "No item-specific description provided."
    assert normalized["creators"] == [{"name": "RCIN / IAE PAN"}]


def test_normalizer_with_defaults_recovers_from_invalid_dates_and_embargo():
    normalized = normalize_zenodo_metadata(
        {
            "title": "Example",
            "description": "desc",
            "upload_type": "dataset",
            "publication_date": "17-12-2025",
            "creators": [{"name": "A"}],
            "access_right": "embargoed",
            "embargo_date": "2020-01-01",
        },
        apply_defaults=True,
    )

    # Invalid publication date is replaced with a valid fallback.
    assert len(normalized["publication_date"]) == 10
    # Invalid/past embargo is downgraded to open to keep metadata valid.
    assert normalized["access_right"] == "open"
    assert "embargo_date" not in normalized
