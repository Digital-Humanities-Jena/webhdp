"""Describe semantic additions and changes made to generated metadata."""
import json
from lxml import etree


def document_adjustments(before, after, standard):
    def fields(content):
        if standard == 'iiif':
            values = {}
            def visit(value, path):
                if isinstance(value, dict):
                    for key, item in value.items():
                        visit(item, f'{path}.{key}' if path else key)
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        visit(item, f'{path}[{index}]')
                else:
                    values[path] = value
            visit(json.loads(content), '')
            return values
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        root = etree.fromstring(content.encode('utf-8'), parser)
        values = {}
        def visit(element, path):
            name = str(etree.QName(element))
            current = f'{path}/{name}'
            if element.text and element.text.strip():
                values[current] = element.text.strip()
            for key, value in element.attrib.items():
                values[f'{current}/@{etree.QName(key)}'] = value
            if element.tail and element.tail.strip():
                values[f'{current}/tail'] = element.tail.strip()
            counts = {}
            for child in element:
                if not isinstance(child.tag, str):
                    continue
                tag = str(etree.QName(child))
                counts[tag] = counts.get(tag, 0) + 1
                visit(child, f'{current}[{tag}:{counts[tag]}]')
        visit(root, '')
        return values
    try:
        original, final = fields(before), fields(after)
        missing = object()
        changes = [{'field': key, 'value': value, 'source': 'generated',
                 'action': 'added' if key not in original else 'changed'}
                for key, value in final.items() if original.get(key, missing) != value]
        changes.extend({'field': key, 'source': 'generated', 'action': 'removed'} for key in original if key not in final)
        return changes
    except (ValueError, TypeError, etree.XMLSyntaxError):
        return [{'field': 'document', 'source': 'generated', 'action': 'rebuilt'}]
