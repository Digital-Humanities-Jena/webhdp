import pytest

from services.edm_service import EdmService


@pytest.mark.parametrize('local_valid, remote, expected', [
    (True, {'valid': False, 'status': 'unavailable'}, 'unverified'),
    (False, {'valid': False, 'status': 'unavailable'}, 'invalid'),
    (True, {'valid': False, 'status': 'failed'}, 'invalid'),
    (True, {'valid': True, 'status': 'validated'}, 'validated'),
])
def test_validation_distinguishes_unavailable_checks_from_known_metadata_errors(monkeypatch, local_valid, remote, expected):
    service = EdmService()
    for name in ('validate_with_xsd', 'validate_with_schematron', 'validate_edm_business_rules'):
        monkeypatch.setattr(service, name, lambda *args, **kwargs: {'valid': True})
    monkeypatch.setattr(service, 'validate_xml', lambda *args: {'valid': local_valid, 'errors': [] if local_valid else ['Invalid XML']})
    monkeypatch.setattr(service, 'validate_with_local_edm_validator', lambda *args, **kwargs: remote)
    result = service.validate_edm_document('<rdf/>', include_remote=True)
    assert result['status'] == expected
    assert result['valid'] is (expected == 'validated')
    if not local_valid:
        assert 'Invalid XML' in result['errors']
