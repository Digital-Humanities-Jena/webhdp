#!/usr/bin/env python3
"""Validate developer-facing documentation links and docs catalog entries."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = ROOT / "docs"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CHECKED_DOCS = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    DOCS_ROOT / "README.md",
    DOCS_ROOT / "guides" / "workflows.md",
    DOCS_ROOT / "guides" / "common-workflow-recipes.md",
    DOCS_ROOT / "development" / "onboarding.md",
    DOCS_ROOT / "development" / "devcontainer.md",
    DOCS_ROOT / "development" / "first_pr_walkthrough.md",
    DOCS_ROOT / "development" / "troubleshooting_decision_tree.md",
    DOCS_ROOT / "development" / "architecture_map.md",
    DOCS_ROOT / "development" / "developer_glossary.md",
    DOCS_ROOT / "development" / "pr_scope_examples.md",
    DOCS_ROOT / "development" / "known_warnings.md",
    DOCS_ROOT / "development" / "contributor_handbook.md",
    DOCS_ROOT / "development" / "examples.md",
    DOCS_ROOT / "development" / "first_hdp_component.md",
    DOCS_ROOT / "development" / "hdp_component_manifest_specification.md",
    DOCS_ROOT / "development" / "hdp_component_publishing_guide.md",
    DOCS_ROOT / "development" / "good_first_changes.md",
    DOCS_ROOT / "development" / "golden_workflow.md",
    DOCS_ROOT / "development" / "adr" / "README.md",
]

LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _iter_markdown_fences(text: str) -> list[tuple[str, int]]:
    stack: list[tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("````"):
            if stack and stack[-1][0] == "````":
                stack.pop()
            else:
                stack.append(("````", lineno))
        elif stripped.startswith("```"):
            if stack and stack[-1][0] == "```":
                stack.pop()
            else:
                stack.append(("```", lineno))
    return stack


def _resolve_path(reference: str, source: Path) -> Path | None:
    if not reference or reference.startswith(("http://", "https://", "mailto:", "#", "/api/")):
        return None
    target = reference.split("#", 1)[0].strip()
    if not target:
        return None
    if target.startswith("/"):
        return ROOT / target.lstrip("/")
    return (source.parent / target).resolve()


def _check_doc_file(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"Missing checked doc: {path.relative_to(ROOT)}"]

    text = path.read_text(encoding="utf-8")
    open_fences = _iter_markdown_fences(text)
    if open_fences:
        errors.append(f"{path.relative_to(ROOT)} has unclosed code fence(s): {open_fences}")

    references: set[str] = set()
    references.update(match.group(1) for match in LINK_PATTERN.finditer(text))

    for reference in sorted(references):
        resolved = _resolve_path(reference, path)
        if resolved is None:
            continue
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)} references missing path: {reference}")
    return errors


def _check_docs_catalog() -> list[str]:
    try:
        from routes.docs_routes import DOCS_CATALOG, _resolve_catalog_path
    except Exception as exc:
        return [f"Could not import docs catalog: {exc}"]

    ids = [entry.doc_id for entry in DOCS_CATALOG]
    duplicates = sorted({doc_id for doc_id in ids if ids.count(doc_id) > 1})
    missing = [(entry.doc_id, entry.rel_path) for entry in DOCS_CATALOG if _resolve_catalog_path(entry) is None]

    errors: list[str] = []
    if duplicates:
        errors.append(f"Duplicate docs catalog IDs: {duplicates}")
    if missing:
        errors.append(f"Docs catalog entries with missing files: {missing}")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in CHECKED_DOCS:
        errors.extend(_check_doc_file(path))
    errors.extend(_check_docs_catalog())

    if errors:
        for error in errors:
            print(f"[docs-check] {error}", file=sys.stderr)
        return 1

    print(f"Checked {len(CHECKED_DOCS)} developer docs and the in-app docs catalog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
