# Golden Sample Workflow

The golden workflow is a small, local-only confidence check for new developers. It proves that the repository can scan a curated fixture set, create a temporary `.hdpc` project, inspect the resulting records, and match the primary files against a minimal MSF.

It does not call Zenodo, Redis, Celery workers, the renderer, USDZ conversion, cloud storage, or the local EDM validator. That makes it safe to run during onboarding and in CI.

## Run It

```bash
make golden-workflow
```

Expected result:

```text
Golden workflow completed successfully.
- Case: root_stem_mixed
- Records: 3
- Primary files: bronze_helmet.glb, ceramic_bowl.fbx, temple_column.obj
- MSF matched golden files: 3
```

## Keep Generated Artifacts

By default the workflow uses a temporary directory and deletes it after success. To inspect the generated `.hdpc` file and output directory:

```bash
uv run python scripts/run_golden_workflow.py --output-dir /tmp/webhdp-golden
```

## What It Checks

- The curated fixture manifest can be loaded from `test_data/workflow_fixtures/manifest.json`.
- The `root_stem_mixed` fixture scans successfully.
- The scan creates exactly three primary records:
  - `bronze_helmet.glb`
  - `ceramic_bowl.fbx`
  - `temple_column.obj`
- OBJ sidecars remain bundled according to the manifest contract.
- The minimal MSF at `test_data/workflow_fixtures/msf/workflow_minimal.csv` matches the three golden primary files.

## When To Run It

Run the golden workflow:

- after initial setup
- after changing scan, `.hdpc`, MSF, or fixture code
- before asking for help with local workflow setup
- when reviewing onboarding-related changes

`make verify-onboarding` also runs this workflow.

## If It Fails

Start with:

```bash
uv run python scripts/run_golden_workflow.py --json
uv run pytest tests/test_golden_workflow.py -q
```

Common causes:

- fixture files were moved without updating `manifest.json`
- scanner behavior changed without updating fixture expectations
- MSF filename detection changed
- `.hdpc` project creation or inspection regressed
