import json

from services.metadata_adjustments import document_adjustments


def test_xml_formatting_does_not_count_as_generated_adjustment():
    before = '<root xmlns="https://example.org"><label>Object</label></root>'
    after = '<root xmlns="https://example.org">\n  <label>Object</label>\n</root>'
    assert document_adjustments(before, after, 'edm') == []


def test_adjustments_include_changed_values_but_do_not_repeat_removed_content():
    before = json.dumps({'label': 'Old title', 'private_note': 'Do not repeat this'})
    after = json.dumps({'label': 'New title', 'width': 1000})
    changes = document_adjustments(before, after, 'iiif')
    assert {'field': 'label', 'value': 'New title', 'source': 'generated', 'action': 'changed'} in changes
    assert {'field': 'width', 'value': 1000, 'source': 'generated', 'action': 'added'} in changes
    assert {'field': 'private_note', 'source': 'generated', 'action': 'removed'} in changes
    assert 'Do not repeat this' not in json.dumps(changes)


def test_xml_adjustments_preserve_distinct_repeated_elements():
    changes = document_adjustments('<root><label>A</label></root>', '<root><label>A</label><label>B</label></root>', 'mets')
    assert len(changes) == 1
    assert changes[0]['value'] == 'B'
    assert 'label:2' in changes[0]['field']


def test_xml_namespaces_are_semantic_but_prefixes_are_not():
    before = '<root xmlns:a="https://example.org/one"><a:label>Object</a:label></root>'
    equivalent = '<root xmlns:b="https://example.org/one"><b:label>Object</b:label></root>'
    changed = '<root xmlns:a="https://example.org/two"><a:label>Object</a:label></root>'
    assert document_adjustments(before, equivalent, 'edm') == []
    assert {item['action'] for item in document_adjustments(before, changed, 'edm')} == {'added', 'removed'}
