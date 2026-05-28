from routes.docs_routes import (
    DOCS_CATALOG,
    VALID_DOC_AUDIENCES,
    VALID_DOC_CATEGORIES,
    _resolve_catalog_path,
)


def test_docs_catalog_ids_paths_and_taxonomy_are_valid():
    ids = [entry.doc_id for entry in DOCS_CATALOG]

    assert len(ids) == len(set(ids))

    for entry in DOCS_CATALOG:
        assert entry.audience in VALID_DOC_AUDIENCES
        assert entry.category in VALID_DOC_CATEGORIES
        assert _resolve_catalog_path(entry) is not None


def test_account_security_docs_are_discoverable():
    entries = {entry.doc_id: entry for entry in DOCS_CATALOG}

    assert entries["workflows"].category == "workflows"
    assert entries["workflows"].audience == "all"
    assert entries["zenodo-api-keys"].category == "account-security"
    assert entries["zenodo-api-keys"].audience == "user"
    assert entries["security-and-credentials"].category == "account-security"
    assert entries["zenodo-account-retrieval"].category == "workflows"


def test_portal_and_user_workflow_use_markdown_links_for_docs_pages():
    checked_paths = [
        _resolve_catalog_path(entries)
        for entries in DOCS_CATALOG
        if entries.doc_id in {"portal", "user-guide", "workflows"}
    ]

    for path in checked_paths:
        assert path is not None
        text = path.read_text(encoding="utf-8")
        assert "`glossary.md`" not in text
        assert "`troubleshooting.md`" not in text
        assert "`guides/end_to_end_user_guide.md`" not in text
