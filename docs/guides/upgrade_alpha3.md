# Upgrade WebHDP to v0.1.0-alpha.3

This guide is for operators upgrading an existing deployment. If you are
starting from an empty database, follow the [Docker Quickstart](docker_quickstart.md)
first. Deploying an alpha build to a public site requires rehearsing the upgrade
and intended workflows on a staging instance with its own data and credentials.
Publishing the repository version does not change a running deployment.

## Choose what to enable

| Feature | What an operator needs |
| --- | --- |
| Native submission, retry and result review | Matching backend, frontend and Celery worker. Check any interrupted runs and ambiguous Zenodo operations before retrying. |
| Historic, Zenodo community and HMSM processing | Install the required component versions and locally available immutable Docker images or verified SIFs. Catalog entries do not install these runtimes. |
| GPU reservation sharing | Updated private HPC-Link gateway and component runner; a running single-node GPU job whose Slurm owner is the configured gateway account; one registration and named WebHDP grants. |
| WebHDP-Link | Private shared storage, a separate supervised worker, publications with pinned native versions, and applications registered with exact origins and callbacks. |

Local Docker gives the backend access to the Docker daemon. Enable this feature
only on a trusted host and install reviewed runtimes. The public demo does not
need a Docker socket on the WebHDP server when the verified components run on HPC.

## Prepare and migrate

1. Record the existing release image digests and current Alembic revision.
   Record the locations of the database, session files, private Link data if
   present, encryption keys and HPC-Link state. Make a consistent backup of
   all of them. Rehearse restore with the existing version using the
   [restore drill checklist](restore_drill_checklist.md). Keep credentials
   separate from the review record and check ownership of restored files.
   Production requires a random `SECRET_KEY` of at least 32 bytes for HS256
   JWT signing and a separate `CREDENTIAL_ENCRYPTION_KEY`. A signing-key
   rotation invalidates existing sessions; changing the encryption key without
   migrating stored credentials can make them unreadable. Decide and test
   those rotations separately from the schema upgrade.
2. Build or obtain matching images from the reviewed release. Also update
   HPC-Link and its remote runner if using reservations or updated HPC
   components. Keep the gateway registry on a private writable volume and
   preserve its existing state. New installations and upgrades must both use
   the target backend, frontend and worker builds together.
3. Run the upgrade first against the restored staging copy. In the deployment,
   gate new submissions and let active jobs drain before stopping writers.
   Check the native, Celery and Link queues individually. If Link is enabled,
   follow its [drain procedure](webhdp_link_deployment.md#authorized-rollout-and-recovery-sequence);
   disabling a client or publication can withdraw authorization from active
   jobs. An independently held GPU job can stay running while WebHDP is down.
4. With writers stopped, apply migrations once using the reviewed backend
   image, database URL and persistent mounts. For the base production stack:

   ```sh
   docker compose -f docker-compose.prod.yml run --rm --no-deps \
     -e RUN_DB_BOOTSTRAP=0 -e SKIP_DB_CREATE_ALL=1 \
     backend python -m flask --app app db upgrade
   docker compose -f docker-compose.prod.yml run --rm --no-deps \
     -e RUN_DB_BOOTSTRAP=0 -e SKIP_DB_CREATE_ALL=1 \
     backend python -m flask --app app db current
   ```

   Use the same Compose overlay and private configuration as the target
   deployment when those affect the image or database. Upgrade to the single
   release head `d9e0f1a2b345`. Revision `e1f0a2b3c456` adds GPU reservations
   and grants after `c8d9e0f12345`; `d9e0f1a2b345` adds Link tables after it.
   Do not stamp a database that lacks these schema changes or fall back to
   creating tables on import. If a development database already reports the
   Link revision from an earlier branch, verify the reservation tables
   separately before treating it as upgraded.
5. Start the API, frontend and ordinary worker with the migrated database,
   then start the optional Link worker. Leave external clients disabled until
   the staging and HTTPS checks pass.

## Verify the workflows you rely on

- Sign in using a verified ordinary account. Upload a small rights-cleared
  fixture, check readiness and selected files, execute a native pipeline, and
  download its files and reports. Confirm a failure can be reviewed and
  continued without replacing already successful artifacts.
- Check a saved pipeline version against the installed component checksums.
  [Historic reconstruction](historic_reconstruction.md),
  [Zenodo community components](zenodo_community_components.md), and
  [HMSM Studio components](hmsm_components.md) each have installation and test
  instructions. Reuse the validated version or save a new one when the runtime
  bytes or input contract change.
- Rehearse the [reserved GPU workflow](prereserved_gpu_demo.md) through the
  deployment's proxy, worker, VPN and gateway. Verify account and session
  boundaries, component GPU use and artifact hashes. Confirm that release
  detaches WebHDP access and leaves the Slurm job running.
- For Link, [check the actual HTTPS flow](webhdp_link_deployment.md#https-and-proxy-gate)
  with a narrowly scoped test client. Include a denied origin, authorization,
  upload, status, download, token expiry and reconnection. Verify the worker
  processes a real job and monitor queue age and disk space. Leave production
  publication disabled unless it has been approved and rehearsed separately.

## Recover an unsuccessful upgrade

Gate new work and stop writers. Prefer restoring or reverting app images
according to the plan verified in staging. Reverting only images is safe only
if the earlier version was tested against the upgraded schema. Downgrading
either new migration deletes its tables. If you restore from backup, restore
the matched version, database, session and Link files, and preserve encryption
keys. Handle gateway claims and Zenodo drafts created after the backup
separately: restoring the database does not undo those external effects.
