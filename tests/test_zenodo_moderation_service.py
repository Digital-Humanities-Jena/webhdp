from services import zenodo_moderation_service


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_fetch_community_request_page_sends_status_filter(monkeypatch):
    calls = []

    def _mock_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if url.endswith("/api/communities/3dbigdataspace"):
            return _Response({"id": "uuid-1", "slug": "3dbigdataspace", "metadata": {"title": "3D"}, "links": {"requests": "https://zenodo.org/api/communities/3dbigdataspace/requests"}})
        return _Response({"hits": {"total": 1201, "hits": []}})

    monkeypatch.setenv("ZENODO_API_KEY", "token")
    monkeypatch.setattr(zenodo_moderation_service, "make_rate_limited_request", _mock_request)

    result = zenodo_moderation_service.fetch_community_request_page("3dbigdataspace", status="submitted", page=1, size=100)

    assert result["total"] == 1201
    assert calls[-1]["kwargs"]["params"]["status"] == "submitted"
    assert calls[-1]["kwargs"]["params"]["page"] == 1
    assert calls[-1]["kwargs"]["params"]["size"] == 100


def test_summarize_community_requests_uses_authoritative_total(monkeypatch):
    monkeypatch.setattr(
        zenodo_moderation_service,
        "fetch_community_request_page",
        lambda *args, **kwargs: {
            "community": {"slug": "3dbigdataspace"},
            "status": "submitted",
            "request_type": None,
            "total": 12871,
            "requests": [
                {
                    "request_id": "req-1",
                    "is_open": True,
                    "links": {"actions": {"accept": "a", "decline": "d"}},
                }
            ],
        },
    )

    result = zenodo_moderation_service.summarize_community_requests("3dbigdataspace", action="accept")

    assert result["total"] == 12871
    assert result["preview_count"] == 1
    assert result["preview_actionable_count"] == 1
