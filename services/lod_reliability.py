"""Shared safeguards for public metadata artifacts and reproducible generation."""
import ipaddress
import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

FORMATS = ('edm', 'iiif', 'mets', 'cidoc_crm', 'jsonld')
_templates = ContextVar('lod_templates', default=None)
_SECRET_QUERY = re.compile(r'token|secret|signature|credential|password|api.?key|authorization', re.I)


def public_url(value):
    """Reject authenticated or local URLs; never log their contents."""
    try:
        url = urlsplit(str(value).strip())
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
            return False
        if any(_SECRET_QUERY.search(key) for key, _ in parse_qsl(url.query)):
            return False
        if url.hostname == 'localhost':
            return False
        try:
            if not ipaddress.ip_address(url.hostname).is_global:
                return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False


def assert_public_document(content):
    text = html.unescape(str(content)).replace('\\/', '/')
    for match in re.finditer(r'(?:https?://|file://)[^\s<>"\']+', text, re.I):
        if not public_url(match.group()):
            raise ValueError('Generated metadata contains a private or credential-bearing URL. Use a public record or asset URL.')


def digest(content):
    return hashlib.sha256(content.encode('utf-8') if isinstance(content, str) else content).hexdigest()


def atomic_write(path, content):
    """Leave an existing artifact intact if writing its replacement fails."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.lod-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def resolve_template(standard, template_id=None):
    from database.database import db
    from database.models import LodTemplate
    snapshot = _templates.get()
    if snapshot is not None:
        template = snapshot.get(standard)
        if not template or (template_id and str(template['id']) != str(template_id)):
            raise ValueError(f'The pinned {standard.upper()} template is unavailable')
        return SimpleNamespace(**template)
    template = db.session.get(LodTemplate, template_id) if template_id else LodTemplate.query.filter_by(standard=standard, is_default=True).first() or LodTemplate.query.filter_by(standard=standard).first()
    if not template or getattr(template.standard, 'value', template.standard) != standard:
        raise ValueError(f'Choose an existing {standard.upper()} template')
    return template


def snapshot_templates(metadata, *, bootstrap=True, allow_missing=False):
    from database.lod_template_bootstrap import ensure_default_lod_templates
    if bootstrap:
        ensure_default_lod_templates()
    result = {}
    for standard in ('edm', 'iiif', 'mets'):
        try:
            template = resolve_template(standard, metadata.get(f'{standard}_template_id'))
        except ValueError:
            if allow_missing:
                continue
            raise
        result[standard] = {key: getattr(template, key) for key in ('id', 'name', 'content')}
        result[standard]['standard'] = standard
        result[standard]['sha256'] = digest(template.content)
    return result


@contextmanager
def pinned_templates(snapshot):
    token = _templates.set(snapshot)
    try:
        yield
    finally:
        _templates.reset(token)


def source_identity(value):
    return unicodedata.normalize('NFC', str(value).strip().replace('\\', '/')).removeprefix('./')


class MetadataRows:
    """Exact paths first; basename and case folding only when unambiguous."""
    def __init__(self, rows, source_paths):
        self.rows = {}
        self.sources = list(dict.fromkeys(source_identity(p) for p in source_paths))
        for path, row in rows:
            key = source_identity(path)
            if not key or key.lower() == 'nan':
                continue
            if key in self.rows:
                raise ValueError(f'Duplicate metadata row for {key}. Each source needs one row.')
            self.rows[key] = row

    def get(self, path, default=None):
        key = source_identity(path)
        if key in self.rows:
            return self.rows[key]
        matches = [p for p in self.rows if p.casefold() == key.casefold()]
        sources = [p for p in self.sources if p.casefold() == key.casefold()]
        if len(matches) == 1 and len(sources) <= 1:
            return self.rows[matches[0]]
        basename = key.rsplit('/', 1)[-1].casefold()
        matches = [p for p in self.rows if p.rsplit('/', 1)[-1].casefold() == basename]
        sources = [p for p in self.sources if p.rsplit('/', 1)[-1].casefold() == basename]
        if len(matches) == 1 and len(sources) <= 1:
            return self.rows[matches[0]]
        if matches:
            raise ValueError(f'Ambiguous metadata for {key}. Use the exact relative source path in the MSF.')
        return default

    def keys(self):
        return self.rows.keys()

    def __len__(self):
        return len(self.rows)


def capture_session_lod(session_id, *, bootstrap_templates=True, allow_missing_templates=False):
    from database.models import UserMetadata, BatchFileMetadata, Session
    from database.database import db
    fields = {}
    for row in UserMetadata.query.filter_by(session_id=session_id).order_by(UserMetadata.id).all():
        if row.field_name in ('zenodo_metadata_draft', 'msf_profile'):
            fields[row.field_name] = json.loads(row.field_value or '{}')
    metadata = fields.get('zenodo_metadata_draft', {})
    profile = fields.get('msf_profile', {})
    msf_path = metadata.get('msf_path') or profile.get('file_path')
    session = db.session.get(Session, session_id)
    if session and session.hdpc_path:
        from services.submission_pipeline_service import _resolve_lod_msf_candidates
        msf_path = next((path for path in _resolve_lod_msf_candidates(session.hdpc_path, msf_path) if os.path.isfile(path)), None)
    if msf_path and session and not session_metadata_path(msf_path, session):
        raise ValueError('The metadata source must be inside the authorized session')
    msf_hash = None
    if isinstance(msf_path, str) and os.path.isfile(msf_path):
        with open(msf_path, 'rb') as stream:
            msf_hash = digest(stream.read())
    return {'metadata': metadata, 'profile': profile, 'msf_sha256': msf_hash, 'templates': snapshot_templates(metadata, bootstrap=bootstrap_templates, allow_missing=allow_missing_templates),
            'batch': {row.filename: json.loads(row.metadata_json) for row in BatchFileMetadata.query.filter_by(session_id=session_id).all()}}


def normalize_record(record):
    """Provide optional Zenodo containers without inventing identifiers."""
    record = dict(record or {})
    metadata = dict(record.get('metadata') or {})
    metadata['prereserve_doi'] = dict(metadata.get('prereserve_doi') or {})
    record['metadata'] = metadata
    record['links'] = dict(record.get('links') or {})
    from services.edm_service import EdmService
    record['links']['html'] = EdmService().get_record_html_url(record)
    return record


def session_metadata_path(path, session):
    """Resolve only files contained in the authorized session, including symlinks."""
    if not path or session is None or not os.path.isfile(path):
        return None
    resolved = os.path.realpath(path)
    roots = [getattr(session, 'session_dir', None), os.path.dirname(getattr(session, 'hdpc_path', None) or '')]
    for root in roots:
        if root and os.path.commonpath([resolved, os.path.realpath(root)]) == os.path.realpath(root):
            return resolved
    return None
