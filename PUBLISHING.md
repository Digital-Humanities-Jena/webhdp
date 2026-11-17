# Publishing WebHDP

[WebHDP on GitHub](https://github.com/Digital-Humanities-Jena/webhdp) is the
canonical public repository. Publishing a commit and tag does not deploy
WebHDP. Use the [deployment guide](docs/docker_deployment_guide.md) and the
[alpha.3 upgrade checklist](docs/guides/upgrade_alpha3.md) for that separate
operation.

## Review the release tree

1. Review the changes since the remote branch, including already committed but
   unpublished changes. Stage the intended files explicitly and inspect the
   staged diff, binary assets and commit messages. Scan all objects introduced
   by the push for secrets, including files removed in later commits.
2. Keep real credentials, host configuration, model weights, private
   datasets, test databases and scheduler/Zenodo receipts out of the public
   history. Check screenshots and recordings for embedded account identifiers,
   secrets and research data. Publish only cleared fixtures and media.
3. Check the European Union Public Licence v. 1.2 or later and the applicable
   [third-party notices](THIRD_PARTY_NOTICES.md). Review the redistribution
   terms for each bundled runtime, model, schema, asset and excerpt.
4. Match the release notes, citation, Python and frontend versions, lockfiles,
   runtime version and Compose defaults with the intended tag. Regenerate
   the API references after route or schema changes. Update the
   [documentation index](docs/README.md) for changed operator/user workflows.

## Verify

From the repository root:

```sh
uv sync --group dev
uv run pytest
uv run python scripts/check_openapi_fresh.py
make compose-check release-assets-check hpc-link-test devcontainer-check
```

Then run frontend and gateway checks:

```sh
(cd frontend && npm ci && npm run test:unit && npm run build && npm run test:e2e && npm audit --omit=dev --audit-level=moderate)
(cd hpc-link/frontend && npm ci && npm run lint && npm run build && npm audit --omit=dev --audit-level=moderate)
```

`scripts/release_check.sh` provides the combined check. The extended checks
require Docker, Playwright browsers, and a correctly configured isolated
runtime:

```sh
RUN_E2E=true RUN_DEVCONTAINER=true VERIFY_LOCAL_EDM_VALIDATOR=true \
  CHECK_RELEASE_IMAGES=true ./scripts/release_check.sh
```

Record whether optional runtimes passed real execution or only unit, manifest
or preflight checks. A GPU application needs a separate test of the pinned SIF,
HPC-Link runner, input staging and artifact downloads on its target cluster.
WebHDP-Link needs its worker and proxy checked end to end. Neither check should
use production credentials or publish test data. Review dependency audit
findings before making compatibility changes or publishing an affected build.

## Publish the verified commit

Check access and the target branch's protection rules. Create an annotated tag
on the verified commit after the checks pass. For the canonical GitHub remote
named `origin`, when direct pushes to `main` are allowed:

```sh
git tag -a v0.1.0-alpha.3 -m 'WebHDP v0.1.0-alpha.3'
git push --atomic origin HEAD:refs/heads/main refs/tags/v0.1.0-alpha.3
```

Use the repository's protected branch workflow if direct push is disallowed.
Tag the verified merged commit there. Confirm the remote branch and tag point
to the intended commit and read the CI results. Publish to any mirrors only
under that mirror's release policy.
