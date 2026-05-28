# Third-Party Notices

WebHDP itself is licensed under the European Union Public Licence v. 1.2 or later (`EUPL-1.2`). See `LICENSE`.

Third-party dependencies, standards documents, schemas, and external tools retain their own licenses and terms. This file records the release boundary for the public alpha repository.

## Runtime And Package Dependencies

Python, Node.js, Docker image, and system packages are resolved from their respective package registries or base images. Their license terms are not replaced by the WebHDP license. Lockfiles and manifests are included for reproducibility only.

## Local EDM Validator

The local EDM validator source is not vendored in this repository. WebHDP uses a pinned external checkout from:

`https://github.com/Digital-Humanities-Jena/local-edm-validator.git`

The setup script checks out the pinned commit configured in `.env.example` and applies WebHDP's tracked Docker build patch from `patches/local-edm-validator/`. The upstream validator retains its own license and release process.

## Standards And Reference Documentation

The public alpha repository links to external standards prose instead of vendoring full copies. See `docs/standards_links.md` for upstream EDM, IIIF, METS/MODS, and Zenodo documentation.

The `docs/metsmods/` and `schema_xsds/` materials are runtime validation schemas used to validate WebHDP output offline. They retain the terms of their upstream maintainers.

### Europeana EDM XSD Schemas

The `.xsd` files in `schema_xsds/` were sourced from Europeana's EDM resources repository:

`https://github.com/europeana/edm-resources/tree/main/xsd`

The upstream `europeana/edm-resources` repository is published under the European Union Public Licence v. 1.2 (`EUPL-1.2`). WebHDP preserves these files as validation/reference schemas; they remain attributable to Europeana and retain the upstream EUPL-1.2 terms.

### METS/MODS Schemas

The files in `docs/metsmods/` are retained because `services/mets_service.py` uses them for offline METS/MODS validation. The METS schema declares CC0 terms in its embedded documentation. MODS is maintained by the Library of Congress; WebHDP keeps the schema only as an offline validation input.

## HDP Components And External Services

The `external_code/` directory contains WebHDP component manifests and selected local component implementations used by the alpha release. Third-party runtimes such as Blender, Docker base images, validators, and conversion tools retain their own licenses.

For alpha, `fast-renderer` and `any-to-usdz` are first-class optional services because the supported `render` publication path can use them directly. Other HDP Components are installable/evaluation components unless separately released and validated.

## Fixtures

Root fixtures and `test_data/workflow_fixtures/` media-like files are synthetic generated/minimized WebHDP fixtures. They are intended for scanner, setup, and onboarding tests, not as cultural-heritage sample data.

## Documentation Media

`docs/assets/screen_recordings/` contains curated WebHDP walkthrough recordings referenced by the in-app documentation. `scripts/check_release_assets.py` enforces the alpha allow-list, file-size limit, and reference consistency. If a maintainer cannot confirm provenance for a recording, move it out of the source repository and publish it as an external release asset instead.
