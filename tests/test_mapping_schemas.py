import pytest
from pydantic import ValidationError, TypeAdapter

from schemas.mapping_schemas import MappingConfig


def _validate(mapping):
    return TypeAdapter(MappingConfig).validate_python(mapping)


def test_mapping_schema_requires_field_for_msf_source():
    payload = {
        "edm": {
            "3d": {
                "dc:title": {"source": "msf", "field": "", "value": ""},
            }
        }
    }

    with pytest.raises(ValidationError):
        _validate(payload)


def test_mapping_schema_requires_value_for_static_source():
    payload = {
        "edm": {
            "3d": {
                "dc:title": {"source": "static", "field": "", "value": ""},
            }
        }
    }

    with pytest.raises(ValidationError):
        _validate(payload)


def test_mapping_schema_allows_skip_without_field_or_value():
    payload = {
        "edm": {
            "3d": {
                "dc:title": {"source": "skip", "field": "", "value": ""},
            }
        }
    }

    validated = _validate(payload)
    assert validated["edm"]["3d"]["dc:title"].source == "skip"
