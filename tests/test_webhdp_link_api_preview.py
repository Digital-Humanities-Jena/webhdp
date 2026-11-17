"""The temporary UI preview cannot reach queue mutations or HPC polling APIs."""
import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from scripts.run_webhdp_link_api_preview import ReadOnlyPreview, frontend_environment


@pytest.mark.parametrize('method,path,allowed', [
    ('GET','/api/v1/link/jobs',True),
    ('GET','/api/v1/link/jobs/123-abc',True),
    ('HEAD','/api/v1/link/jobs/123-abc/artifacts/456-def',True),
    ('POST','/api/v1/auth/login',True),
    ('OPTIONS','/api/v1/link/jobs/123-abc/cancel',True),
    ('POST','/api/v1/link/jobs/123-abc/cancel',False),
    ('POST','/api/v1/link/runs',False),
    ('DELETE','/api/v1/link/grants/123',False),
    ('GET','/api/v1/hpc/allocations',False),
    ('GET','/api/v1/auth/verify-email/token',False),
    ('POST','/api/v1/auth/login/resend-code',False),
])
def test_preview_blocks_mutations_and_reads_with_possible_operational_side_effects(method,path,allowed):
    calls = []
    def application(environ,start_response):
        calls.append((environ['REQUEST_METHOD'],environ['PATH_INFO']))
        return Response('OK')(environ,start_response)
    client = Client(ReadOnlyPreview(application,'http://127.0.0.1:5174'),Response)
    response = client.open(path,method=method,headers={'Origin':'http://127.0.0.1:5174'})
    assert response.status_code == (200 if allowed else 405)
    assert bool(calls) is allowed
    if not allowed:
        assert response.headers['Access-Control-Allow-Origin'] == 'http://127.0.0.1:5174'


def test_preview_frontend_receives_only_system_environment_and_api_url(monkeypatch):
    monkeypatch.setenv('HPC_LINK_PASSWORD','private-service-password')
    monkeypatch.setenv('SECRET_KEY','private-session-secret')
    monkeypatch.setenv('VITE_ACCIDENTAL_SECRET','private-build-secret')
    environment = frontend_environment(5101)
    assert environment['VITE_API_URL'] == 'http://127.0.0.1:5101'
    assert not any('private-' in value for value in environment.values())
    assert set(environment).issubset({'PATH','HOME','TMPDIR','TEMP','TMP','SHELL','LANG','LC_ALL','LC_CTYPE','TERM','VITE_API_URL'})
