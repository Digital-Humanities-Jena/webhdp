# Publishing WebHDP on GitHub and Codeberg

This directory has been prepared as a source repository for both GitHub and Codeberg.

## Before Publishing

1. Confirm the project license.
   - The repository is licensed under the European Union Public Licence v. 1.2 or later (`EUPL-1.2`).
   - Third-party dependencies, bundled documentation excerpts, and external tools retain their own licenses.
2. Review `.env.example` and keep real secrets only in local `.env` or deployment secret stores.
3. Confirm large binary datasets, reports, raw production exports, scratch tests, and local run outputs are excluded. Curated in-app documentation videos are allowed only when `make release-assets-check` passes; larger recordings should move to release artifacts / Git LFS storage.
4. Confirm no credential-looking files are staged or present in the release tree. The local file
   `hdp-3drepo-credentials.txt` is explicitly ignored and must not be published.
5. Confirm release metadata is current:
   - `RELEASE_NOTES.md`
   - `THIRD_PARTY_NOTICES.md`
   - `CITATION.cff`
   - `docs/README.md`, `docs/guides/docker_quickstart.md`, and `docs/guides/planned_future_updates.md`
   - `version.json`, `pyproject.toml`, frontend package versions, and Docker image tags
6. Confirm the public release boundary:
   - Core publication pipelines are `render` and `metadata_only`. The separately installed `mesh_optimization` and `model_georeferencing` pipelines have validated HPC workflows; see their component validation reports for supported inputs and limitations.
   - Other optional components and deployment profiles require their own acceptance checks before being enabled.
   - Do not deploy, sync, or run release preparation on HPC as part of repository publishing.
7. Run:
   - `make compose-check`
   - `make release-assets-check`
   - `uv sync --group dev && uv run pytest`
   - `uv run python scripts/check_openapi_fresh.py`
   - `cd frontend && npm ci && npm run test:unit && npm run build && npm run test:e2e && npm audit --omit=dev --audit-level=moderate`
   - `make hpc-link-test`
   - `cd hpc-link/frontend && npm ci && npm run lint && npm run build && npm audit --omit=dev --audit-level=moderate`
   - `make devcontainer-check`
   - `RUN_E2E=true RUN_DEVCONTAINER=true VERIFY_LOCAL_EDM_VALIDATOR=true CHECK_RELEASE_IMAGES=true ./scripts/release_check.sh`

Do not use `git add .` for the first public commit. Stage only the curated release tree and verify `git status --short --ignored` before committing.

Do not use `npm audit fix --force` to clear audit findings unless the resulting dependency changes pass
documentation/rendering regression tests.

## Suggested Git Remotes

```bash
git remote add github git@github.com:Digital-Humanities-Jena/webhdp.git
git remote add codeberg git@codeberg.org:<owner>/<repo>.git
git push github main
git push codeberg main
git tag -a v0.1.0-alpha.2 -m "WebHDP v0.1.0-alpha.2"
git push github v0.1.0-alpha.2
git push codeberg v0.1.0-alpha.2
```

After pushing, confirm GitHub Actions and Codeberg/Woodpecker checks pass on the published commit.

The canonical public GitHub URL for release metadata is:

`https://github.com/Digital-Humanities-Jena/webhdp`

## Platform Notes

- GitHub CI workflow is in `.github/workflows/ci.yml`.
- Codeberg can use the included `.woodpecker.yml` when Woodpecker CI is enabled for the repository.
- If Git LFS is later used for sample models or videos, initialize LFS before adding those files:

```bash
git lfs install
git lfs track "*.glb" "*.fbx" "*.obj" "*.mp4" "*.mov" "*.zip"
```

## Deployment Notes

For production deployment, set at least:

- `SECRET_KEY`
- `CREDENTIAL_ENCRYPTION_KEY`
- `SETUP_BOOTSTRAP_TOKEN` or `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD`
- `OEMBED_FRAME_ANCESTORS` with explicit trusted origins if public embeds are enabled
- Zenodo, mail, storage, and HPC settings relevant to the deployment

SQLite is the default database for the first low-user deployment. Move to Postgres if you see repeated
`database is locked` errors, need multiple backend/worker replicas, need high write concurrency, require HA, or must
place the database on network storage.

Then deploy with:

```bash
docker compose up -d --build
```
