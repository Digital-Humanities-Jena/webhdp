import copy
import json

import pytest
from flask import Flask

from services.iiif_service import IiifService


@pytest.fixture(autouse=True)
def application_context():
    app = Flask(__name__)
    app.config['ENABLE_RENDERER'] = False
    with app.app_context():
        yield


@pytest.fixture
def image_manifest():
    # An independent Presentation 3 image fixture; it is not produced by the generator.
    return {'@context': 'http://iiif.io/api/presentation/3/context.json',
            'id': 'https://example.org/manifest', 'type': 'Manifest', 'label': {'en': ['Image']},
            'items': [{'id': 'https://example.org/canvas/1', 'type': 'Canvas', 'width': 800, 'height': 600,
                       'items': [{'id': 'https://example.org/page/1', 'type': 'AnnotationPage',
                                  'items': [{'id': 'https://example.org/annotation/1', 'type': 'Annotation',
                                             'motivation': 'painting', 'target': 'https://example.org/canvas/1',
                                             'body': {'id': 'https://example.org/photo.jpg', 'type': 'Image',
                                                      'format': 'image/jpeg', 'width': 800, 'height': 600}}]}]}]}


def test_independent_image_manifest_passes(image_manifest):
    assert IiifService().validate_iiif_manifest(json.dumps(image_manifest))['valid']


@pytest.mark.parametrize('mutation, expected', [
    (lambda m: m['items'][0].pop('width'), 'width'),
    (lambda m: m['items'][0].update(height=0), 'height'),
    (lambda m: m['items'][0].update(width=True), 'width'),
    (lambda m: m['items'][0].update(width=10 ** 1000), 'width'),
    (lambda m: m['items'][0]['items'][0]['items'][0].update(target='https://example.org/wrong'), 'target'),
    (lambda m: m['items'][0]['items'][0]['items'][0]['body'].update(type='Model'), 'compatible'),
    (lambda m: m.update(id='file:///private/manifest'), 'HTTP(S)'),
    (lambda m: m.update(label={'en': ['']}), 'language map'),
])
def test_invalid_media_manifest_is_rejected(image_manifest, mutation, expected):
    mutation(image_manifest)
    report = IiifService().validate_iiif_manifest(json.dumps(image_manifest))
    assert not report['valid']
    assert any(expected in error for error in report['errors'])


@pytest.mark.parametrize('nested', ['canvas', 'page', 'annotation', 'body'])
def test_validation_checks_later_entries(image_manifest, nested):
    canvas = image_manifest['items'][0]
    page = canvas['items'][0]
    annotation = page['items'][0]
    if nested == 'canvas':
        bad = copy.deepcopy(canvas); bad.update(id='https://example.org/canvas/2', width=-1)
        image_manifest['items'].append(bad)
    elif nested == 'page':
        bad = copy.deepcopy(page); bad.update(type='WrongPage')
        canvas['items'].append(bad)
    elif nested == 'annotation':
        bad = copy.deepcopy(annotation); bad.update(id='https://example.org/annotation/2', target='https://example.org/wrong')
        page['items'].append(bad)
    else:
        annotation['body'] = [annotation['body'], {'id': 'https://example.org/audio.wav', 'type': 'Model', 'format': 'audio/wav'}]
    assert not IiifService().validate_iiif_manifest(json.dumps(image_manifest))['valid']


@pytest.mark.parametrize('filename, kind, painted', [('model.glb', 'Model', True), ('photo.jpg', 'Image', True),
                                                    ('audio.wav', 'Sound', False), ('film.mp4', 'Video', False),
                                                    ('scan.pdf', 'Text', False), ('notes.doc', 'Text', False), ('notes.docx', 'Text', False)])
def test_generation_respects_media_without_inventing_duration(filename, kind, painted):
    service = IiifService()
    content = service._ensure_minimum_viable_iiif('{}', {'title': 'Source'},
               {'id': 123, 'links': {'html': 'https://zenodo.org/records/123'}, 'files': [{'key': filename}]})
    manifest = json.loads(content)
    canvas = manifest['items'][0]
    assert service.validate_iiif_manifest(content)['valid']
    if painted:
        assert canvas['items'][0]['items'][0]['body'][0]['type'] == kind
    else:
        assert canvas['rendering'][0]['type'] == kind
        assert 'duration' not in canvas


def test_audio_with_duration_is_painted_and_invalid_duration_is_rejected():
    service = IiifService()
    record = {'id': 123, 'links': {'html': 'https://zenodo.org/records/123'}, 'files': [{'key': 'oral.wav'}]}
    content = service._ensure_minimum_viable_iiif('{}', {'title': 'Oral history', 'iiif_duration': 12.5}, record)
    canvas = json.loads(content)['items'][0]
    assert canvas['duration'] == 12.5
    assert canvas['items'][0]['items'][0]['body'][0]['type'] == 'Sound'
    assert service.validate_iiif_manifest(content)['valid']
    for value in (0, -1, True, float('nan'), 'unknown'):
        with pytest.raises(ValueError, match='duration'):
            service._ensure_minimum_viable_iiif('{}', {'iiif_duration': value}, record)


@pytest.mark.parametrize('field, value', [('iiif_translate_x', 'unknown'), ('iiif_point_z', float('inf')),
                                          ('iiif_rotate_y', True), ('iiif_scale_x', 0)])
def test_model_placement_rejects_invalid_values(field, value):
    with pytest.raises(ValueError, match='IIIF'):
        IiifService()._ensure_minimum_viable_iiif('{}', {field: value},
              {'id': 123, 'files': [{'key': 'model.glb'}]})


def test_non_model_media_ignores_legacy_model_placement():
    service = IiifService()
    content = service._ensure_minimum_viable_iiif('{}', {'iiif_translate_x': 'unknown', 'iiif_point_z': 8},
                  {'id': 123, 'files': [{'key': 'image.jpg'}]})
    annotation = json.loads(content)['items'][0]['items'][0]['items'][0]
    assert annotation['body'][0]['type'] == 'Image'
    assert 'transform' not in annotation['body'][0]
    assert isinstance(annotation['target'][0], str)
    assert service.validate_iiif_manifest(content)['valid']
