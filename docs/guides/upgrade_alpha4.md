# Upgrade WebHDP to v0.1.0-alpha.4

This guide is for operators upgrading an existing deployment. If you are
starting from an empty database, follow the [Docker Quickstart](docker_quickstart.md)
first. Deploying an alpha build to a public site requires rehearsing the upgrade
and intended workflows on a staging instance with its own data and credentials.
Publishing the repository version does not change a running deployment.

## Choose what to enable

| Feature | What an operator needs |
| --- | --- |
| Native submission, retry and result review | Matching backend, frontend and Celery worker. Check any interrupted runs and ambiguous Zenodo operations before retrying. |
| Guided 3D practice and Sandbox drafts | A dedicated model publication worker sharing the API's instance directory. Sandbox deposit tests also need an authorized staging credential and the configured EDM validator must be reachable from the worker. |
| Historic, Zenodo community and HMSM processing | Retain installed versions and their pinned images. Use the Component Installer for new versions and follow the [component upgrade checks](hdp_component_hpc_installation.md#preserve-installations-during-a-webhdp-upgrade). |
| GPU reservation sharing | Updated private HPC-Link gateway and component runner; a running single-node GPU job whose Slurm owner is the configured gateway account; one registration and named WebHDP grants. |
| WebHDP-Link | Private shared storage, a separate supervised worker, publications with pinned native versions, and applications registered with exact origins and callbacks. |
| Registration and institution invitations | Working SMTP for the deployment, its HTTPS frontend URL, and controlled mailboxes for verification and acceptance tests. |
| Institution workspace approval | A verified site administrator to review requests and existing workspace roles. |

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
2. Build or obtain matching images from the reviewed release. Update HPC-Link
   before restarting the WebHDP API and queue worker if this instance uses
   HPC. Reconcile any
   [unconfirmed scheduler submissions](../workflows/hpc-cloud-storage.md#recover-an-unconfirmed-scheduler-submission)
   before changing gateways. Update the remote runner for updated HPC components.
   Keep the gateway registry on a private writable volume and
   preserve its existing state. Keep the HPC application root and installed
   component versions available at their existing paths. On a deployment
   using the core workflow profile, carry forward `WEBHDP_ENABLE_NATIVE_TOOLS`
   if signed-in users use Playground. Use the target backend, frontend and
   worker builds together.
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
   release head `b5c4d6e7f890`. Revision `e1f0a2b3c456` adds the GPU
   reservation tables after `c8d9e0f12345`. Revision `d9e0f1a2b345` adds
   Link, and `e2f1a3b4c567` adds account upload admission records. The
   identity revisions are `f3a2b4c5d678` for email verification,
   `a4b3c5d6e789` for invitations, and `b5c4d6e7f890` for workspace
   requests.
   Do not stamp a database that lacks these schema changes or fall back to
   creating tables on import. If a development database already reports the
   Link revision from an earlier branch, verify the reservation tables
   separately before treating it as upgraded.
5. Start the API, frontend, ordinary worker and `hpc-queue` with the migrated
   database. If you enable guided 3D publication, set `WEBHDP_INSTANCE_PATH` to
   the backend's persistent host directory and add
   `docker-compose.model-publication.yml`. Use the same backend image for the
   API and dedicated worker. If the validator runs in the same Compose project,
   set `LOCAL_EDM_VALIDATOR_URL=http://local-edm-validator:8080` in `.env` so the
   worker can reach it. Run the [validator setup and verification](local_edm_validator.md#managed-docker-compose-deployment)
   again so the checkout uses the matching schema, sorter and transformation.
   Start the optional Link worker when its proxy, secrets and storage are
   ready. Enable external clients after the staging and HTTPS checks pass.

## Verify account continuity

Keep the same application database bind mount and `DATABASE_URL` when replacing
the containers. WebHDP stores account records and their email verification state
in SQLite. Set `WEBHDP_INSTANCE_PATH` to the absolute path of the existing
instance directory if releases use separate checkout directories. Compose
mounts that directory into the backend and workers at `/app/instance`.
Authentication workers on the same host share throttle state in
`auth-throttle.sqlite3` beneath that private directory by default. Check
`AUTH_TRUSTED_PROXY_HOPS` against the deployed proxy chain.
[Operations guide](operations_and_setup_guide.md)

For an existing installation, run the following on the database host. Use the
file resolved from the running backend's mount and `DATABASE_URL`. Keep the
same private snapshot through the entire upgrade.

```sh
database_path=/absolute/path/to/instance/hdp_web.db
account_check_dir=$(mktemp -d)
python3 scripts/check_account_continuity.py capture --database "$database_path" \
  --snapshot "$account_check_dir/accounts.json"

# Check the migrated database before reopening traffic. Repeat after container
# recreation using the file resolved from the new backend's mount and DATABASE_URL.
python3 scripts/check_account_continuity.py verify --database "$database_path" \
  --snapshot "$account_check_dir/accounts.json"
```

The check accepts newly registered accounts and newly verified email addresses.
It fails when an existing account disappears, its role changes, or it loses
verification. If it fails, keep traffic gated and check the running database
mount before considering recovery from the verified backup. Sign in with an
ordinary account that existed before the release as a final HTTPS check. Remove
the private snapshot when the upgrade is accepted.

### Review registration and institutional access

- Already verified accounts keep their credentials and active memberships.
  The migration invalidates earlier verification links. Ask pending users to
  request a fresh link from the current registration page. Link confirmation
  requires them to choose a password. Review any retained legacy address
  collisions with account support and preserve associated work and ownership
  through the review.
- Examine workspaces and members created before the new approval policy.
  Check legacy Owners and Reader memberships against institutional approval
  records. Preserve the verified institutional owners and authorized members.
- Verify delivery with a staging mailbox. Complete a fresh email-first
  registration, test resend and a simulated SMTP outage, then sign in. Confirm
  reactivation of an older pending account uses a new link.
  [Registration and delivery checks](../workflows/access-setup-identity.md#verification-delivery-checks)
- On staging, request a new institution and approve it as a site administrator.
  Confirm that the requester owns the private workspace and management is
  available to administrators without a membership. Invite a new account and
  check that activation requires the verified recipient to accept. Exercise
  resend with SMTP loss and recovery, revocation, and the roster and audit
  privacy rules.
  [Institution workflows](../workflows/institutions-credentials-governance.md)
- Reopen **Account setup** from **Getting started** and **Account Configuration**.
  Check the key status for each environment, workspace discovery and request
  status, and invitation actions for a workspace manager. Confirm that a
  regular account can reach the tutorial and create a personal session when
  it has no Zenodo key or workspace. [Guided account setup](../workflows/access-setup-identity.md#guided-account-setup)

## Verify the workflows you rely on

- Sign in using a verified ordinary account. Upload a small rights-cleared
  fixture, check readiness and selected files, execute a native pipeline, and
  download its files and reports. Confirm a failure can be reviewed and
  continued without replacing already successful artifacts.
- Run the [CPU-only tutorial and Sandbox draft workflow](model_publication.md)
  through the staged HTTPS endpoint. Rehearse the repaired-texture sample and
  the three-model MSF sample. Download the resulting GLBs and metadata.
  Confirm that a second account sees only its own jobs and files and that
  queued or rejected requests leave both accounts' usage correct.
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
- Check **HPC access and allocations** with a permitted user. Watch requests
  move from queued to running, reconcile an interrupted scheduler response,
  and confirm that detaching or releasing returns allowance to the
  corresponding account. [HPC access and storage](../workflows/hpc-cloud-storage.md)
- For Link, [check the actual HTTPS flow](webhdp_link_deployment.md#https-and-proxy-gate)
  with a narrowly scoped test client. Include a denied origin, authorization,
  upload, status, download, token expiry and reconnection. Verify the worker
  processes a real job and monitor queue age and disk space. Leave production
  publication disabled unless it has been approved and rehearsed separately.

## Recover an unsuccessful upgrade

Gate new work and stop writers. Prefer restoring or reverting app images
according to the plan verified in staging. Reverting only images requires
testing the earlier application against the upgraded schema. Downgrading
the identity migrations deletes challenge, invitation, and workspace request
state from their tables. Restore the matched version, database, session and
Link files when using a backup, and preserve encryption keys. Reconcile
gateway claims and Zenodo drafts created after the backup with their actual
external state.
