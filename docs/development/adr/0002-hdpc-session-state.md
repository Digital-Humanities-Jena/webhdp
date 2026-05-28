# ADR 0002: `.hdpc` Session Project State

Status: Accepted

## Context

WebHDP needs reproducible session-level project state that can be inspected, exported, shared, retrieved from Zenodo, and used by native pipeline services. Keeping all processing state only in the application database would make session portability and HDP-side record lifecycle harder.

## Decision

WebHDP treats `.hdpc` SQLite files as canonical session project state for local project records, source-file metadata, record lifecycle data, and native pipeline execution context. The application database stores WebHDP platform state such as users, sessions, submissions, credentials, reviews, notifications, and configuration.

The `.hdpc` format is versioned separately from the app database. Its canonical schema contract is documented in `../../architecture/hdpc_schema.md`.

## Consequences

- Contributors must identify whether new state belongs in the app DB or `.hdpc` before implementation.
- `.hdpc` schema changes need explicit compatibility and migration thinking.
- App DB migrations do not replace `.hdpc` schema migration rules.
- Features that export, import, retrieve, compact, or share sessions must respect `.hdpc` boundaries and provenance.
