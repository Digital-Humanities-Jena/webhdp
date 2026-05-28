import pytest

from services.public_oembed_service import (
    PublicRecordError,
    build_oembed_response,
    build_public_record,
    calculate_oembed_size,
    parse_public_record_url,
)


class FakeZenodoCache:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def fetch(self, is_sandbox, record_id):
        self.calls.append((is_sandbox, record_id))
        return self.payload


def _public_payload():
    return {
        "id": "12345",
        "metadata": {
            "title": "Public 3D Model",
            "creators": [{"person_or_org": {"name": "Ada Lovelace"}}],
            "publication_date": "2026-04-29",
        },
        "pids": {"doi": {"identifier": "10.5281/zenodo.12345"}},
        "links": {"html": "https://zenodo.org/records/12345"},
        "files": {
            "entries": {
                "model.glb": {"key": "model.glb", "size": 1024},
                "model_preview.png": {"key": "model_preview.png", "size": 256},
            }
        },
    }


def test_build_public_record_uses_public_zenodo_payload_for_preview():
    record = build_public_record(
        "zenodo",
        "12345",
        public_base_url="https://webhdp.example",
        cache=FakeZenodoCache(_public_payload()),
    )

    assert record["title"] == "Public 3D Model"
    assert record["author_name"] == "Ada Lovelace"
    assert record["doi"] == "10.5281/zenodo.12345"
    assert record["public_url"] == "https://webhdp.example/p/records/zenodo/12345"
    assert record["embed_url"] == "https://webhdp.example/embed/records/zenodo/12345"
    assert record["thumbnail_url"] == "https://zenodo.org/api/records/12345/files/model_preview.png/content"
    assert record["model_preview"]["can_inline_preview"] is True
    assert record["model_preview"]["url"] == "https://zenodo.org/api/records/12345/files/model.glb/content"


def test_parse_public_record_url_accepts_public_and_embed_urls():
    assert parse_public_record_url("https://webhdp.example/p/records/zenodo/123") == ("zenodo", "123")
    assert parse_public_record_url("https://webhdp.example/embed/records/sandbox/abc-123") == ("sandbox", "abc-123")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://webhdp.example/dashboard",
        "https://webhdp.example/p/records/private/123",
        "https://webhdp.example/p/records/zenodo/../../../etc/passwd",
    ],
)
def test_parse_public_record_url_rejects_invalid_urls(url):
    with pytest.raises(PublicRecordError):
        parse_public_record_url(url)


def test_calculate_oembed_size_respects_max_dimensions():
    assert calculate_oembed_size() == (640, 480)
    assert calculate_oembed_size(maxwidth="320") == (320, 240)
    assert calculate_oembed_size(maxwidth="640", maxheight="240") == (320, 240)


def test_build_oembed_response_returns_rich_iframe():
    response = build_oembed_response(
        {
            "title": "Public 3D Model",
            "provider_name": "WebHDP",
            "provider_url": "https://webhdp.example",
            "author_name": "Ada Lovelace",
            "embed_url": "https://webhdp.example/embed/records/zenodo/12345",
            "thumbnail_url": "https://zenodo.org/api/records/12345/files/preview.png/content",
        },
        maxwidth="300",
    )

    assert response["version"] == "1.0"
    assert response["type"] == "rich"
    assert response["width"] == 300
    assert response["height"] == 225
    assert 'src="https://webhdp.example/embed/records/zenodo/12345"' in response["html"]
    assert response["thumbnail_url"].endswith("/preview.png/content")
