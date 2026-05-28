# Public, Docs, And Profiles Workflows

This document covers workflows that expose documentation, public record
presentation, legal/static pages, and internal profile pages.

## Overview

These workflows are the low-friction reading and sharing surfaces in WebHDP.
They cover the documentation center, public/legal pages, public record pages,
embed/oEmbed behavior, and profile lookup. Most readers can skim the first
sections to understand the public experience; maintainers can use the lower
sections for routing, visibility, and presentation optimization.

## Use Cases

- Maintain public pages, legal pages, docs browsing, and documentation assets.
- Present public records through pages, embeds, and oEmbed responses.
- Diagnose profile visibility for users and institutions.
- Find public-read code paths that must keep working without authentication.

## Documentation Center

Primary actor: any user who needs guidance.

Entry points:
- UI: `/docs`
- UI: `/docs/:docId`
- API: `/api/v1/docs/index`
- API: `/api/v1/docs/content/<doc_id>`
- API: `/api/v1/docs/assets/<path:asset_path>`

Workflow:
1. Open the documentation center.
2. Browse the generated document index.
3. Open an individual document.
4. Load documentation assets such as videos or images.

Complete when:
- The target document content and any needed assets are visible.

## Static Public Information

Primary actor: public visitor.

Entry points:
- UI: `/`
- UI: `/credits`
- UI: `/impressum`
- UI: `/privacy`
- UI: `/cookies`

Workflow:
1. Open the public landing page or legal/static page.
2. Review credits, legal notice, privacy policy, or cookie policy.

Complete when:
- The public information page renders without requiring authentication.

## Public Record Presentation

Primary actor: public viewer, presenter, or embedding site.

Entry points:
- UI: `/p/records/:environment/:zenodoRecordId`
- UI: `/embed/records/:environment/:zenodoRecordId`
- API: `/api/v1/public/records/<environment>/<zenodo_record_id>`
- API: `/api/v1/oembed?url=<public_record_url>&format=json`

Workflow:
1. Resolve a public Zenodo record by environment and record ID.
2. Build a public record payload from Zenodo metadata.
3. Render the full public page or iframe-safe embed page.
4. For external platforms, request oEmbed JSON for the public record URL.

Complete when:
- The record page or embed exposes stable metadata, media, identifiers, credits, and fallbacks.
- The oEmbed response returns a valid rich response for supported records.

## Internal User And Institution Profiles

Primary actor: authenticated user, moderator, or administrator.

Entry points:
- UI: `/profiles/users/:identifier`
- UI: `/profiles/institutions/:identifier`
- API: `/api/v1/profiles/users/<identifier>`
- API: `/api/v1/profiles/institutions/<identifier>`

Workflow:
1. Open a user or institution profile by public ID or slug.
2. Apply profile visibility rules.
3. Show public/internal fields to normal users.
4. Show private fields only to users with moderator or admin access.

Complete when:
- The profile resolves and only permitted fields are visible.

## Prerequisites And Permissions

- Documentation, legal, public record, embed, and oEmbed workflows are public unless the backing content is unavailable.
- User and institution profile workflows require authentication for internal fields.
- Moderator or administrator access may reveal additional profile fields.
- Public record presentation requires resolvable Zenodo environment and record ID.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Documentation doc ID or asset path | Markdown content or asset response | docs catalog entry, file path, asset existence |
| Public static route | Rendered public or legal page | frontend route and public-route metadata |
| Zenodo environment and record ID | Public page, embed page, or oEmbed JSON | record metadata, media fallback, oEmbed URL |
| User or institution identifier | Profile payload | visibility flags, role-based field filtering |

## Failure And Recovery

- Missing documentation content should be fixed through the docs catalog or file path.
- Public record failures should distinguish missing Zenodo data from presentation fallback issues.
- oEmbed failures should verify the supplied public record URL and supported format.
- Profile visibility bugs should be checked against role, ownership, and public-field rules.

## Optimization Targets

- Keep docs index and content lookup fast as documentation grows.
- Avoid redundant public record metadata fetches for page and embed rendering.
- Keep oEmbed responses small and stable for external platforms.
- Make profile lookups efficient by public ID, slug, or identifier.

## Verification Checklist

- Verify docs index, doc content, and doc asset retrieval.
- Verify landing, credits, impressum, privacy, and cookie pages.
- Verify public record, embed record, and oEmbed responses.
- Verify user and institution profile visibility for normal, moderator, and admin users.

Related docs:
- `docs/guides/video_guides/public_records_and_operations.md`
- `docs/guides/video_guides/release_walkthroughs.md`

## Codebase Starting Points

- Public and legal views: `frontend/src/views/public/`, `frontend/src/views/legal/`
- Docs frontend: `frontend/src/views/docs/DocumentationHubView.vue`
- Docs routes and catalog: `routes/docs_routes.py`
- Public record routes: `routes/public_routes.py`
- Profile routes: `routes/profile_routes.py`
- Frontend routing: `frontend/src/router/index.js`
- Documentation files and assets: `docs/`
