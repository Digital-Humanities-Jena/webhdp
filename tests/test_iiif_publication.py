import json
from urllib.parse import urlsplit

import pytest
from flask import Flask
from flask_cors import CORS

from routes.iiif_routes import iiif_bp
from services.iiif_publication import MANIFEST_NAME, published_manifest_id
from services.iiif_service import IiifService
from services.iiif_validation import CONTEXT, V3_CONTEXT

BASE = 'https://iiif.example.org'
URL = '/api/v1/iiif/zenodo/123/manifest.json'
PUBLIC_RECORD = {
    'id': 123,
    'status': 'published',
    'metadata': {'access_right': 'open'},
    'files': [{'key': MANIFEST_NAME}],
}


class UpstreamResponse:
    def __init__(self, status, value=None):
        self.status_code = status
        self.content = value if isinstance(value, bytes) else json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config['IIIF_PUBLIC_BASE_URL'] = BASE
    CORS(app, origins=['https://frontend.example.org'], supports_credentials=True)
    app.register_blueprint(iiif_bp, url_prefix='/api/v1/iiif')
    return app.test_client()


@pytest.fixture
def upstream(monkeypatch):
    responses = [UpstreamResponse(200, PUBLIC_RECORD)]
    calls = []

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def get(self, url, **options):
            assert not self.trust_env
            assert options == {'headers': {'Accept': 'application/json'}, 'allow_redirects': False,
                               'stream': True, 'timeout': (3, 8)}
            calls.append(url)
            return responses.pop(0)

    monkeypatch.setattr('services.iiif_publication.requests.Session', Session)
    return responses, calls


def manifest_bytes(profile):
    context = ["https://example.org/additional-context.json", profile]
    return json.dumps({'@context': context, 'id': 'https://example.org/original-manifest',
                       'type': 'Manifest', 'label': {'en': ['An image']}}, indent=2).encode() + b'\n'


@pytest.mark.parametrize('profile', [V3_CONTEXT, CONTEXT])
def test_public_manifest_preserves_bytes_and_announces_its_profile(client, upstream, profile):
    responses, calls = upstream
    content = manifest_bytes(profile)
    responses.append(UpstreamResponse(200, content))

    result = client.get(URL, headers={'Origin': 'https://frontend.example.org'})

    assert result.status_code == 200
    assert result.data == content
    assert result.headers['Content-Type'] == f'application/ld+json; profile="{profile}"'
    assert result.headers['Access-Control-Allow-Origin'] == '*'
    assert 'Access-Control-Allow-Credentials' not in result.headers
    assert result.headers['Vary'] == 'Accept'
    assert result.cache_control.public and result.cache_control.no_cache
    assert calls == ['https://zenodo.org/api/records/123',
                     'https://zenodo.org/api/records/123/files/iiif.json/content']


def test_manifest_supports_negotiation_head_and_conditional_requests(client, upstream):
    responses, _ = upstream
    content = manifest_bytes(CONTEXT)
    responses[:] = [response for _ in range(7) for response in
                    (UpstreamResponse(200, PUBLIC_RECORD), UpstreamResponse(200, content))]
    environment_url = URL.replace('/zenodo/', '/sandbox/')

    result = client.get(environment_url, headers={'Accept': 'application/json'})
    assert result.status_code == 200 and result.content_type == 'application/json'
    assert result.data == content
    etag = result.headers['ETag']
    result = client.head(environment_url, headers={'Accept': f'application/ld+json; profile="{CONTEXT}"'})
    assert result.status_code == 200 and result.data == b''
    assert result.content_length == len(content) and result.headers['ETag'] == etag
    assert result.headers['Content-Type'] == f'application/ld+json; profile="{CONTEXT}"'
    result = client.get(environment_url, headers={'If-None-Match': etag})
    assert result.status_code == 304 and result.data == b''
    assert result.headers['Access-Control-Allow-Origin'] == '*'
    result = client.get(environment_url, headers={'Accept': f'application/ld+json; profile="{V3_CONTEXT}"'})
    assert result.status_code == 406
    result = client.get(environment_url, headers={'Accept': '*/*'})
    assert result.status_code == 200 and result.headers['ETag'] == etag
    result = client.get(environment_url, headers={'Accept': 'application/ld+json; charset=UTF-8'})
    assert result.status_code == 200 and result.headers['Content-Type'].startswith('application/ld+json')
    result = client.get(environment_url, headers={
        'Accept': f'application/ld+json, application/ld+json; profile="{CONTEXT}"; q=0, application/json; q=0.1',
    })
    assert result.status_code == 200 and result.headers['Content-Type'] == 'application/json'
    assert all(urlsplit(url).hostname == 'sandbox.zenodo.org' for url in upstream[1])


@pytest.mark.parametrize('record', [
    {**PUBLIC_RECORD, 'status': 'draft'},
    {**PUBLIC_RECORD, 'is_published': False},
    {**PUBLIC_RECORD, 'metadata': {'access_right': 'restricted'}},
    {**PUBLIC_RECORD, 'access': {'files': 'restricted', 'record': 'public'}},
    {**PUBLIC_RECORD, 'files': []},
    {**PUBLIC_RECORD, 'id': 321},
    {'id': 123, 'is_published': True, 'files': [{'key': MANIFEST_NAME}]},
])
def test_private_unpublished_or_unbound_attachment_is_not_fetched(client, upstream, record):
    responses, calls = upstream
    responses[:] = [UpstreamResponse(200, record)]

    result = client.get(URL)

    assert result.status_code == 404
    assert calls == ['https://zenodo.org/api/records/123']


def test_public_zenodo_api_with_structured_file_entries(client, upstream):
    responses, _ = upstream
    responses[:] = [UpstreamResponse(200, {
        'id': '123', 'is_published': True, 'access': {'files': 'public', 'record': 'public'},
        'files': {'enabled': True, 'entries': {MANIFEST_NAME: {'size': 15}}},
    }), UpstreamResponse(200, manifest_bytes(CONTEXT))]

    assert client.get(URL).status_code == 200


def test_preflight_invalid_routes_and_unconfigured_service_never_fetch(client, upstream):
    result = client.options(URL, headers={'Origin': 'https://viewer.example.org',
                                         'Access-Control-Request-Method': 'GET'})
    assert result.status_code == 204 and result.headers['Access-Control-Allow-Origin'] == '*'
    assert client.get(URL.replace('zenodo', 'some-other-host')).status_code == 404
    assert client.get(URL.replace('123', 'random')).status_code == 404
    client.application.config['IIIF_PUBLIC_BASE_URL'] = ''
    assert client.get(URL).status_code == 404
    assert upstream[1] == []


@pytest.mark.parametrize('status', [301, 302, 500])
def test_upstream_redirect_or_failure_returns_bad_gateway(client, upstream, status):
    responses, calls = upstream
    responses[:] = [UpstreamResponse(status)]

    assert client.get(URL).status_code == 502
    assert calls == ['https://zenodo.org/api/records/123']


@pytest.mark.parametrize('body', [b'x' * (2 * 1024 * 1024 + 1), b'garbage', manifest_bytes('https://example.org')])
def test_rejects_unbounded_or_non_manifest_attachments(client, upstream, body):
    responses, _ = upstream
    responses.append(UpstreamResponse(200, body))

    assert client.get(URL).status_code == 502


def test_generation_canonical_id_uses_the_opt_in_base(client):
    with client.application.app_context():
        expected = f'{BASE}/api/v1/iiif/sandbox/123/manifest.json'
        assert published_manifest_id(123, is_sandbox=True) == expected
        content = IiifService().generate_iiif_manifest_with_report(
            {'title': 'Model'}, {'id': 123, 'links': {'html': 'https://sandbox.zenodo.org/records/123'},
                                'files': [{'key': 'object.glb'}]}, template_content='{}')['content']
        assert json.loads(content)['id'] == expected
        client.application.config['IIIF_PUBLIC_BASE_URL'] = ''
        assert published_manifest_id(123, is_sandbox=True) == 'https://sandbox.zenodo.org/api/records/123/files/iiif.json/content'
