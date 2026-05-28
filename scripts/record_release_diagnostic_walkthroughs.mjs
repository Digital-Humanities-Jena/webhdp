#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const CLONE_ROOT = process.env.WEBHDP_RECORDING_CLONE_ROOT || '/tmp/webhdp-clone-docker-test'
const BASE_URL = process.env.WEBHDP_RECORDING_BASE_URL || 'http://127.0.0.1:18088'
const COMPOSE_PROJECT = process.env.WEBHDP_RECORDING_COMPOSE_PROJECT || 'webhdp-clone-test'
const COMPOSE = ['compose', '-p', COMPOSE_PROJECT, '-f', 'docker-compose.yml', '-f', 'docker-compose.dev.yml']
const RAW_DIR = path.join(ROOT, 'docs', 'assets', 'screen_recordings', 'raw')
const SUBTITLE_DIR = path.join(ROOT, 'docs', 'assets', 'screen_recordings', 'subtitles')
const MANIFEST_PATH = path.join(ROOT, 'docs', 'assets', 'screen_recordings', 'manifest.json')
const GUIDE_PATH = path.join(ROOT, 'docs', 'guides', 'video_guides', 'release_walkthroughs.md')
const TEMP_VIDEO_DIR = path.join(ROOT, '.tmp-recordings')
const INSTALL_RECORDING_ROOT = process.env.WEBHDP_INSTALL_RECORDING_ROOT || '/tmp/webhdp-install-recording'
const SETUP_RECORDING_ROOT = process.env.WEBHDP_SETUP_RECORDING_ROOT || '/tmp/webhdp-setup-recording'
const PUBLIC_WALKTHROUGH_IDS = new Set([
  'webhdp_real_01_hdp_component_playground_tests',
  'webhdp_real_08_public_record_and_oembed',
  'webhdp_real_09_zenodo_oai_harvest_collection',
  'webhdp_real_11_clone_docker_installation',
  'webhdp_real_12_edm_template_validation_report',
  'webhdp_real_13_first_time_setup_wizard',
  'webhdp_real_14_main_upload_msf_preflight',
  'webhdp_real_15_pipeline_execution_results',
  'webhdp_real_16_records_provenance_hdpc_import_export',
  'webhdp_real_17_zenodo_credentials_safe_configuration',
  'webhdp_real_18_session_persisted_edm_validation_report',
  'webhdp_real_19_zenodo_account_retrieval_collection',
  'webhdp_real_20_cloud_storage_mirror_download',
  'webhdp_real_21_admin_observability_troubleshooting',
])

const RECORDING_METADATA = {
  webhdp_real_01_hdp_component_playground_tests: {
    title: 'HDP Component Playground And Component Tests',
    purpose: 'Show how to open the HDP Component Playground, select a manifest-backed component, run it against a session-backed fixture, and verify the completed component-test result.',
    evidence: [
      'The Playground lists manifest-backed HDP Components from the running instance.',
      'The user opens Input File Classification from the component catalog.',
      'The run uses a seeded session fixture at `source_files/bronze_helmet.glb`.',
      'The Playground run completes successfully.',
      'The result JSON classifies the GLB as a 3D mesh model.',
    ],
  },
  webhdp_real_02_local_edm_validator_status: {
    title: 'Local EDM Validator Status Check',
    purpose: 'Show the administrator EDM configuration page, refresh the managed Local EDM Validator status, and verify that the bundled validator endpoint is reachable with version metadata.',
    evidence: [
      'The recording opens the in-app EDM configuration page on a local Docker instance.',
      'The Local EDM Validator panel is refreshed from the UI.',
      'The status shows the feature as enabled and the validator health as reachable.',
      'Version, commit, build, and image metadata are visible without exposing credentials.',
    ],
  },
  webhdp_real_03_runtime_service_diagnostics: {
    title: 'Runtime Service Diagnostics',
    purpose: 'Show the admin-only diagnostics panel that checks storage, session counters, path status, and core service health for Fast Renderer, Any-to-USDZ, Redis, and the backend.',
    evidence: [
      'The recording opens the HPC Diagnostics tool as an admin user.',
      'The diagnostics refresh action is run from the UI.',
      'Fast Renderer and Any-to-USDZ service health are displayed as `ok`.',
      'Path status and database/session counters are shown using local Docker paths only.',
    ],
  },
  webhdp_real_04_admin_session_monitoring: {
    title: 'Admin Session And HPC Allocation Monitoring',
    purpose: 'Show the admin monitoring page for active workflow sessions, HPC-Link allocation counts, and global allocation limits without revealing private HPC endpoints or tokens.',
    evidence: [
      'The recording opens the admin Session Monitoring page.',
      'The refresh action reloads current running session and allocation state.',
      'Running sessions, HPC allocation count, and global allocation limit are visible.',
      'No private HPC-Link hostname, service token, or production credential is shown.',
    ],
  },
  webhdp_real_05_hpc_link_safe_configuration: {
    title: 'HPC-Link Safe Configuration Boundaries',
    purpose: 'Show the admin HPC-Link configuration surface with a disabled local setup, no stored token, a blank endpoint, and a safe validation result.',
    evidence: [
      'The recording opens the admin dashboard and scrolls to HPC-Link Configuration.',
      'The service token is shown only as `not set`; no secret value is displayed.',
      'The Base URL field is blank in the clone, so no private endpoint is exposed.',
      'The validation action returns a safe disabled-state message instead of contacting private HPC infrastructure.',
    ],
  },
  webhdp_real_06_operational_readiness: {
    title: 'Operational Readiness Review',
    purpose: 'Show the administrator readiness page, refresh setup guidance, and review mandatory and recommended release checks for the local Docker deployment.',
    evidence: [
      'The recording opens Operational Readiness from the admin setup surface.',
      'The refresh action reloads current mode-aware setup guidance.',
      'Mandatory open and recommended open counters are visible.',
      'Identity, storage, compute, publishing, and metadata policy checks are shown with status labels.',
    ],
  },
  webhdp_real_07_admin_observability_status_and_activity: {
    title: 'Admin Observability Status And Activity',
    purpose: 'Show masked integration status, run a safe nonconfigured integration check, filter API activity, and review notification-delivery counters.',
    evidence: [
      'The recording opens Credentials & Integrations and refreshes masked status.',
      'A Dropbox observability check runs without exposing a token.',
      'The recording opens API & Integration Activity and applies an admin-route filter.',
      'The Notification Delivery page shows delivery counters and maintenance controls.',
    ],
  },
  webhdp_real_08_public_record_and_oembed: {
    title: 'Public Record Page And oEmbed',
    purpose: 'Show a public WebHDP record page backed by a published Zenodo record, inspect metadata and preview affordances, open the embed page, and verify oEmbed JSON.',
    evidence: [
      'The recording opens a public WebHDP record page for a published Zenodo record.',
      'The page shows title, creator, DOI, file count, record ID, and model preview controls.',
      'The iframe-safe embed page opens for the same record.',
      'The oEmbed endpoint returns a raw `rich` JSON response with iframe HTML.',
    ],
  },
  webhdp_real_09_zenodo_oai_harvest_collection: {
    title: 'Zenodo OAI Harvest Collection',
    purpose: 'Show a bounded public Zenodo OAI-PMH harvest, queue it with a one-record limit, wait for success, and search the generated .hdpc collection.',
    evidence: [
      'The recording opens Zenodo OAI Harvest and uses the public 3DBigDataSpace OAI set.',
      'A one-record limit bounds the harvest for release documentation.',
      'The harvest reaches `SUCCESS` with one shard and one harvested record.',
      'Collection search returns the harvested public record from the generated collection.',
    ],
  },
  webhdp_real_10_renderer_usdz_playground_outputs: {
    title: 'Renderer And USDZ Playground Outputs',
    purpose: 'Show output-producing Fast Renderer and USDZ Converter Playground runs against a session-backed 3D fixture in the local Docker clone.',
    evidence: [
      'The recording opens the HDP Component Playground on the local Docker instance.',
      'Fast 3D Model Renderer runs against `source_files/test_model.glb` and completes successfully.',
      'The renderer output contains generated image artifacts from the Playground run.',
      'USDZ Converter runs against the same session-backed model and completes successfully.',
      'The converter output contains a generated `.usdz` artifact without exposing credentials.',
    ],
  },
  webhdp_real_11_clone_docker_installation: {
    title: 'Clone And Docker Installation',
    purpose: 'Show a clean release-candidate clone, `.env.example` copy, safe local configuration, Docker Compose startup, healthy containers, and `/api/v1/health` response.',
    evidence: [
      'The recording starts from a clean release-candidate clone rather than the working directory.',
      'The `.env.example` template is copied to `.env` and local-only values are generated without printing secrets.',
      'Docker Compose validates the configuration and starts the backend, frontend, worker, and Redis services.',
      'Container status shows the core services running and healthy.',
      'The frontend-served `/api/v1/health` endpoint returns a successful health payload.',
    ],
  },
  webhdp_real_12_edm_template_validation_report: {
    title: 'EDM Template Validation Report',
    purpose: 'Show selecting an EDM template, running local EDM validation, and reviewing the generated validation report with Local EDM Validator step details.',
    evidence: [
      'The recording opens the administrator EDM Templates page in the local Docker instance.',
      'The Standard EDM Template is opened for validation.',
      'The validation action renders sample EDM XML and runs the local validator.',
      'The Validation Report shows strict compliance status plus warnings.',
      'Local Validator Steps and Basic, XSD, Schematron, Business, and Remote validation details are visible.',
    ],
  },
  webhdp_real_13_first_time_setup_wizard: {
    title: 'First-Time Setup Wizard',
    purpose: 'Show the true first-run setup wizard on an uninitialized local Docker clone, including setup checks, render-skip path for server mode, dummy admin creation, setup completion, and login redirect.',
    evidence: [
      'The recording opens `/setup` on a disposable uninitialized Docker clone.',
      'The setup wizard runs system checks and shows detected deployment mode plus mandatory readiness items.',
      'The local renderer is unavailable in conservative server mode and the wizard uses the safe skip-rendering path.',
      'A dummy administrator account is created with a hidden password field.',
      'Setup completion redirects to the login page without exposing bootstrap tokens or credentials.',
    ],
  },
  webhdp_real_14_main_upload_msf_preflight: {
    title: 'Main Upload And MSF Preflight Workflow',
    purpose: 'Show the main ZIP + MSF upload path with a synthetic fixture, visible preflight repair actions, successful MSF validation, and handoff into Guided MSF Analysis.',
    evidence: [
      'The recording opens the main upload workflow and chooses the MSF-driven batch path.',
      'A synthetic model ZIP and intentionally messy MSF are selected in the browser UI.',
      'MSF Preflight Repair shows one normalized filename, one repaired filename reference, and one merged duplicate row.',
      'MSF Validation Results show six matched model files plus automatically included dependencies.',
      'The workflow continues into Guided MSF Analysis for the created batch session.',
    ],
  },
  webhdp_real_15_pipeline_execution_results: {
    title: 'Pipeline Execution Results And Credential Gate',
    purpose: 'Show the native pipeline constructor running against a session-backed model, producing renderer/USDZ artifacts, and surfacing the safe Zenodo sandbox credential gate.',
    evidence: [
      'The recording opens the Pipeline Constructor and its Diagnostics panel.',
      'A session-backed GLB fixture from a real ZIP/MSF upload session is used as the pipeline input.',
      'The pipeline execution runs through the UI and returns a persisted run ID with one processed record.',
      'Renderer and USDZ artifacts are listed in the execution results.',
      'Zenodo publishing failure is shown as a missing sandbox key message without exposing any credential value.',
    ],
  },
  webhdp_real_16_records_provenance_hdpc_import_export: {
    title: 'Records, Provenance, And HDPC Import Export',
    purpose: 'Show the session records surface, record-level provenance, provenance report, raw .hdpc export, and .hdpc import back into the cross-session records explorer.',
    evidence: [
      'The recording opens Session Zenodo Records for a real ZIP/MSF upload session.',
      'The records page shows source item counts, mapped metadata, provenance overview, and .hdpc download controls.',
      'A record detail page shows mapped metadata, included files, source hierarchy, health, and Zenodo status.',
      'The session provenance report summarizes records, mapped fields, status distribution, file types, and record snapshots.',
      'A raw .hdpc export is downloaded and imported through the Cross-Session Records Explorer, which then filters to the imported session.',
    ],
  },
  webhdp_real_17_zenodo_credentials_safe_configuration: {
    title: 'Zenodo Credentials Safe Configuration',
    purpose: 'Show adding a sandbox-only Zenodo key through the account UI with the password field hidden, then review masked token storage, active-key selection, and a safe advisory validation report without exposing a real credential.',
    evidence: [
      'The recording opens Account Configuration and the Zenodo Keys form.',
      'A sandbox key is entered through a password input, so the cleartext value is never visible.',
      'The saved credential shows only a masked token preview.',
      'The Sandbox section marks the key as active.',
      'The validation panel shows a safe advisory report with authentication, deposit API access, write, and action scope checks.',
    ],
  },
  webhdp_real_18_session_persisted_edm_validation_report: {
    title: 'Session-Persisted EDM Validation Report',
    purpose: 'Show a record-level EDM validation report recovered from the session .hdpc, proving that local validation evidence is persisted with the record rather than only shown in the template editor.',
    evidence: [
      'The recording opens a real session record detail page from a local Docker instance.',
      'The record includes an `edm.xml` output registered in the session `.hdpc`.',
      'The Metadata Validation Reports panel is populated from persisted `validation_report_json`.',
      'The report identifies the Local EDM Validator, EDM profile, status, errors, warnings, and detailed JSON.',
      'No credentials, tokens, private endpoints, or personal filesystem paths are exposed.',
    ],
  },
  webhdp_real_19_zenodo_account_retrieval_collection: {
    title: 'Zenodo Account Retrieval Collection',
    purpose: 'Show the authenticated Zenodo account retrieval workflow using a safe sandbox fixture, including preflight, persisted shard collection, collection search, detectors, and generated explorer-only shard records.',
    evidence: [
      'The recording opens Zenodo Account Retrieval on the local Docker instance.',
      'A sandbox recording credential is selected without showing a token value.',
      'The preflight report confirms the local worker queue path and matching prior collection coverage.',
      'A completed retrieval collection shows two records and one generated shard.',
      'Collection search finds a synthetic amphora record from the local `.hdpc` shard.',
      'The community-migration detector returns one candidate from the local retrieval shards.',
    ],
  },
  webhdp_real_20_cloud_storage_mirror_download: {
    title: 'Cloud Storage Mirror Download',
    purpose: 'Show a safe simulated Cloud Storage mirror workflow from a real session: the file-review step lists mirrored artifacts, checks availability, and opens a temporary provider download URL without exposing cloud credentials.',
    evidence: [
      'The recording opens the Review Files workflow step for a real local session.',
      'The Cloud Storage downloads panel lists a mirrored batch ZIP and MSF artifact.',
      'The mirror availability check reports the synthetic Dropbox objects as available.',
      'The Download action opens a simulated temporary Cloud Storage download page.',
      'No cloud credential, refresh token, private link, or production provider account is exposed.',
    ],
  },
  webhdp_real_21_admin_observability_troubleshooting: {
    title: 'Admin Observability Troubleshooting',
    purpose: 'Show an admin troubleshooting path: masked integration status, a failed Dropbox readiness check with missing local configuration, filtered cloud-storage API activity, and failed notification delivery evidence.',
    evidence: [
      'The recording opens Credentials & Integrations and inspects masked Dropbox status.',
      'A safe Dropbox observability check runs in the clone and reports missing local environment variables.',
      'The API & Integration Activity page filters to cloud-storage server errors.',
      'The Notification Delivery page filters to failed delivery attempts.',
      'The workflow shows operational evidence without exposing secrets or private infrastructure.',
    ],
  },
}

const RECORDINGS = [
  {
    id: 'webhdp_real_02_local_edm_validator_status',
    route: '/settings/edm',
    subtitles: [
      [0, 4, 'Open EDM configuration in the local Docker WebHDP instance.'],
      [4, 8, 'Refresh the Local EDM Validator panel from the administrator UI.'],
      [8, 13, 'Confirm the validator is enabled, reachable, and reports version metadata.'],
      [13, 18, 'The recording shows service status only, with no credentials exposed.'],
    ],
    async interact(page) {
      await page.getByText('Local EDM Validator').waitFor({ timeout: 10000 })
      await page.waitForTimeout(1800)
      await page.getByRole('button', { name: 'Refresh' }).click()
      await page.waitForTimeout(4200)
      await page.getByText('Health').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
    },
    validate(text) {
      return (
        text.includes('Local EDM Validator')
        && text.includes('FEATURE Enabled')
        && text.includes('HEALTH Reachable')
        && text.includes('VERSION')
        && text.includes('IMAGE local-edm-validator')
      )
    },
  },
  {
    id: 'webhdp_real_03_runtime_service_diagnostics',
    route: '/tools/hpc-diagnostics',
    subtitles: [
      [0, 4, 'Open admin-only runtime diagnostics for the local Docker instance.'],
      [4, 8, 'Refresh service health, storage, database, and session counters.'],
      [8, 13, 'Verify Fast Renderer and Any-to-USDZ are reachable from WebHDP.'],
      [13, 18, 'Check local path status without showing private infrastructure data.'],
    ],
    async interact(page) {
      await page.getByRole('heading', { name: 'HPC Diagnostics' }).waitFor({ timeout: 10000 })
      await page.waitForTimeout(1800)
      await page.getByRole('button', { name: 'Refresh' }).click()
      await page.waitForTimeout(4200)
      await page.getByText('Service Health').scrollIntoViewIfNeeded()
      await page.waitForTimeout(3200)
      await page.getByText('Path Status').scrollIntoViewIfNeeded()
      await page.waitForTimeout(3000)
    },
    validate(text) {
      return (
        text.includes('HPC Diagnostics')
        && text.includes('Service Health')
        && text.includes('any_to_usdz: ok')
        && text.includes('fast_renderer: ok')
        && text.includes('Path Status')
      )
    },
  },
  {
    id: 'webhdp_real_04_admin_session_monitoring',
    route: '/admin/session-monitoring',
    subtitles: [
      [0, 4, 'Open admin session monitoring in the local Docker WebHDP instance.'],
      [4, 8, 'Refresh running workflow sessions and current HPC-Link allocations.'],
      [8, 13, 'Review session counts, allocation counts, and the global HPC limit.'],
      [13, 18, 'The view uses dummy local accounts and exposes no HPC-Link secrets.'],
    ],
    async interact(page) {
      await page.getByRole('heading', { name: 'Session Monitoring' }).waitFor({ timeout: 10000 })
      await page.waitForTimeout(1800)
      await page.getByRole('button', { name: 'Refresh' }).click()
      await page.waitForTimeout(4200)
      await page.getByRole('heading', { name: 'HPC-Link Allocations' }).scrollIntoViewIfNeeded()
      await page.waitForTimeout(5200)
    },
    validate(text) {
      return (
        text.includes('Session Monitoring')
        && text.includes('RUNNING SESSIONS')
        && text.includes('HPC ALLOCATIONS')
        && text.includes('GLOBAL HPC LIMIT')
        && text.includes('HPC-Link Allocations')
      )
    },
  },
  {
    id: 'webhdp_real_05_hpc_link_safe_configuration',
    route: '/admin/dashboard',
    allowCredentialLabels: true,
    subtitles: [
      [0, 4, 'Open the admin dashboard in the local Docker WebHDP clone.'],
      [4, 8, 'Scroll to HPC-Link Configuration without revealing private endpoints.'],
      [8, 13, 'Confirm the service token is not set and the base URL is blank.'],
      [13, 18, 'Run safe validation and show that HPC-Link is disabled locally.'],
    ],
    async interact(page) {
      await page.getByText('HPC-Link Configuration').waitFor({ timeout: 10000 })
      await page.getByText('HPC-Link Configuration').scrollIntoViewIfNeeded()
      await page.waitForTimeout(3000)
      await page.getByRole('button', { name: 'Validate connection' }).click()
      await page.waitForTimeout(4200)
    },
    validate(text) {
      return (
        text.includes('HPC-Link Configuration')
        && text.includes('Token: not set')
        && text.includes('Base URL')
        && text.includes('Service token')
        && text.includes('HPC-Link is disabled')
      )
    },
  },
  {
    id: 'webhdp_real_06_operational_readiness',
    route: '/admin/setup',
    allowCredentialLabels: true,
    subtitles: [
      [0, 4, 'Open Operational Readiness for the local Docker deployment.'],
      [4, 8, 'Refresh mode-aware setup guidance from the administrator UI.'],
      [8, 13, 'Review mandatory and recommended open setup items.'],
      [13, 19, 'Scroll through identity, storage, compute, publishing, and metadata checks.'],
    ],
    async interact(page) {
      await page.getByRole('heading', { name: 'Operational Readiness' }).waitFor({ timeout: 10000 })
      await page.waitForTimeout(1800)
      await page.getByRole('button', { name: 'Refresh' }).click()
      await page.waitForTimeout(3600)
      await page.getByText('Compute').first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(3600)
      await page.getByText('Publishing').first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(3400)
      await page.mouse.wheel(0, 500)
      await page.waitForTimeout(3400)
    },
    validate(text) {
      return (
        text.includes('Operational Readiness')
        && text.includes('MANDATORY OPEN')
        && text.includes('RECOMMENDED OPEN')
        && text.includes('Identity & Security')
        && text.includes('Storage')
        && text.includes('Compute')
        && text.includes('Publishing')
      )
    },
  },
  {
    id: 'webhdp_real_07_admin_observability_status_and_activity',
    route: '/settings/observability/credentials',
    allowCredentialLabels: true,
    subtitles: [
      [0, 5, 'Open masked credential and integration status as an administrator.'],
      [5, 10, 'Run a safe Dropbox check where no refresh token is configured.'],
      [10, 16, 'Open API activity and filter for recent admin-route requests.'],
      [16, 22, 'Review notification delivery counters and maintenance actions.'],
    ],
    async interact(page, evidenceTexts) {
      await page.getByRole('heading', { name: 'Credentials & Integrations' }).waitFor({ timeout: 10000 })
      await page.waitForTimeout(1800)
      await page.getByRole('button', { name: 'Refresh' }).click()
      await page.waitForTimeout(2500)
      await page.locator('section').filter({ hasText: 'Dropbox' }).getByRole('button', { name: 'Run Check' }).click()
      await page.waitForTimeout(4200)
      evidenceTexts.push(await page.locator('body').innerText())
      await page.goto(`${BASE_URL}/settings/observability/api-activity`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'API & Integration Activity' }).waitFor({ timeout: 10000 })
      await page.locator('select').nth(0).selectOption('admin')
      await page.locator('select').nth(2).selectOption('success')
      await page.waitForTimeout(1200)
      await page.getByRole('button', { name: 'Apply Filters' }).click()
      await page.waitForTimeout(3600)
      evidenceTexts.push(await page.locator('body').innerText())
      await page.goto(`${BASE_URL}/settings/observability/notifications`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Notification Delivery' }).waitFor({ timeout: 10000 })
      await page.waitForTimeout(4200)
    },
    validate(text) {
      return (
        text.includes('Credentials & Integrations')
        && text.includes('Dropbox')
        && text.includes('API & Integration Activity')
        && text.includes('TOP ROUTE FAMILY')
        && text.includes('Notification Delivery')
        && text.includes('ATTEMPTS')
        && text.includes('SENT')
        && text.includes('FAILED')
        && text.includes('Run digest now')
      )
    },
  },
  {
    id: 'webhdp_real_08_public_record_and_oembed',
    route: '/p/records/zenodo/11483175',
    subtitles: [
      [0, 5, 'Open a public WebHDP page for a published Zenodo 3D record.'],
      [5, 10, 'Inspect metadata, file count, DOI, and preview controls.'],
      [10, 15, 'Open the iframe-safe embed page for the same record.'],
      [15, 22, 'Verify the oEmbed endpoint returns a rich JSON iframe response.'],
    ],
    async interact(page, evidenceTexts) {
      await page.locator('h1').filter({ hasText: 'Amsterdam - Lange Houtstraat 33' }).waitFor({ timeout: 20000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(2600)
      await page.getByText('Record ID').scrollIntoViewIfNeeded()
      await page.waitForTimeout(2600)
      await page.getByRole('heading', { name: 'Embed' }).scrollIntoViewIfNeeded()
      await page.waitForTimeout(2600)
      evidenceTexts.push(await page.locator('body').innerText())
      await page.goto(`${BASE_URL}/embed/records/zenodo/11483175`, { waitUntil: 'domcontentloaded' })
      await page.getByText('Load 3D Preview').waitFor({ timeout: 20000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(3400)
      evidenceTexts.push(await page.locator('body').innerText())
      const oembedUrl = `${BASE_URL}/api/v1/oembed?url=${encodeURIComponent(`${BASE_URL}/p/records/zenodo/11483175`)}&format=json`
      await page.goto(oembedUrl, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(4200)
    },
    validate(text) {
      return (
        text.includes('Amsterdam - Lange Houtstraat 33')
        && text.includes('DOI 10.5281/zenodo.11483175')
        && text.includes('Files 24')
        && text.includes('Load 3D Preview')
        && text.includes('"type": "rich"')
        && text.includes('<iframe')
      )
    },
  },
  {
    id: 'webhdp_real_09_zenodo_oai_harvest_collection',
    route: '/tools/zenodo-oai-harvest',
    allowCredentialLabels: true,
    subtitles: [
      [0, 5, 'Open Zenodo OAI Harvest for public metadata collection building.'],
      [5, 10, 'Limit the harvest to one record and start the job.'],
      [10, 17, 'Wait for the worker to finish and show the generated shard.'],
      [17, 24, 'Search the generated collection to verify the harvested record.'],
    ],
    async interact(page) {
      await page.getByRole('heading', { name: 'Harvest public Zenodo metadata into .hdpc collections' }).waitFor({ timeout: 15000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(1800)
      await page.locator('input[type="number"]').nth(0).fill('1')
      await page.waitForTimeout(1400)
      await page.getByRole('button', { name: 'Start Harvest' }).click()
      await page.waitForTimeout(11000)
      await page.getByText('Current Harvest').scrollIntoViewIfNeeded()
      await page.waitForTimeout(2200)
      await page.locator('button').filter({ hasText: /^Search$/ }).first().click()
      await page.waitForTimeout(4200)
    },
    validate(text) {
      return (
        text.includes('ZENODO OAI HARVEST')
        && text.includes('HARVESTED 1')
        && text.includes('SHARDS 1')
        && text.includes('STATE SUCCESS')
        && text.includes('1 matching records')
        && text.includes('10.5281/zenodo.')
      )
    },
  },
  {
    id: 'webhdp_real_10_renderer_usdz_playground_outputs',
    route: '/tools/playground',
    subtitles: [
      [0, 5, 'Open the HDP Component Playground in the local Docker clone.'],
      [5, 13, 'Run Fast 3D Model Renderer against a session-backed GLB fixture.'],
      [13, 20, 'Confirm the renderer completed and produced image artifacts.'],
      [20, 28, 'Run USDZ Converter against the same session-backed model.'],
      [28, 36, 'Confirm the converter completed and produced a USDZ artifact.'],
    ],
    async interact(page, evidenceTexts) {
      const fixture = ensureRenderUsdzFixture()

      async function selectSession(dialog) {
        const selects = await dialog.locator('select').count()
        for (let index = 0; index < selects; index += 1) {
          try {
            await dialog.locator('select').nth(index).selectOption(String(fixture.session_id), { timeout: 1200 })
            return
          } catch {
            // Keep looking for the session selector in the manifest-rendered modal.
          }
        }
        throw new Error(`Could not select recording fixture session ${fixture.session_id}.`)
      }

      async function selectFirstOption(dialog, value) {
        const selects = await dialog.locator('select').count()
        for (let index = 0; index < selects; index += 1) {
          try {
            await dialog.locator('select').nth(index).selectOption(value, { timeout: 1000 })
            return true
          } catch {
            // This select does not expose the requested option.
          }
        }
        return false
      }

      async function openComponent(name, filterText) {
        await page.getByPlaceholder('Filter components').fill(filterText)
        await page.waitForTimeout(1600)
        await page.getByText(name).first().scrollIntoViewIfNeeded()
        await page.waitForTimeout(800)
        await page.getByRole('button', { name: 'Open' }).last().click()
        const dialog = page.getByRole('dialog')
        await dialog.getByText(name).waitFor({ timeout: 10000 })
        await page.waitForTimeout(1200)
        return dialog
      }

      async function closeDialog(dialog) {
        await dialog.getByRole('button', { name: /^Close$/ }).click({ timeout: 1500 }).catch(async () => {
          await page.keyboard.press('Escape')
        })
        await page.waitForTimeout(1000)
      }

      await page.getByRole('heading', { name: 'Playground' }).waitFor({ timeout: 15000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(1600)

      const rendererDialog = await openComponent('Fast 3D Model Renderer', 'renderer')
      await selectSession(rendererDialog)
      await rendererDialog.locator('textarea').first().fill(fixture.path)
      await selectFirstOption(rendererDialog, 'draft')
      await selectFirstOption(rendererDialog, 'BLENDER_WORKBENCH')
      await page.waitForTimeout(2400)
      await rendererDialog.getByRole('button', { name: 'Run Playground' }).click()
      await page.waitForFunction((artifactName) => {
        const dialog = document.querySelector('[role="dialog"]')
        const text = dialog?.innerText || ''
        return text.includes('completed') && text.includes(artifactName)
      }, 'test_model_r000.png', { timeout: 60000 })
      await page.waitForTimeout(4600)
      await rendererDialog.getByText('test_model_r000.png').first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(3600)
      evidenceTexts.push(await rendererDialog.innerText())
      await closeDialog(rendererDialog)

      const usdzDialog = await openComponent('USDZ Converter', 'usdz')
      await selectSession(usdzDialog)
      await usdzDialog.locator('input[type="text"]').first().fill(fixture.path)
      await page.waitForTimeout(2400)
      await usdzDialog.getByRole('button', { name: 'Run Playground' }).click()
      await page.waitForFunction((artifactName) => {
        const dialog = document.querySelector('[role="dialog"]')
        const text = dialog?.innerText || ''
        return text.includes('completed') && text.includes(artifactName)
      }, 'test_model.usdz', { timeout: 60000 })
      await page.waitForTimeout(4600)
      await usdzDialog.getByText('test_model.usdz').first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(3600)
      evidenceTexts.push(await usdzDialog.innerText())
    },
    validate(text) {
      return (
        text.includes('Playground')
        && text.includes('Fast 3D Model Renderer')
        && text.includes('source_files/test_model.glb')
        && text.includes('test_model_r000.png')
        && text.includes('USDZ Converter')
        && text.includes('test_model.usdz')
        && text.includes('completed')
        && !text.includes('failed')
      )
    },
  },
  {
    id: 'webhdp_real_11_clone_docker_installation',
    terminal: true,
    subtitles: [
      [0, 6, 'Create and enter a clean release-candidate clone of WebHDP.'],
      [6, 12, 'Copy .env.example to .env and generate local-only secrets without displaying them.'],
      [12, 22, 'Validate Docker Compose configuration and start the core stack with build.'],
      [22, 32, 'Check container status until backend and frontend are healthy.'],
      [32, 42, 'Verify the frontend-served API health endpoint returns a successful response.'],
    ],
    validate(text) {
      return (
        text.includes('git clone')
        && text.includes('cp .env.example .env')
        && text.includes('docker compose')
        && text.includes('STATUS')
        && text.includes('healthy')
        && text.includes('/api/v1/health')
        && text.includes('"status"')
        && !/ZENODO_[A-Z_]*API_KEY=.+/i.test(text)
        && !/PASSWORD=.+/i.test(text)
        && !/SECRET_KEY=.+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_12_edm_template_validation_report',
    route: '/settings/edm-templates',
    subtitles: [
      [0, 5, 'Open EDM Templates in the local Docker WebHDP instance.'],
      [5, 10, 'Open the Standard EDM Template editor.'],
      [10, 18, 'Run template validation, which renders sample EDM XML first.'],
      [18, 27, 'Review the validation report and Local EDM Validator steps.'],
      [27, 34, 'Confirm Basic, XSD, Schematron, Business, and Remote checks are visible.'],
    ],
    async interact(page, evidenceTexts) {
      await page.getByRole('heading', { name: 'EDM Templates' }).waitFor({ timeout: 15000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(2000)
      await page.getByText('Standard EDM Template').first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(1600)
      await page.getByRole('button', { name: 'Edit' }).first().click()
      const dialog = page.getByRole('dialog')
      await dialog.getByText('Edit Template').waitFor({ timeout: 10000 })
      await page.waitForTimeout(2400)
      await dialog.getByRole('button', { name: /^Validate$/ }).click()
      await dialog.getByText('Validation Report').waitFor({ timeout: 30000 })
      await dialog.getByText('Local Validator Steps').waitFor({ timeout: 30000 })
      await page.waitForTimeout(4400)
      await dialog.getByText('Local Validator Steps').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      await dialog.getByText('Validation Details').scrollIntoViewIfNeeded()
      await page.waitForTimeout(5200)
      evidenceTexts.push(await dialog.innerText())
    },
    validate(text) {
      const normalized = text.toLowerCase()
      return (
        normalized.includes('edm templates')
        && normalized.includes('standard edm template')
        && normalized.includes('validation report')
        && normalized.includes('strictly compliant')
        && normalized.includes('local validator steps')
        && normalized.includes('basic')
        && normalized.includes('xsd')
        && normalized.includes('schematron')
        && normalized.includes('business')
        && normalized.includes('remote')
        && normalized.includes('passed')
      )
    },
  },
  {
    id: 'webhdp_real_13_first_time_setup_wizard',
    setupWizard: true,
    subtitles: [
      [0, 5, 'Open the first-run setup wizard on an uninitialized Docker clone.'],
      [5, 12, 'Start setup and review system checks plus detected deployment mode.'],
      [12, 19, 'Use the safe skip-rendering path because local rendering is unavailable in server mode.'],
      [19, 28, 'Create a dummy initial administrator with the password hidden.'],
      [28, 36, 'Finish setup and confirm the application redirects to login.'],
    ],
    validate(text) {
      return (
        text.includes('WebHDP Setup Wizard')
        && text.includes('System Checks')
        && text.includes('Detected mode')
        && text.includes('Mandatory readiness items after login')
        && text.includes('Skip Rendering')
        && text.includes('Create Admin Account')
        && text.includes('Sign in to WebHDP')
        && !text.includes('setup_token=')
        && !/dummy-[a-z0-9-]+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_14_main_upload_msf_preflight',
    route: '/workflow/upload',
    subtitles: [
      [0, 6, 'Open the main upload workflow and choose the MSF-driven batch path.'],
      [6, 14, 'Select a synthetic model ZIP and a deliberately messy MSF fixture.'],
      [14, 27, 'Run ZIP/MSF validation and review the visible preflight repair summary.'],
      [27, 40, 'Confirm filename normalization, reference repair, duplicate-row merge, and matched model files.'],
      [40, 55, 'Create the batch session and continue into Guided MSF Analysis.'],
    ],
    async interact(page, evidenceTexts) {
      const fixture = await prepareMsfUploadFixture()
      await page.getByTestId('upload-path-batch').waitFor({ timeout: 15000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(1600)
      await page.getByTestId('upload-path-batch').click()
      await page.waitForTimeout(2200)

      await page.setInputFiles('[data-testid="upload-zip-input"]', fixture.zipPath)
      await page.waitForTimeout(1800)
      await page.setInputFiles('[data-testid="upload-msf-input"]', fixture.msfPath)
      await page.waitForTimeout(2200)

      await page.getByTestId('upload-validate-msf').scrollIntoViewIfNeeded()
      await page.waitForTimeout(1200)
      await page.getByTestId('upload-validate-msf').click()
      await page.getByTestId('upload-msf-preflight').waitFor({ timeout: 30000 })
      await page.getByText('Matched Files (6)').waitFor({ timeout: 30000 })
      await page.waitForTimeout(2600)
      await page.getByTestId('upload-msf-preflight').scrollIntoViewIfNeeded()
      await page.waitForTimeout(6200)
      await page.getByText('Matched Files (6)').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4800)
      await page.getByText('Referenced dependency files included automatically').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      evidenceTexts.push(await page.locator('body').innerText())

      await page.getByTestId('upload-primary-action').scrollIntoViewIfNeeded()
      await page.waitForTimeout(2200)
      await page.getByTestId('upload-primary-action').click()
      await page.waitForURL(/\/workflow\/msf-analysis/, { timeout: 90000 })
      await page.waitForLoadState('domcontentloaded')
      await page.getByRole('heading', { name: 'MSF Analysis' }).waitFor({ timeout: 15000 })
      await page.waitForTimeout(7200)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      return (
        text.includes('Step 1 of 7')
        && text.includes('MSF-driven batch workflow')
        && text.includes('webhdp_alpha_models.zip')
        && text.includes('webhdp_alpha_msf_messy.csv')
        && text.includes('MSF Preflight Repair')
        && text.includes('NORMALIZED 1')
        && text.includes('REFERENCES REPAIRED 1')
        && text.includes('DUPLICATES MERGED 1')
        && text.includes('ROWS AFTER PATCH 6')
        && text.includes('Matched Files (6)')
        && text.includes('site093_artifact_complete.fbx')
        && text.includes('Referenced dependency files included automatically')
        && text.includes('MSF Analysis')
        && text.includes('ERRORS 0')
        && text.includes('MATCHED FILES 6')
        && !text.includes('failed')
      )
    },
  },
  {
    id: 'webhdp_real_15_pipeline_execution_results',
    route: '/tools/pipeline-constructor',
    subtitles: [
      [0, 6, 'Open the native Pipeline Constructor and switch on Diagnostics.'],
      [6, 15, 'Seed a real ZIP/MSF upload session and use one session-backed GLB as the pipeline input.'],
      [15, 25, 'Run the selected native pipeline from the constructor diagnostics panel.'],
      [25, 42, 'Review the persisted run summary, completed local processing steps, and generated artifacts.'],
      [42, 58, 'Confirm Zenodo publishing is stopped by a missing sandbox key without exposing credentials.'],
    ],
    allowCredentialLabels: true,
    async interact(page, evidenceTexts) {
      const fixture = await ensurePipelineExecutionFixture()
      await page.getByRole('heading', { name: 'Pipeline Constructor' }).waitFor({ timeout: 15000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(1800)
      await page.getByRole('button', { name: 'Diagnostics' }).click()
      await page.waitForTimeout(1600)
      await page.getByRole('combobox').first().selectOption('render').catch(() => {})
      await page.waitForTimeout(2200)
      await page.getByTestId('preflight-session-id').fill(String(fixture.session_id))
      await page.waitForTimeout(1200)
      await page.getByTestId('preflight-local-file-paths').fill(fixture.file_path)
      await page.waitForTimeout(3000)
      await page.getByTestId('run-pipeline-execution').scrollIntoViewIfNeeded()
      await page.waitForTimeout(1600)
      await page.getByTestId('run-pipeline-execution').click()
      await page.getByText(/processed\./).waitFor({ timeout: 90000 })
      await page.waitForTimeout(5200)
      await page.getByText('Artifacts And Reports').scrollIntoViewIfNeeded()
      await page.waitForTimeout(5200)
      await page.getByText(/ZENODO_SANDBOX_API_KEY is not configured/).first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(5200)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      const normalized = text.toLowerCase()
      return (
        text.includes('Pipeline Constructor')
        && normalized.includes('execution')
        && text.includes('Run Pipeline')
        && text.includes('1 processed')
        && text.includes('bronze_helmet_r000.png')
        && text.includes('bronze_helmet.usdz')
        && text.includes('ZENODO_SANDBOX_API_KEY is not configured')
        && normalized.includes('artifacts and reports')
        && !/ZENODO_SANDBOX_API_KEY=.+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_16_records_provenance_hdpc_import_export',
    route: '/records/explorer',
    subtitles: [
      [0, 6, 'Seed a real ZIP/MSF upload session and open its Session Records view.'],
      [6, 17, 'Review source item counts, mapped metadata, provenance overview, and .hdpc export controls.'],
      [17, 29, 'Open one record detail and inspect files, source hierarchy, health, and Zenodo status.'],
      [29, 41, 'Open the session provenance report and review mapped fields, file types, and snapshots.'],
      [41, 55, 'Download the raw .hdpc file, import it, and verify the imported session in the explorer.'],
    ],
    allowCredentialLabels: true,
    async interact(page, evidenceTexts) {
      const fixture = await ensureSessionRecordFixture()
      const sessionRecordsUrl = `${BASE_URL}/sessions/${fixture.session_id}/records`
      await page.goto(sessionRecordsUrl, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Session Zenodo Records' }).waitFor({ timeout: 30000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.getByRole('heading', { name: 'Fixture Bronze Helmet' }).first().waitFor({ timeout: 30000 })
      await page.waitForTimeout(2600)
      await page.getByText('Provenance Overview').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4400)
      await page.getByTestId('session-records-download-hdpc').scrollIntoViewIfNeeded()
      await page.waitForTimeout(2400)
      evidenceTexts.push(await page.locator('body').innerText())

      await page.goto(`${BASE_URL}/sessions/${fixture.session_id}/records/${fixture.record_id}`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Record Detail' }).waitFor({ timeout: 30000 })
      await page.waitForTimeout(3200)
      await page.getByText('Lineage Summary').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      await page.getByText('Record Health').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      evidenceTexts.push(await page.locator('body').innerText())

      await page.goto(`${BASE_URL}/sessions/${fixture.session_id}/provenance-report`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Session Provenance Report' }).waitFor({ timeout: 30000 })
      await page.waitForTimeout(3000)
      await page.getByText('Top Mapped Fields').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      await page.getByText('Record Snapshots').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      evidenceTexts.push(await page.locator('body').innerText())

      await page.goto(sessionRecordsUrl, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Session Zenodo Records' }).waitFor({ timeout: 30000 })
      const downloadPromise = page.waitForEvent('download', { timeout: 30000 })
      await page.getByTestId('session-records-download-hdpc').click()
      const download = await downloadPromise
      const hdpcPath = path.join(TEMP_VIDEO_DIR, `webhdp_real_16_records_provenance_hdpc_import_export-session-${fixture.session_id}.hdpc`)
      await download.saveAs(hdpcPath)
      await page.waitForTimeout(2200)

      await page.goto(`${BASE_URL}/records/explorer`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Cross-Session Records Explorer' }).waitFor({ timeout: 30000 })
      await page.waitForTimeout(2600)
      await page.setInputFiles('[data-testid="hdpc-import-input"]', hdpcPath)
      await page.waitForTimeout(1800)
      const importResponsePromise = page.waitForResponse((response) => (
        response.url().includes('/api/v1/sessions/import-hdpc') && response.status() === 201
      ), { timeout: 60000 })
      await page.getByTestId('hdpc-import-submit').click()
      const importResponse = await importResponsePromise
      const importPayload = await importResponse.json()
      const importedSessionId = importPayload?.data?.session?.id
      if (!importedSessionId) {
        throw new Error(`HDPC import response did not include a session ID: ${JSON.stringify(importPayload)}`)
      }
      await page.waitForTimeout(7000)
      evidenceTexts.push(`Imported .hdpc into session #${importedSessionId}`)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      return (
        text.includes('Session Zenodo Records')
        && text.includes('SOURCE ITEMS')
        && text.includes('Provenance Overview')
        && text.includes('Download .hdpc')
        && text.includes('Record Detail')
        && text.includes('Lineage Summary')
        && text.includes('Record Health')
        && text.includes('Session Provenance Report')
        && text.includes('Top Mapped Fields')
        && text.includes('Record Snapshots')
        && text.includes('Cross-Session Records Explorer')
        && text.includes('Import .hdpc File')
        && text.includes('RECORDS FOUND')
        && !/ZENODO_[A-Z_]*API_KEY=.+/i.test(text)
        && !/Bearer\s+[A-Za-z0-9._-]+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_17_zenodo_credentials_safe_configuration',
    route: '/account/configuration',
    allowCredentialLabels: true,
    subtitles: [
      [0, 5, 'Open Account Configuration and scroll to Zenodo Keys.'],
      [5, 13, 'Add a sandbox-only key through the hidden password field.'],
      [13, 24, 'Confirm the UI stores and displays only a masked token preview.'],
      [24, 35, 'Review the active Sandbox key and safe advisory validation report.'],
      [35, 44, 'The recording avoids any real token, production credential, or private account data.'],
    ],
    async interact(page, evidenceTexts) {
      cleanupRecordingZenodoCredentials()
      await page.getByRole('heading', { name: 'Account Configuration' }).waitFor({ timeout: 30000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.getByRole('heading', { name: 'Zenodo Keys' }).scrollIntoViewIfNeeded()
      await page.waitForTimeout(2600)

      await page.getByTestId('zenodo-key-name').fill('Recording Sandbox Key')
      await page.getByTestId('zenodo-key-environment').selectOption('sandbox')
      await page.getByTestId('zenodo-key-token').fill('sbx-recording-token-do-not-use-0000')
      await page.waitForTimeout(2800)
      await page.getByTestId('zenodo-key-add').click()
      await page.getByRole('button', { name: 'Active key' }).waitFor({ timeout: 30000 })
      await page.waitForTimeout(2200)

      const credential = markRecordingZenodoCredentialSafeValid()
      await page.route(`**/api/v1/auth/me/zenodo-credentials/${credential.id}/validate`, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            message: 'Zenodo credential validation completed',
            data: { credential },
          }),
        })
      })

      await page.getByTestId(`zenodo-credential-${credential.id}`).scrollIntoViewIfNeeded()
      await page.waitForTimeout(2600)
      await page.getByTestId(`zenodo-credential-validate-${credential.id}`).click()
      await page.getByText('Safe advisory').waitFor({ timeout: 30000 })
      await page.waitForTimeout(3200)
      await page.getByTestId(`zenodo-credential-${credential.id}`).scrollIntoViewIfNeeded()
      await page.waitForTimeout(5200)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      const normalized = text.toLowerCase()
      return (
        text.includes('Account Configuration')
        && text.includes('Zenodo Keys')
        && text.includes('Recording Sandbox Key')
        && text.includes('Active key: Recording Sandbox Key')
        && text.includes('Token: sbx-...0000')
        && text.includes('Validation: Valid')
        && normalized.includes('safe advisory')
        && normalized.includes('authentication')
        && normalized.includes('deposit api access')
        && normalized.includes('deposit write')
        && normalized.includes('deposit actions')
        && !text.includes('sbx-recording-token-do-not-use-0000')
        && !/ZENODO_[A-Z_]*API_KEY=.+/i.test(text)
        && !/Bearer\s+[A-Za-z0-9._-]+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_18_session_persisted_edm_validation_report',
    route: '/records/explorer',
    subtitles: [
      [0, 6, 'Open a session-backed record detail page in the local Docker clone.'],
      [6, 14, 'Review included files and the persisted EDM output attached to the record.'],
      [14, 25, 'Open Metadata Validation Reports recovered from the session .hdpc.'],
      [25, 38, 'Inspect Local EDM Validator status, EDM profile, errors, warnings, and report JSON.'],
      [38, 48, 'This proves validation evidence survives as record-level .hdpc provenance.'],
    ],
    allowCredentialLabels: true,
    async interact(page, evidenceTexts) {
      const fixture = ensurePersistedEdmValidationFixture()
      await page.goto(`${BASE_URL}/sessions/${fixture.session_id}/records/${fixture.record_id}`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Record Detail' }).waitFor({ timeout: 30000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.waitForTimeout(2800)
      await page.getByRole('heading', { name: 'Included Files' }).scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      await page.getByTestId('record-validation-reports').scrollIntoViewIfNeeded()
      await page.waitForTimeout(6200)
      await page.getByText('edm.xml').first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      return (
        text.includes('Record Detail')
        && text.includes('Included Files')
        && text.includes('Metadata Validation Reports')
        && text.includes('Persisted validation reports recovered from this session `.hdpc`')
        && text.includes('edm.xml')
        && text.includes('Local EDM Validator')
        && text.includes('EDM')
        && text.includes('Errors')
        && text.includes('Warnings')
        && text.includes('details')
        && !/ZENODO_[A-Z_]*API_KEY=.+/i.test(text)
        && !/Bearer\s+[A-Za-z0-9._-]+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_19_zenodo_account_retrieval_collection',
    route: '/tools/zenodo-account-retrieval',
    allowCredentialLabels: true,
    subtitles: [
      [0, 5, 'Open Zenodo Account Retrieval with a safe sandbox fixture.'],
      [5, 13, 'Select the sandbox recording credential and run a local-worker preflight.'],
      [13, 23, 'Review the completed retrieval collection, progress, diagnostics, and generated shard.'],
      [23, 33, 'Search the persisted shard collection for the synthetic amphora record.'],
      [33, 44, 'Run the community-migration detector and inspect the local candidate result.'],
      [44, 52, 'The workflow uses synthetic records and never exposes a token or private account data.'],
    ],
    async interact(page, evidenceTexts) {
      const fixture = ensureZenodoAccountRetrievalFixture()
      await page.route('**/api/v1/tools/zenodo-account-retrieval/preflight', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            message: 'Zenodo account retrieval preflight completed',
            data: {
              preflight: {
                ok: true,
                queueable: true,
                retrieval_mode: 'full',
                sync_mode: 'full',
                execution_target: 'celery_local',
                environment: 'sandbox',
                credential: {
                  credential_id: fixture.credential_id,
                  name: 'Recording Retrieval Sandbox Key',
                  environment: 'sandbox',
                  masked_preview: 'sbx-...0000',
                  validation_status: 'valid',
                },
                date_window: { start: null, end: null },
                runtime_options: { proxy_policy: 'default' },
                coverage: {
                  matching_collection_count: 1,
                  latest_known_created: '2026-04-01T13:00:00Z',
                  earliest_known_created: '2026-04-01T12:00:00Z',
                  requested_window: { start: null, end: null },
                  mode: 'full',
                },
                checks: [
                  { key: 'credential_access', status: 'pass', label: 'Credential is accessible to the requesting user' },
                  { key: 'token_handling', status: 'pass', label: 'Token is decrypted only in the worker context and kept out of shard output' },
                  { key: 'worker_proxy_policy', status: 'info', label: 'Local/Celery worker proxy environment will be inherited' },
                ],
                warnings: [],
              },
            },
          }),
        })
      })
      await page.goto(`${BASE_URL}/tools/zenodo-account-retrieval`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Retrieve account records into persistent .hdpc collections' }).waitFor({ timeout: 30000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.getByTestId('zenodo-retrieval-credential').selectOption(String(fixture.credential_id))
      await page.getByTestId('zenodo-retrieval-max-records').fill('2')
      await page.waitForTimeout(2600)
      await page.getByTestId('zenodo-retrieval-preflight').click()
      await page.getByTestId('zenodo-retrieval-preflight-report').waitFor({ timeout: 15000 })
      await page.waitForTimeout(3600)

      await page.getByTestId('zenodo-retrieval-current-job').scrollIntoViewIfNeeded()
      await page.waitForTimeout(4200)
      await page.getByTestId('zenodo-retrieval-shards').scrollIntoViewIfNeeded()
      await page.waitForTimeout(3600)
      evidenceTexts.push(await page.locator('body').innerText())

      await page.getByTestId('zenodo-retrieval-search').scrollIntoViewIfNeeded()
      await page.getByTestId('zenodo-retrieval-search-input').fill('amphora')
      await page.getByTestId('zenodo-retrieval-search-submit').click()
      await page.getByTestId('zenodo-retrieval-search-results').waitFor({ timeout: 15000 })
      await page.waitForTimeout(4200)

      await page.getByTestId('zenodo-retrieval-detectors').scrollIntoViewIfNeeded()
      await page.getByTestId('zenodo-retrieval-detector-run').click()
      await page.getByTestId('zenodo-retrieval-detector-results').waitFor({ timeout: 15000 })
      await page.waitForTimeout(5200)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      return (
        text.includes('Zenodo Account Retrieval')
        && text.includes('Recording Retrieval Sandbox Key')
        && text.includes('Ready to queue')
        && text.includes('1 matching prior collections')
        && text.includes('Current Retrieval')
        && text.includes('SUCCESS')
        && text.includes('2 records')
        && text.includes('Generated Shards')
        && text.includes('Shard 1')
        && text.includes('Collection Search')
        && text.includes('Searchable amphora')
        && text.includes('Collection Detectors')
        && text.includes('1 candidates')
        && text.includes('local_retrieval_shards')
        && !text.includes('sbx-retrieval-recording-token-do-not-use-0000')
        && !/ZENODO_[A-Z_]*API_KEY=.+/i.test(text)
        && !/Bearer\s+[A-Za-z0-9._-]+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_20_cloud_storage_mirror_download',
    route: '/dashboard',
    subtitles: [
      [0, 6, 'Open Review Files for a real local session with simulated cloud mirror metadata.'],
      [6, 16, 'Inspect available Cloud Storage downloads for the batch ZIP and MSF artifacts.'],
      [16, 26, 'Refresh the mirror check and confirm both synthetic Dropbox objects are available.'],
      [26, 38, 'Open a temporary provider download URL served by the safe recording fixture.'],
      [38, 46, 'No cloud token, refresh token, private link, or production account is exposed.'],
    ],
    async interact(page, evidenceTexts) {
      const fixture = await ensureSessionRecordFixture()
      const cloudPayload = {
        success: true,
        data: {
          session_id: fixture.session_id,
          available: true,
          reason: null,
          items: [
            {
              id: 90001,
              session_id: fixture.session_id,
              artifact_kind: 'batch_zip',
              original_filename: 'bronze_helmet_release_fixture.zip',
              storage_provider: 'dropbox',
              cloud_path: '/webhdp-release-fixtures/bronze_helmet_release_fixture.zip',
              status: 'available',
              label: 'Batch ZIP',
              can_download: true,
              availability_status: 'available',
              availability_message: 'Dropbox mirror is available from simulated release storage.',
            },
            {
              id: 90002,
              session_id: fixture.session_id,
              artifact_kind: 'msf',
              original_filename: 'bronze_helmet_release_fixture.msf.xlsx',
              storage_provider: 'dropbox',
              cloud_path: '/webhdp-release-fixtures/bronze_helmet_release_fixture.msf.xlsx',
              status: 'available',
              label: 'MSF',
              can_download: true,
              availability_status: 'available',
              availability_message: 'Dropbox mirror is available from simulated release storage.',
            },
          ],
        },
      }
      await page.route(`**/api/v1/sessions/${fixture.session_id}/cloud-downloads`, async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(cloudPayload) })
      })
      await page.route(`**/api/v1/sessions/${fixture.session_id}/cloud-downloads/90001**`, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: {
              mirror: cloudPayload.data.items[0],
              download_url: 'https://example.invalid/webhdp-cloud-mirror/bronze_helmet_release_fixture.zip',
            },
          }),
        })
      })
      await page.route('https://example.invalid/webhdp-cloud-mirror/**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'text/html',
          body: '<!doctype html><title>Simulated Cloud Storage Download</title><main style="font:16px system-ui;padding:32px"><h1>Simulated Cloud Storage Download</h1><p>Temporary provider URL resolved for bronze_helmet_release_fixture.zip.</p><p>No credentials or private provider links are present in this recording fixture.</p></main>',
        })
      })
      await page.goto(`${BASE_URL}/workflow/files?sessionId=${fixture.session_id}&resume=workflow`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Review Files' }).waitFor({ timeout: 30000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.getByTestId('cloud-downloads-panel').waitFor({ timeout: 30000 })
      await page.waitForTimeout(3600)
      await page.getByRole('button', { name: 'Refresh' }).first().click()
      await page.getByText('bronze_helmet_release_fixture.zip').waitFor({ timeout: 15000 })
      await page.waitForTimeout(5200)
      evidenceTexts.push(await page.locator('body').innerText())
      await page.getByTestId('cloud-download-button').first().click()
      await page.waitForURL('https://example.invalid/webhdp-cloud-mirror/bronze_helmet_release_fixture.zip', { timeout: 15000 })
      await page.waitForTimeout(5200)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      const normalized = text.toLowerCase()
      return (
        text.includes('Review Files')
        && text.includes('Cloud Storage downloads')
        && text.includes('Mirrored upload artifacts are available from Cloud Storage')
        && text.includes('bronze_helmet_release_fixture.zip')
        && text.includes('Batch ZIP')
        && text.includes('bronze_helmet_release_fixture.msf.xlsx')
        && text.includes('MSF')
        && normalized.includes('available')
        && normalized.includes('dropbox mirror is available from simulated release storage')
        && text.includes('Simulated Cloud Storage Download')
        && !/DROPBOX_REFRESH_TOKEN=.+/i.test(text)
        && !/GOOGLE_APPLICATION_CREDENTIALS=.+/i.test(text)
        && !/Bearer\s+[A-Za-z0-9._-]+/i.test(text)
      )
    },
  },
  {
    id: 'webhdp_real_21_admin_observability_troubleshooting',
    route: '/settings/observability/credentials',
    allowCredentialLabels: true,
    subtitles: [
      [0, 7, 'Open masked integration status and inspect the Dropbox readiness row.'],
      [7, 17, 'Run a safe Dropbox check in the clone; it reports missing local configuration only.'],
      [17, 29, 'Filter API activity to cloud-storage server errors for the same symptom.'],
      [29, 41, 'Open notification delivery evidence and filter to failed attempts.'],
      [41, 50, 'The admin sees an actionable troubleshooting trail without secrets or private endpoints.'],
    ],
    async interact(page, evidenceTexts) {
      ensureAdminObservabilityFixture()
      await page.getByRole('heading', { name: 'Credentials & Integrations' }).waitFor({ timeout: 30000 })
      await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
      await page.getByRole('heading', { name: 'Dropbox' }).scrollIntoViewIfNeeded()
      await page.waitForTimeout(3600)
      const dropboxSection = page.locator('section').filter({ hasText: 'Dropbox' }).first()
      await dropboxSection.getByRole('button', { name: 'Run Check' }).click()
      await page.getByText('Missing environment variables').waitFor({ timeout: 30000 })
      await page.waitForTimeout(5200)
      evidenceTexts.push(await page.locator('body').innerText())

      await page.goto(`${BASE_URL}/settings/observability/api-activity`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'API & Integration Activity' }).waitFor({ timeout: 30000 })
      await page.locator('select').nth(0).selectOption('admin')
      await page.locator('select').nth(1).selectOption('cloud_storage')
      await page.locator('select').nth(2).selectOption('server_error')
      await page.getByRole('button', { name: 'Apply Filters' }).click()
      await page.getByText('/api/v1/admin/cloud/test/dropbox').first().waitFor({ timeout: 15000 })
      await page.waitForTimeout(6200)
      evidenceTexts.push(await page.locator('body').innerText())

      await page.goto(`${BASE_URL}/settings/observability/notifications`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: 'Notification Delivery' }).waitFor({ timeout: 30000 })
      await page.locator('select').nth(1).selectOption('failed')
      await page.getByRole('button', { name: 'Apply Filters' }).click()
      await page.getByText('SMTP host is not configured in the release clone').waitFor({ timeout: 15000 })
      await page.waitForTimeout(6200)
      evidenceTexts.push(await page.locator('body').innerText())
    },
    validate(text) {
      const normalized = text.toLowerCase()
      return (
        text.includes('Credentials & Integrations')
        && text.includes('Dropbox')
        && normalized.includes('not configured')
        && normalized.includes('missing environment variables')
        && text.includes('API & Integration Activity')
        && text.includes('/api/v1/admin/cloud/test/dropbox')
        && text.includes('cloud_storage')
        && text.includes('503')
        && text.includes('server_error')
        && text.includes('Notification Delivery')
        && text.includes('failed')
        && text.includes('SMTP host is not configured in the release clone')
        && !/DROPBOX_REFRESH_TOKEN=.+/i.test(text)
        && !/ZENODO_[A-Z_]*API_KEY=.+/i.test(text)
        && !/Bearer\s+[A-Za-z0-9._-]+/i.test(text)
      )
    },
  },
]

const requestedRecordingIds = new Set(
  String(process.env.WEBHDP_RECORDING_ONLY || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean),
)

function dockerExecPython(source) {
  return execFileSync(
    'docker',
    [...COMPOSE, 'exec', '-T', 'backend', 'python', '-c', source],
    { cwd: CLONE_ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] },
  ).trim().split(/\n/).pop()
}

function recordingAdminToken() {
  return dockerExecPython(`from app import app
from database.models import User
from routes.auth_routes import _create_access_token_for_user
with app.app_context():
    user = User.query.filter_by(email="recording-admin@example.test").first() or User.query.filter_by(email="alpha-admin@example.test").first() or User.query.first()
    print(_create_access_token_for_user(user))
`)
}

function ensureRenderUsdzFixture() {
  return JSON.parse(dockerExecPython(`from app import app
from database.database import db
from database.models import User, Session, File
from pathlib import Path
import json, shutil
with app.app_context():
    user = User.query.filter_by(email="recording-admin@example.test").first() or User.query.filter_by(email="alpha-admin@example.test").first() or User.query.first()
    root = Path("/shared/sessions/recording-render-usdz-session")
    source = root / "source_files"
    source.mkdir(parents=True, exist_ok=True)
    src = Path("/app/test_model.glb")
    dst = source / "test_model.glb"
    shutil.copyfile(src, dst)
    session = Session.query.filter_by(session_dir=str(root)).first()
    if not session:
        session = Session(user_id=user.id, session_dir=str(root), hdpc_path=str(root / "session.hdpc"), status="scanned", origin_type="recording_fixture", access_mode="full")
        db.session.add(session)
        db.session.flush()
    session.status = "scanned"
    file_row = File.query.filter_by(session_id=session.id, filename="test_model.glb").first()
    if not file_row:
        file_row = File(session_id=session.id, filename="test_model.glb", path=str(dst), size=dst.stat().st_size, status="uploaded")
        db.session.add(file_row)
    else:
        file_row.path = str(dst)
        file_row.size = dst.stat().st_size
        file_row.status = "uploaded"
    db.session.commit()
    print(json.dumps({"session_id": session.id, "path": "source_files/test_model.glb"}))
`))
}

async function prepareMsfUploadFixture() {
  const fixtureRoot = '/tmp/webhdp-msf-recording-fixture'
  const filesRoot = path.join(fixtureRoot, 'files')
  const zipPath = path.join(fixtureRoot, 'webhdp_alpha_models.zip')
  const msfPath = path.join(fixtureRoot, 'webhdp_alpha_msf_messy.csv')

  await fs.rm(fixtureRoot, { recursive: true, force: true })
  await fs.mkdir(filesRoot, { recursive: true })
  await fs.cp(path.join(ROOT, 'test_data', 'workflow_fixtures', 'cases', 'root_stem_mixed'), filesRoot, { recursive: true })
  await fs.cp(path.join(ROOT, 'test_data', 'workflow_fixtures', 'cases', 'core_identifier_via_pattern'), filesRoot, { recursive: true })
  await fs.writeFile(msfPath, `Identifier,Filename,Title,Description,Creator,Creator Affiliation,dcterms:created,Related to,dc:type,dcterms:extent (MB),Reference System,Units
1, ./temple_column.obj ,Fixture Temple Column,Root stem OBJ bundle fixture.,WebHDP Fixtures,WebHDP Test Lab,2026-01-01,not applicable,virtual models,1,not applicable,meters
2,ceramic_bowl.fbx,Fixture Ceramic Bowl,Root stem FBX fixture.,WebHDP Fixtures,WebHDP Test Lab,2026-01-01,not applicable,virtual models,1,not applicable,meters
3,bronze_helmet.glb,Fixture Bronze Helmet,Root stem GLB fixture.,WebHDP Fixtures,WebHDP Test Lab,2026-01-01,not applicable,virtual models,4,not applicable,meters
4,site042_structure_detail.obj,Fixture Site 042 Detail,Core identifier OBJ fixture.,WebHDP Fixtures,WebHDP Test Lab,2026-01-01,Identifier 5,virtual models,1,not applicable,meters
5,site093_artifact_complete.glb,Fixture Site 093 Complete,Core identifier FBX fixture with repairable extension mismatch.,WebHDP Fixtures,WebHDP Test Lab,2026-01-01,Identifier 7,virtual models,4,not applicable,meters
6,site093_artifact_fragment.obj,Fixture Site 093 Fragment,Core identifier OBJ fixture.,WebHDP Fixtures,WebHDP Test Lab,2026-01-01,Identifier 6,virtual models,1,not applicable,meters
6,site093_artifact_fragment.obj,,Duplicate fragment row contributes missing metadata and is merged by preflight.,WebHDP Fixtures,WebHDP Test Lab,2026-01-01,Identifier 6,virtual models,1,not applicable,meters
`, 'utf8')
  execFileSync('zip', ['-qr', zipPath, '.'], { cwd: filesRoot, stdio: 'ignore' })
  return { zipPath, msfPath }
}

async function ensurePipelineExecutionFixture() {
  const { zipPath, msfPath } = await prepareMsfUploadFixture()
  const token = recordingAdminToken()
  const formData = new FormData()
  formData.append(
    'zip_file',
    new Blob([await fs.readFile(zipPath)], { type: 'application/zip' }),
    'webhdp_alpha_models.zip',
  )
  formData.append(
    'msf_file',
    new Blob([await fs.readFile(msfPath)], { type: 'text/csv' }),
    'webhdp_alpha_msf_messy.csv',
  )
  formData.append('submit_token', `recording-pipeline-${Date.now()}`)

  const response = await fetch(`${BASE_URL}/api/v1/sessions/directory`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  })
  const payload = await response.json()
  if (!response.ok || payload.success === false) {
    throw new Error(`Failed to create pipeline fixture upload session: ${JSON.stringify(payload.error || payload)}`)
  }

  const sessionId = payload.data?.session_id
  const taskId = payload.data?.task_id
  if (!sessionId) {
    throw new Error('Pipeline fixture upload did not return a session ID.')
  }

  if (taskId) {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      const taskResponse = await fetch(`${BASE_URL}/api/v1/sessions/tasks/${taskId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      const taskPayload = await taskResponse.json()
      const state = taskPayload.data?.state || taskPayload.state
      const status = taskPayload.data?.status || taskPayload.status
      if (state === 'SUCCESS' || state === 'coordinator_completed') {
        if (status === 'failed') {
          throw new Error(taskPayload.data?.error || taskPayload.error || 'Pipeline fixture upload coordinator failed.')
        }
        break
      }
      if (state === 'FAILURE') {
        throw new Error(taskPayload.data?.error || taskPayload.error || 'Pipeline fixture upload coordinator failed.')
      }
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  }

  for (let attempt = 0; attempt < 120; attempt += 1) {
    const progressResponse = await fetch(`${BASE_URL}/api/v1/sessions/${sessionId}/progress`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const progressPayload = await progressResponse.json()
    const data = progressPayload.data || progressPayload
    const uploadProgress = data.upload_progress || {}
    const currentStage = uploadProgress.current_stage || data.current_stage
    const percent = uploadProgress.percent ?? data.percent ?? 0
    if (currentStage === 'failed') {
      throw new Error(uploadProgress.status_message || 'Pipeline fixture upload failed.')
    }
    if (percent >= 100) {
      break
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  for (let attempt = 0; attempt < 120; attempt += 1) {
    const fixtureState = JSON.parse(dockerExecPython(`from app import app
from database.models import File, Session
from pathlib import Path
import json, sqlite3
with app.app_context():
    session = Session.query.get(${Number(sessionId)})
    file_row = File.query.filter_by(session_id=${Number(sessionId)}, filename="bronze_helmet.glb").first()
    record_id = None
    record_count = 0
    hdpc_path = Path(session.hdpc_path or "") if session else Path("")
    if hdpc_path.exists():
        con = sqlite3.connect(str(hdpc_path))
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT record_id FROM zenodo_records ORDER BY record_id LIMIT 1").fetchone()
            record_count = con.execute("SELECT COUNT(*) FROM zenodo_records").fetchone()[0]
            record_id = int(row["record_id"]) if row else None
        finally:
            con.close()
    print(json.dumps({
        "ready": bool(file_row and record_id),
        "session_id": ${Number(sessionId)},
        "file_path": file_row.path if file_row else None,
        "record_id": record_id,
        "record_count": record_count,
    }))
`))
    if (fixtureState.ready) {
      return fixtureState
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  throw new Error(`Pipeline fixture session ${sessionId} did not create HDPC records in time.`)
}

async function ensureSessionRecordFixture() {
  const existing = JSON.parse(dockerExecPython(`from app import app
from database.models import File, Session
from pathlib import Path
import json, sqlite3
with app.app_context():
    result = None
    for session in Session.query.filter(Session.hdpc_path.isnot(None)).order_by(Session.id.desc()).limit(20):
        hdpc_path = Path(session.hdpc_path or "")
        if not hdpc_path.exists():
            continue
        con = sqlite3.connect(str(hdpc_path))
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT record_id FROM zenodo_records ORDER BY record_id LIMIT 1").fetchone()
            record_count = con.execute("SELECT COUNT(*) FROM zenodo_records").fetchone()[0]
        finally:
            con.close()
        file_row = File.query.filter_by(session_id=session.id, filename="bronze_helmet.glb").first()
        if row and file_row:
            result = {
                "ready": True,
                "session_id": session.id,
                "file_path": file_row.path,
                "record_id": int(row["record_id"]),
                "record_count": int(record_count),
            }
            break
    print(json.dumps(result or {"ready": False}))
`))
  if (existing.ready) {
    return existing
  }
  return ensurePipelineExecutionFixture()
}

function ensurePersistedEdmValidationFixture() {
  const fixture = ensureSessionRecordFixtureSync()
  return JSON.parse(dockerExecPython(`from app import app
from database.models import Session
from services.hdpc_local_service import add_local_source_files
from pathlib import Path
from datetime import datetime, timezone
import json, sqlite3

EDM_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/">
  <edm:ProvidedCHO rdf:about="https://webhdp.example.test/recording/bronze-helmet">
    <dc:title>Fixture Bronze Helmet</dc:title>
    <dc:description>Release recording fixture for persisted EDM validation evidence.</dc:description>
    <dc:creator>WebHDP Test Lab</dc:creator>
    <dc:type>3D model</dc:type>
    <dcterms:created>2026-01-01</dcterms:created>
  </edm:ProvidedCHO>
  <edm:WebResource rdf:about="https://webhdp.example.test/files/bronze_helmet.glb">
    <dc:format>model/gltf-binary</dc:format>
  </edm:WebResource>
  <ore:Aggregation rdf:about="https://webhdp.example.test/aggregation/bronze-helmet">
    <edm:aggregatedCHO rdf:resource="https://webhdp.example.test/recording/bronze-helmet"/>
    <edm:isShownBy rdf:resource="https://webhdp.example.test/files/bronze_helmet.glb"/>
    <edm:provider>WebHDP</edm:provider>
    <edm:dataProvider>WebHDP Test Lab</edm:dataProvider>
    <edm:rights rdf:resource="http://creativecommons.org/licenses/by/4.0/"/>
  </ore:Aggregation>
</rdf:RDF>
'''

def report_steps(report):
    details = report.get("details") if isinstance(report, dict) else {}
    result = []
    for key, label in (
        ("basic", "Basic XML"),
        ("xsd", "XSD"),
        ("schematron", "Schematron"),
        ("business", "Business Rules"),
        ("remote", "Local EDM Validator"),
    ):
        detail = details.get(key) if isinstance(details, dict) else None
        if isinstance(detail, dict):
            result.append({
                "name": label,
                "valid": bool(detail.get("valid", True)),
                "errors": detail.get("errors") or [],
                "warnings": detail.get("warnings") or [],
            })
    return result

with app.app_context():
    session = Session.query.get(${Number(fixture.session_id)})
    if session is None or not session.hdpc_path:
        raise RuntimeError("Recording session with .hdpc was not found.")
    hdpc_path = Path(session.hdpc_path)
    output_dir = Path(session.session_dir) / "data_out" / "recording-edm-validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    edm_path = output_dir / "edm.xml"
    validation_path = output_dir / "edm.validation.json"
    report = app.edm_service.validate_edm_document(
        EDM_XML,
        metadata={
            "title": "Fixture Bronze Helmet",
            "description": "Release recording fixture for persisted EDM validation evidence.",
            "creator": "WebHDP Test Lab",
            "language": "en",
            "country": "DE",
        },
        include_remote=False,
    )
    report["validator"] = "Local EDM Validator"
    report["profile"] = "EDM"
    report["recording_fixture"] = True
    report["validated_at"] = datetime.now(timezone.utc).isoformat()
    report["steps"] = report_steps(report)
    edm_path.write_text(EDM_XML, encoding="utf-8")
    validation_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    add_local_source_files(
        str(hdpc_path),
        absolute_file_paths=[str(edm_path), str(validation_path)],
        record_id_to_associate=${Number(fixture.record_id)},
        pipeline_name="metadata_validation",
        step_name="local_edm_validator",
        validation_reports={str(edm_path): report},
    )
    con = sqlite3.connect(str(hdpc_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT file_id, filename, relative_path, absolute_path FROM source_files WHERE absolute_path IN (?, ?)",
            (str(edm_path), str(validation_path)),
        ).fetchall()
        for row in rows:
            purpose = "metadata" if row["filename"] == "edm.xml" else "validation_report"
            con.execute(
                """
                INSERT INTO record_files_map (record_id, file_id, file_path, file_purpose, upload_status, upload_timestamp)
                VALUES (?, ?, ?, ?, 'local', CURRENT_TIMESTAMP)
                ON CONFLICT(record_id, file_id) DO UPDATE SET
                  file_path = excluded.file_path,
                  file_purpose = excluded.file_purpose,
                  upload_status = excluded.upload_status,
                  upload_timestamp = excluded.upload_timestamp
                """,
                (${Number(fixture.record_id)}, int(row["file_id"]), row["relative_path"] or row["absolute_path"], purpose),
            )
        con.commit()
        report_rows = con.execute(
            """
            SELECT sf.file_id, sf.filename, sf.relative_path, sf.validation_report_json
            FROM source_files sf
            JOIN record_files_map rfm ON rfm.file_id = sf.file_id
            WHERE rfm.record_id = ? AND sf.filename = 'edm.xml'
            """,
            (${Number(fixture.record_id)},),
        ).fetchall()
    finally:
        con.close()
    if not report_rows:
        raise RuntimeError("Persisted EDM validation report was not linked to the record.")
    print(json.dumps({
        "session_id": ${Number(fixture.session_id)},
        "record_id": ${Number(fixture.record_id)},
        "edm_path": str(edm_path),
        "valid": bool(report.get("valid", False)),
        "report_count": len(report_rows),
    }))
`))
}

function ensureSessionRecordFixtureSync() {
  return JSON.parse(dockerExecPython(`from app import app
from database.models import File, Session
from pathlib import Path
import json, sqlite3
with app.app_context():
    result = None
    for session in Session.query.filter(Session.hdpc_path.isnot(None)).order_by(Session.id.desc()).limit(30):
        hdpc_path = Path(session.hdpc_path or "")
        if not hdpc_path.exists():
            continue
        con = sqlite3.connect(str(hdpc_path))
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT record_id FROM zenodo_records ORDER BY record_id LIMIT 1").fetchone()
        finally:
            con.close()
        file_row = File.query.filter_by(session_id=session.id, filename="bronze_helmet.glb").first()
        if row and file_row:
            result = {
                "ready": True,
                "session_id": session.id,
                "file_path": file_row.path,
                "record_id": int(row["record_id"]),
            }
            break
    print(json.dumps(result or {"ready": False}))
`))
}

function readPipelineFixtureFilePath(sessionId) {
  return JSON.parse(dockerExecPython(`from app import app
from database.models import File
import json
with app.app_context():
    file_row = File.query.filter_by(session_id=${Number(sessionId)}, filename="bronze_helmet.glb").first()
    if not file_row:
        raise SystemExit("bronze_helmet.glb not found in pipeline fixture session")
    print(json.dumps({"session_id": ${Number(sessionId)}, "file_path": file_row.path}))
`))
}

function cleanupRecordingZenodoCredentials() {
  dockerExecPython(`from app import app
from database.database import db
from database.models import User, UserZenodoActiveCredential, ZenodoCredential
with app.app_context():
    user = User.query.filter_by(email="recording-admin@example.test").first() or User.query.filter_by(email="alpha-admin@example.test").first() or User.query.first()
    if user:
        credentials = ZenodoCredential.query.filter_by(owner_type="user", owner_id=user.id, name="Recording Sandbox Key").all()
        for credential in credentials:
            UserZenodoActiveCredential.query.filter_by(credential_id=credential.id).delete()
            db.session.delete(credential)
        db.session.commit()
    print("ok")
`)
}

function markRecordingZenodoCredentialSafeValid() {
  return JSON.parse(dockerExecPython(`from app import app
from database.database import db
from database.models import User, UserZenodoActiveCredential, ZenodoCredential
from services.zenodo_credential_service import ZenodoCredentialService
from datetime import datetime
import json
with app.app_context():
    user = User.query.filter_by(email="recording-admin@example.test").first() or User.query.filter_by(email="alpha-admin@example.test").first() or User.query.first()
    credential = ZenodoCredential.query.filter_by(owner_type="user", owner_id=user.id, environment="sandbox", name="Recording Sandbox Key").order_by(ZenodoCredential.id.desc()).first()
    if not credential:
        raise SystemExit("Recording Sandbox Key was not created")
    report = {
        "mode": "safe_advisory",
        "environment": "sandbox",
        "aggregate_status": "valid",
        "summary": "Safe recording fixture: the sandbox credential workflow was exercised with a hidden password field and masked storage. No live Zenodo token is exposed in this release walkthrough.",
        "recommended_scopes": ["deposit:write", "deposit:actions"],
        "capabilities": {
            "authentication": {"status": "verified", "message": "Credential is present in encrypted storage and is only shown as a masked preview."},
            "deposit_api_access": {"status": "verified", "message": "Sandbox endpoint configuration is selected for this key."},
            "deposit_write": {"status": "verified", "message": "Required write scope is documented for sandbox publication workflows."},
            "deposit_actions": {"status": "verified", "message": "Required action scope is documented for draft cleanup and publication workflows."},
            "community_moderation": {"status": "unverified", "message": "Community moderation is not required for this alpha recording."}
        },
    }
    credential.validation_status = "valid"
    credential.last_validation_error = None
    credential.last_validation_report = json.dumps(report, sort_keys=True)
    credential.last_validated_at = datetime.utcnow()
    row = UserZenodoActiveCredential.query.filter_by(user_id=user.id, environment="sandbox").first()
    if not row:
        row = UserZenodoActiveCredential(user_id=user.id, environment="sandbox", credential_id=credential.id)
        db.session.add(row)
    else:
        row.credential_id = credential.id
        row.updated_at = datetime.utcnow()
    db.session.commit()
    print(json.dumps(ZenodoCredentialService().serialize_for_user(credential, user.id)))
`))
}

function ensureZenodoAccountRetrievalFixture() {
  return JSON.parse(dockerExecPython(`from app import app
from database.database import db
from database.models import User, UserZenodoActiveCredential, ZenodoCredential
from services.zenodo_credential_service import ZenodoCredentialService
from services.zenodo_account_retrieval_history_service import get_retrieval_entry, record_retrieval_launch, update_retrieval_entry
from services.zenodo_account_retrieval_service import write_retrieval_shard
from datetime import datetime
import json

RETRIEVAL_ID = "recording-zenodo-account-retrieval"

with app.app_context():
    entry = get_retrieval_entry(RETRIEVAL_ID)
    if isinstance(entry, dict) and (entry.get("manifest") or {}).get("shards"):
        print(json.dumps({
            "retrieval_id": RETRIEVAL_ID,
            "credential_id": int(entry.get("credential_id") or 0),
            "shards": (entry.get("manifest") or {}).get("shards") or [],
        }))
        raise SystemExit(0)

    user = (
        User.query.filter_by(email="recording-admin@example.test").first()
        or User.query.filter_by(email="alpha-admin@example.test").first()
        or User.query.order_by(User.id.asc()).first()
    )
    if not user:
        raise SystemExit("No recording user is available for Zenodo retrieval fixture")

    for credential in ZenodoCredential.query.filter_by(
        owner_type="user",
        owner_id=user.id,
        environment="sandbox",
        name="Recording Retrieval Sandbox Key",
    ).all():
        UserZenodoActiveCredential.query.filter_by(credential_id=credential.id).delete()
        db.session.delete(credential)
    db.session.commit()

    credential = ZenodoCredentialService().create_credential(
        user_id=user.id,
        environment="sandbox",
        token="sbx-retrieval-recording-token-do-not-use-0000",
        name="Recording Retrieval Sandbox Key",
        actor_user_id=user.id,
    )
    credential.validation_status = "valid"
    credential.last_validation_error = None
    credential.last_validation_report = json.dumps({
        "mode": "safe_synthetic_retrieval_fixture",
        "environment": "sandbox",
        "aggregate_status": "valid",
        "summary": "Safe recording fixture. The token is synthetic, masked, and never written to retrieval shards.",
    }, sort_keys=True)
    credential.last_validated_at = datetime.utcnow()
    row = UserZenodoActiveCredential.query.filter_by(user_id=user.id, environment="sandbox").first()
    if row:
        row.credential_id = credential.id
        row.updated_at = datetime.utcnow()
    else:
        db.session.add(UserZenodoActiveCredential(user_id=user.id, environment="sandbox", credential_id=credential.id))
    db.session.commit()

    window = {"status": "published", "start": "2026-04-01T00:00:00Z", "end": "2026-04-02T00:00:00Z"}
    records = [
        {
            "id": 9501,
            "created": "2026-04-01T12:00:00Z",
            "modified": "2026-04-01T12:10:00Z",
            "metadata": {
                "title": "Searchable amphora recording fixture",
                "description": "Synthetic Objaverse candidate for WebHDP release recording.",
                "communities": [],
                "creators": [{"name": "WebHDP Recording Fixture"}],
                "version": "1.0",
            },
            "files": [
                {"id": "file-9501", "filename": "amphora_model.glb", "filesize": 1024, "type": "model/gltf-binary"}
            ],
            "links": {"edit": "https://sandbox.zenodo.org/deposit/9501", "html": "https://sandbox.zenodo.org/records/9501"},
        },
        {
            "id": 9502,
            "created": "2026-04-01T13:00:00Z",
            "modified": "2026-04-01T13:10:00Z",
            "metadata": {
                "title": "Reference vessel recording fixture",
                "description": "Synthetic non-candidate retrieval record.",
                "communities": [{"identifier": "3dbigdataspace"}],
                "creators": [{"name": "WebHDP Recording Fixture"}],
            },
            "files": [
                {"id": "file-9502", "filename": "metadata.json", "filesize": 512, "type": "application/json"}
            ],
            "links": {"html": "https://sandbox.zenodo.org/records/9502"},
        },
    ]
    shard = write_retrieval_shard(
        retrieval_id=RETRIEVAL_ID,
        shard_index=1,
        environment="sandbox",
        requested_by=user,
        credential=credential,
        window=window,
        manifest_summary={
            "retrieval_id": RETRIEVAL_ID,
            "shard_index": 1,
            "sync_mode": "full",
            "retrieval_mode": "full",
            "record_count": 2,
        },
        records=records,
    )
    credential_summary = {
        "credential_id": int(credential.id),
        "name": credential.name,
        "environment": credential.environment,
        "owner_type": credential.owner_type,
        "owner_id": int(credential.owner_id),
        "relation": "owned_by_requesting_user",
        "masked_preview": credential.masked_preview,
        "validation_status": credential.validation_status,
    }
    preflight = {
        "ok": True,
        "queueable": True,
        "retrieval_mode": "full",
        "sync_mode": "full",
        "execution_target": "celery_local",
        "environment": "sandbox",
        "credential": credential_summary,
        "date_window": {"start": None, "end": None},
        "runtime_options": {"proxy_policy": "default"},
        "coverage": {
            "matching_collection_count": 1,
            "latest_known_created": "2026-04-01T13:00:00Z",
            "earliest_known_created": "2026-04-01T12:00:00Z",
            "requested_window": {"start": None, "end": None},
            "mode": "full",
        },
        "checks": [
            {"key": "credential_access", "status": "pass", "label": "Credential is accessible to the requesting user"},
            {"key": "token_handling", "status": "pass", "label": "Token is decrypted only in the worker context and kept out of shard output"},
            {"key": "worker_proxy_policy", "status": "info", "label": "Local/Celery worker proxy environment will be inherited"},
        ],
        "warnings": [],
    }
    record_retrieval_launch(
        retrieval_id=RETRIEVAL_ID,
        task_id=None,
        credential_id=int(credential.id),
        environment="sandbox",
        requested_by_user_id=int(user.id),
        requested_by_email=user.email,
        credential_summary=credential_summary,
        max_records=2,
        sync_mode="full",
        retrieval_mode="full",
        execution_target="celery_local",
        runtime_options={"proxy_policy": "default", "token_source": "credential"},
        preflight_report=preflight,
    )
    update_retrieval_entry(
        RETRIEVAL_ID,
        state="SUCCESS",
        status="completed",
        progress={
            "processed_windows": 1,
            "pending_windows": 0,
            "retrieved_records": 2,
            "created_shards": 1,
            "published_records": 2,
            "draft_records": 0,
            "rate_limited_waits": 0,
            "percent": 100,
            "max_records": 2,
            "records_per_hour": 120,
            "pages_per_hour": 60,
            "eta_seconds": 0,
            "latest_created": "2026-04-01T13:00:00Z",
        },
        summary={
            "retrieved_records": 2,
            "created_shards": 1,
            "published_records": 2,
            "draft_records": 0,
            "failed_windows": 0,
            "rate_limited_waits": 0,
            "max_records": 2,
            "limit_reached": True,
            "earliest_created": "2026-04-01T12:00:00Z",
            "latest_created": "2026-04-01T13:00:00Z",
            "latest_modified": "2026-04-01T13:10:00Z",
            "wait_seconds": 0,
        },
        manifest={"retrieval_id": RETRIEVAL_ID, "sync_mode": "full", "shards": [shard]},
        runtime={"execution_target": "celery_local", "proxy_policy": "default", "token_source": "credential", "script_version": "recording-fixture"},
        preflight=preflight,
    )
    print(json.dumps({"retrieval_id": RETRIEVAL_ID, "credential_id": int(credential.id), "shards": [shard]}))
`))
}

function ensureAdminObservabilityFixture() {
  return JSON.parse(dockerExecPython(`from app import app
from database.database import db
from database.models import Notification, NotificationDelivery, SystemConfig, User
from services.api_activity_service import record_api_activity
from services.admin_observability_service import AdminObservabilityService
from datetime import datetime, timezone
import json

with app.app_context():
    user = (
        User.query.filter_by(email="recording-admin@example.test").first()
        or User.query.filter_by(email="alpha-admin@example.test").first()
        or User.query.order_by(User.id.asc()).first()
    )
    if not user:
        raise SystemExit("No recording user is available for admin observability fixture")

    now = datetime.now(timezone.utc).isoformat()
    stored = AdminObservabilityService._load_check_results()
    stored["dropbox"] = {
        "status": "Missing environment variables: DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN",
        "ok": False,
        "details": {"refresh_token_present": False},
        "checked_at": now,
    }
    AdminObservabilityService._save_check_results(stored)

    record_api_activity({
        "timestamp": now,
        "method": "GET",
        "path": "/api/v1/admin/cloud/test/dropbox",
        "route_family": "admin",
        "service": "cloud_storage",
        "status_code": 503,
        "status_class": "server_error",
        "duration_ms": 348,
        "user_id": user.id,
        "request_id": "recording-cloud-storage-failure",
    })
    record_api_activity({
        "timestamp": now,
        "method": "GET",
        "path": "/api/v1/admin/observability/credentials-status",
        "route_family": "admin",
        "service": "webhdp",
        "status_code": 200,
        "status_class": "success",
        "duration_ms": 42,
        "user_id": user.id,
        "request_id": "recording-observability-status",
    })

    dedupe_key = "recording-observability-failed-email"
    notification = Notification.query.filter_by(dedupe_key=dedupe_key).first()
    if not notification:
        notification = Notification(
            recipient_user_id=user.id,
            notification_type="admin.observability.recording",
            category="admin",
            severity="warning",
            title="Cloud storage readiness check failed",
            body="Dropbox cloud storage is not configured in the release clone.",
            action_url="/settings/observability/credentials",
            payload_json=json.dumps({"recording_fixture": True}, sort_keys=True),
            dedupe_key=dedupe_key,
            email_status="failed",
            email_error="SMTP host is not configured in the release clone.",
        )
        db.session.add(notification)
        db.session.flush()
    else:
        notification.email_status = "failed"
        notification.email_error = "SMTP host is not configured in the release clone."

    delivery = NotificationDelivery.query.filter_by(notification_id=notification.id, channel="email", status="failed").first()
    if not delivery:
        delivery = NotificationDelivery(
            notification_id=notification.id,
            recipient_user_id=user.id,
            channel="email",
            status="failed",
            batch_key="recording-observability",
            error="SMTP host is not configured in the release clone.",
        )
        db.session.add(delivery)
    else:
        delivery.error = "SMTP host is not configured in the release clone."
        delivery.created_at = datetime.utcnow()
    db.session.commit()
    print(json.dumps({"ready": True, "user_id": int(user.id), "notification_id": int(notification.id)}))
`))
}

function shell(command, options = {}) {
  return execFileSync(
    'bash',
    ['-lc', command],
    {
      cwd: options.cwd || ROOT,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: options.timeout || 120000,
      maxBuffer: options.maxBuffer || 1024 * 1024 * 20,
    },
  )
}

function prepareInstallRecordingRemote() {
  const snapshot = path.join(INSTALL_RECORDING_ROOT, 'snapshot')
  const remoteParent = path.join(INSTALL_RECORDING_ROOT, 'remote')
  const remote = path.join(remoteParent, 'webhdp.git')
  shell(`rm -rf ${JSON.stringify(INSTALL_RECORDING_ROOT)} && mkdir -p ${JSON.stringify(snapshot)} ${JSON.stringify(remoteParent)}`)
  shell([
    'rsync -a',
    '--exclude .git',
    '--exclude .env',
    '--exclude .venv',
    '--exclude node_modules',
    '--exclude frontend/node_modules',
    '--exclude hpc-link/frontend/node_modules',
    '--exclude hdp-shared',
    '--exclude artifacts',
    '--exclude reports',
    '--exclude unsorted_test_files',
    '--exclude instance',
    '--exclude logs',
    '--exclude .tmp-recordings',
    '--exclude external_code/local-edm-validator',
    `${JSON.stringify(`${ROOT}/`)}`,
    `${JSON.stringify(`${snapshot}/`)}`,
  ].join(' '))
  shell('git init -q && git config user.email recording@example.test && git config user.name "WebHDP Recording" && git add -A && git commit -q -m "release candidate snapshot"', { cwd: snapshot })
  shell(`git clone --bare ${JSON.stringify(snapshot)} ${JSON.stringify(remote)}`)
  return remote
}

function prepareSetupRecordingRemote() {
  const snapshot = path.join(SETUP_RECORDING_ROOT, 'snapshot')
  const remoteParent = path.join(SETUP_RECORDING_ROOT, 'remote')
  const remote = path.join(remoteParent, 'webhdp.git')
  shell(`rm -rf ${JSON.stringify(SETUP_RECORDING_ROOT)} && mkdir -p ${JSON.stringify(snapshot)} ${JSON.stringify(remoteParent)}`)
  shell([
    'rsync -a',
    '--exclude .git',
    '--exclude .env',
    '--exclude .venv',
    '--exclude node_modules',
    '--exclude frontend/node_modules',
    '--exclude hpc-link/frontend/node_modules',
    '--exclude hdp-shared',
    '--exclude artifacts',
    '--exclude reports',
    '--exclude unsorted_test_files',
    '--exclude instance',
    '--exclude logs',
    '--exclude .tmp-recordings',
    '--exclude external_code/local-edm-validator',
    `${JSON.stringify(`${ROOT}/`)}`,
    `${JSON.stringify(`${snapshot}/`)}`,
  ].join(' '))
  shell('git init -q && git config user.email recording@example.test && git config user.name "WebHDP Recording" && git add -A && git commit -q -m "release candidate snapshot"', { cwd: snapshot })
  shell(`git clone --bare ${JSON.stringify(snapshot)} ${JSON.stringify(remote)}`)
  return remote
}

function sanitizeTerminalOutput(text) {
  return String(text || '')
    .replaceAll(ROOT, '<source-worktree>')
    .replaceAll(CLONE_ROOT, '<clone-worktree>')
    .replaceAll(INSTALL_RECORDING_ROOT, '<install-check>')
    .replaceAll(SETUP_RECORDING_ROOT, '<setup-check>')
    .replace(/(SECRET_KEY|CREDENTIAL_ENCRYPTION_KEY|SETUP_BOOTSTRAP_TOKEN|DEFAULT_ADMIN_PASSWORD|ZENODO_SANDBOX_API_KEY|ZENODO_API_KEY|MAIL_PASSWORD)=\S*/gi, '$1=<redacted>')
}

async function ensureDirs() {
  await fs.mkdir(RAW_DIR, { recursive: true })
  await fs.mkdir(SUBTITLE_DIR, { recursive: true })
  await fs.mkdir(path.dirname(GUIDE_PATH), { recursive: true })
  await fs.mkdir(TEMP_VIDEO_DIR, { recursive: true })
}

function vttTime(seconds) {
  const whole = Math.floor(seconds)
  const millis = Math.round((seconds - whole) * 1000)
  const hh = String(Math.floor(whole / 3600)).padStart(2, '0')
  const mm = String(Math.floor((whole % 3600) / 60)).padStart(2, '0')
  const ss = String(whole % 60).padStart(2, '0')
  return `${hh}:${mm}:${ss}.${String(millis).padStart(3, '0')}`
}

async function writeSubtitles(recording) {
  const cues = recording.subtitles.map(([start, end, text]) => (
    `${vttTime(start)} --> ${vttTime(end)}\n${text}`
  )).join('\n\n')
  await fs.writeFile(path.join(SUBTITLE_DIR, `${recording.id}.en.vtt`), `WEBVTT\n\n${cues}\n`, 'utf8')
}

async function readManifest() {
  try {
    return JSON.parse(await fs.readFile(MANIFEST_PATH, 'utf8'))
  } catch {
    return { version: 1, updated: '2026-05-29', entries: [] }
  }
}

function manifestEntry(id) {
  return {
    id,
    title: RECORDING_METADATA[id].title,
    kind: 'real-alpha-recording',
    source_document: 'docs/guides/video_guides/release_walkthroughs.md',
    webm: `docs/assets/screen_recordings/raw/${id}.webm`,
    video: `docs/assets/screen_recordings/raw/${id}.mp4`,
    subtitles: `docs/assets/screen_recordings/subtitles/${id}.en.vtt`,
  }
}

async function writeManifestAndGuide() {
  await readManifest()
  const entriesById = new Map()
  for (const id of Object.keys(RECORDING_METADATA)) {
    if (!PUBLIC_WALKTHROUGH_IDS.has(id)) {
      continue
    }
    const webm = path.join(RAW_DIR, `${id}.webm`)
    const mp4 = path.join(RAW_DIR, `${id}.mp4`)
    const vtt = path.join(SUBTITLE_DIR, `${id}.en.vtt`)
    try {
      await Promise.all([fs.access(webm), fs.access(mp4), fs.access(vtt)])
      entriesById.set(id, manifestEntry(id))
    } catch {
      // Keep unrecorded metadata out of the release manifest.
    }
  }
  const entries = Array.from(entriesById.values()).sort((a, b) => a.id.localeCompare(b.id))
  await fs.writeFile(
    MANIFEST_PATH,
    `${JSON.stringify({ version: 1, updated: '2026-05-29', entries }, null, 2)}\n`,
    'utf8',
  )

  const sections = entries.map((entry) => {
    const meta = RECORDING_METADATA[entry.id]
    const evidence = meta.evidence.map((item, index) => `${index + 1}. ${item}`).join('\n')
    return `### ${meta.title}

Purpose: ${meta.purpose}

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/${entry.id}.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/${entry.id}.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/${entry.id}.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

Workflow evidence shown in the video:

${evidence}`
  }).join('\n\n')

  const guide = `# Release Walkthrough Videos

This page contains accepted alpha release walkthrough recordings. Each accepted
video must show a real, replayable workflow against a local WebHDP Docker
instance. Generated route tours and caption-only placeholders are not accepted.
Short admin/status verification clips are kept out of this public guide until
they have been replaced by coherent walkthroughs.

## Accepted Recordings

${sections}

## Additional Recordings

Add new recordings only after they show a complete workflow, use repeatable
local or synthetic data, and avoid credentials, private endpoints, and personal
filesystem paths.
`
  await fs.writeFile(GUIDE_PATH, guide, 'utf8')
}

async function recordWorkflow(recording) {
  const { chromium } = await import(path.join(ROOT, 'frontend', 'node_modules', 'playwright', 'index.mjs'))
  const token = recordingAdminToken()
  const videoDir = path.join(TEMP_VIDEO_DIR, recording.id)
  await fs.rm(videoDir, { recursive: true, force: true })
  await fs.mkdir(videoDir, { recursive: true })

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } },
  })
  await context.addInitScript((authToken) => {
    window.sessionStorage.setItem('token', authToken)
  }, token)
  const page = await context.newPage()
  await page.goto(`${BASE_URL}${recording.route}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
  const evidenceTexts = []
  await recording.interact(page, evidenceTexts)

  const text = `${await page.locator('body').innerText()} ${evidenceTexts.join(' ')}`.replace(/\s+/g, ' ')
  if (!recording.validate(text)) {
    await fs.writeFile(path.join(TEMP_VIDEO_DIR, `${recording.id}.failure.txt`), text, 'utf8')
    await page.screenshot({ path: path.join(TEMP_VIDEO_DIR, `${recording.id}.failure.png`), fullPage: true })
    throw new Error(`${recording.id} did not show the required evidence.`)
  }
  if (/token|password|secret/i.test(text) && !recording.allowCredentialLabels && !recording.id.includes('admin_session_monitoring')) {
    await fs.writeFile(path.join(TEMP_VIDEO_DIR, `${recording.id}.sensitive-review.txt`), text, 'utf8')
    throw new Error(`${recording.id} page text needs sensitive-data review before publishing.`)
  }

  await context.close()
  await browser.close()

  const files = await fs.readdir(videoDir)
  const recordedWebm = files.find((name) => name.endsWith('.webm'))
  if (!recordedWebm) {
    throw new Error(`Playwright did not produce a WebM recording for ${recording.id}.`)
  }
  const webmPath = path.join(RAW_DIR, `${recording.id}.webm`)
  const mp4Path = path.join(RAW_DIR, `${recording.id}.mp4`)
  await fs.copyFile(path.join(videoDir, recordedWebm), webmPath)
  execFileSync('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    webmPath,
    '-vf',
    'scale=1280:-2',
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    mp4Path,
  ], { stdio: 'inherit' })
  await writeSubtitles(recording)
  await fs.rm(videoDir, { recursive: true, force: true })
}

async function recordTerminalWorkflow(recording) {
  const { chromium } = await import(path.join(ROOT, 'frontend', 'node_modules', 'playwright', 'index.mjs'))
  const remote = prepareInstallRecordingRemote()
  const installRoot = path.join(INSTALL_RECORDING_ROOT, 'workspace')
  const repoDir = path.join(installRoot, 'webhdp')
  const projectName = 'webhdp-install-recording'
  const port = '18090'
  await fs.rm(installRoot, { recursive: true, force: true })
  await fs.mkdir(installRoot, { recursive: true })

  const videoDir = path.join(TEMP_VIDEO_DIR, recording.id)
  await fs.rm(videoDir, { recursive: true, force: true })
  await fs.mkdir(videoDir, { recursive: true })

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } },
  })
  const page = await context.newPage()
  await page.setContent(`<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; background: #111827; color: #e5e7eb; font: 16px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    main { padding: 28px; }
    .title { color: #f9fafb; font: 700 24px/1.2 system-ui, sans-serif; margin-bottom: 8px; }
    .subtitle { color: #9ca3af; font: 15px/1.4 system-ui, sans-serif; margin-bottom: 20px; }
    .terminal { background: #020617; border: 1px solid #334155; border-radius: 8px; padding: 18px; min-height: 720px; box-shadow: 0 24px 80px rgba(0,0,0,.35); white-space: pre-wrap; overflow-wrap: anywhere; }
    .prompt { color: #93c5fd; }
    .output { color: #d1d5db; }
    .ok { color: #86efac; }
    .note { color: #fde68a; }
    .error { color: #fca5a5; }
  </style>
</head>
<body>
  <main>
    <div class="title">WebHDP Clone And Docker Installation</div>
    <div class="subtitle">Release-candidate clone smoke test. Secrets are generated locally and never printed.</div>
    <div id="terminal" class="terminal"></div>
  </main>
  <script>
    window.appendLine = (text, className = 'output') => {
      const terminal = document.getElementById('terminal')
      const span = document.createElement('span')
      span.className = className
      span.textContent = text + "\\n"
      terminal.appendChild(span)
      window.scrollTo(0, document.body.scrollHeight)
    }
  </script>
</body>
</html>`, { waitUntil: 'domcontentloaded' })

  const transcript = []
  async function append(text, className = 'output') {
    const sanitized = sanitizeTerminalOutput(text)
    transcript.push(sanitized)
    await page.evaluate(([line, cls]) => window.appendLine(line, cls), [sanitized, className])
    await page.waitForTimeout(650)
  }
  async function run(command, options = {}) {
    await append(`$ ${sanitizeTerminalOutput(command)}`, 'prompt')
    try {
      const output = shell(command, {
        cwd: options.cwd || installRoot,
        timeout: options.timeout || 120000,
        maxBuffer: options.maxBuffer,
      })
      if (output.trim()) {
        await append(output.trim(), options.outputClass || 'output')
      }
      if (options.ok) {
        await append(options.ok, 'ok')
      }
      return output
    } catch (error) {
      const stderr = `${error.stdout || ''}\n${error.stderr || ''}`.trim()
      await append(stderr || String(error), 'error')
      throw error
    }
  }

  await append('This pre-publication recording clones from a local release-candidate remote. After publication, use: git clone https://github.com/Digital-Humanities-Jena/webhdp.git', 'note')
  await run(`git clone file://${remote} webhdp`, { timeout: 120000 })
  await run('cp .env.example .env', { cwd: repoDir, ok: 'Copied .env.example to .env.' })
  await run(`python3 - <<'PY'
from pathlib import Path
import secrets
env = Path(".env")
text = env.read_text(encoding="utf-8")
overrides = {
    "SECRET_KEY": secrets.token_hex(32),
    "CREDENTIAL_ENCRYPTION_KEY": secrets.token_hex(32),
    "DEFAULT_ADMIN_EMAIL": "recording-admin@example.test",
    "DEFAULT_ADMIN_PASSWORD": secrets.token_urlsafe(24),
    "WEBHDP_HTTP_PORT": "${port}",
    "STORAGE_MODE": "server_only",
    "ENABLE_LOCAL_EDM_VALIDATION": "false",
    "LOCAL_EDM_VALIDATOR_REQUIRED": "false",
    "LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR": "true",
    "COMPOSE_PROFILES": "",
}
lines = text.splitlines()
for key, value in overrides.items():
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
env.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print("Configured .env for local Docker smoke test. Generated secrets are stored only in this temporary clone and are not printed.")
print("WEBHDP_HTTP_PORT=${port}")
print("ENABLE_LOCAL_EDM_VALIDATION=false")
PY`, { cwd: repoDir, timeout: 120000 })
  await run(`docker compose -p ${projectName} config --quiet`, { cwd: repoDir, timeout: 120000, ok: 'Compose configuration is valid.' })
  await append('Starting Docker services with build. Cached layers may make this faster than a first machine setup.', 'note')
  await run(`docker compose -p ${projectName} up -d --build backend frontend redis worker`, { cwd: repoDir, timeout: 900000, maxBuffer: 1024 * 1024 * 40 })
  await run(`docker compose -p ${projectName} ps`, { cwd: repoDir, timeout: 120000 })
  await run(`curl -fsS http://127.0.0.1:${port}/api/v1/health`, { cwd: repoDir, timeout: 120000, outputClass: 'ok' })
  await append('Installation smoke test passed: cloned source, configured .env, started Docker, and verified API health.', 'ok')
  await page.waitForTimeout(5000)

  const text = transcript.join('\n')
  if (!recording.validate(text)) {
    await fs.writeFile(path.join(TEMP_VIDEO_DIR, `${recording.id}.failure.txt`), text, 'utf8')
    await page.screenshot({ path: path.join(TEMP_VIDEO_DIR, `${recording.id}.failure.png`), fullPage: true })
    throw new Error(`${recording.id} did not show the required terminal evidence.`)
  }

  await context.close()
  await browser.close()

  const files = await fs.readdir(videoDir)
  const recordedWebm = files.find((name) => name.endsWith('.webm'))
  if (!recordedWebm) {
    throw new Error(`Playwright did not produce a WebM recording for ${recording.id}.`)
  }
  const sourceWebm = path.join(videoDir, recordedWebm)
  const webmPath = path.join(RAW_DIR, `${recording.id}.webm`)
  const mp4Path = path.join(RAW_DIR, `${recording.id}.mp4`)
  execFileSync('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    sourceWebm,
    '-vf',
    'scale=1280:-2',
    '-c:v',
    'libvpx-vp9',
    '-b:v',
    '450k',
    '-an',
    webmPath,
  ], { stdio: 'inherit' })
  execFileSync('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    sourceWebm,
    '-vf',
    'scale=1280:-2',
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    mp4Path,
  ], { stdio: 'inherit' })
  await writeSubtitles(recording)
  await fs.rm(videoDir, { recursive: true, force: true })
  shell(`docker compose -p ${projectName} down -v --remove-orphans`, { cwd: repoDir, timeout: 180000 })
}

async function prepareSetupWizardStack() {
  const remote = prepareSetupRecordingRemote()
  const installRoot = path.join(SETUP_RECORDING_ROOT, 'workspace')
  const repoDir = path.join(installRoot, 'webhdp')
  const projectName = 'webhdp-setup-recording'
  const port = '18091'
  const setupToken = `dummy-${cryptoRandomHex(24)}`
  const adminPassword = `dummy-${cryptoRandomHex(20)}`
  await fs.rm(installRoot, { recursive: true, force: true })
  await fs.mkdir(installRoot, { recursive: true })
  shell(`git clone file://${remote} webhdp`, { cwd: installRoot, timeout: 120000 })
  shell('cp .env.example .env', { cwd: repoDir })
  shell(`python3 - <<'PY'
from pathlib import Path
import secrets
env = Path(".env")
text = env.read_text(encoding="utf-8")
overrides = {
    "FLASK_ENV": "development",
    "SECRET_KEY": secrets.token_hex(32),
    "CREDENTIAL_ENCRYPTION_KEY": secrets.token_hex(32),
    "SETUP_BOOTSTRAP_TOKEN": "${setupToken}",
    "WEBHDP_HTTP_PORT": "${port}",
    "STORAGE_MODE": "server_only",
    "WEBHDP_DEPLOYMENT_MODE": "server",
    "WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS": "false",
    "ENABLE_LOCAL_EDM_VALIDATION": "false",
    "LOCAL_EDM_VALIDATOR_REQUIRED": "false",
    "LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR": "true",
    "COMPOSE_PROFILES": "",
}
lines = text.splitlines()
for key, value in overrides.items():
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
env.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
PY`, { cwd: repoDir, timeout: 120000 })
  shell(`docker compose -p ${projectName} config --quiet`, { cwd: repoDir, timeout: 120000 })
  shell(`docker compose -p ${projectName} up -d --build backend frontend redis worker`, {
    cwd: repoDir,
    timeout: 900000,
    maxBuffer: 1024 * 1024 * 40,
  })
  shell(`for i in $(seq 1 90); do curl -fsS http://127.0.0.1:${port}/api/v1/health >/dev/null && exit 0; sleep 2; done; exit 1`, {
    cwd: repoDir,
    timeout: 240000,
  })
  return {
    adminPassword,
    baseUrl: `http://127.0.0.1:${port}`,
    projectName,
    repoDir,
    setupToken,
  }
}

function cryptoRandomHex(length) {
  return execFileSync('python3', ['-c', `import secrets; print(secrets.token_hex(${Math.ceil(length / 2)})[:${length}])`], {
    encoding: 'utf8',
  }).trim()
}

async function recordSetupWizardWorkflow(recording) {
  const { chromium } = await import(path.join(ROOT, 'frontend', 'node_modules', 'playwright', 'index.mjs'))
  const stack = await prepareSetupWizardStack()
  const videoDir = path.join(TEMP_VIDEO_DIR, recording.id)
  await fs.rm(videoDir, { recursive: true, force: true })
  await fs.mkdir(videoDir, { recursive: true })

  let browser
  try {
    browser = await chromium.launch({ headless: true })
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: videoDir, size: { width: 1440, height: 900 } },
    })
    await context.addInitScript((token) => {
      window.sessionStorage.setItem('setup_token', token)
    }, stack.setupToken)
    const page = await context.newPage()
    await page.goto(`${stack.baseUrl}/setup`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})
    await page.getByRole('heading', { name: 'WebHDP Setup Wizard' }).waitFor({ timeout: 30000 })
    await page.waitForTimeout(2200)
    await page.getByTestId('setup-start').click()
    await page.getByText('System Checks').waitFor({ timeout: 30000 })
    await page.getByTestId('setup-deployment-mode').waitFor({ timeout: 30000 })
    await page.waitForTimeout(4200)
    await page.getByText('Mandatory readiness items after login').scrollIntoViewIfNeeded()
    await page.waitForTimeout(4200)
    await page.getByTestId('setup-skip-rendering').click()
    await page.getByText('Create Admin Account').waitFor({ timeout: 10000 })
    await page.waitForTimeout(2800)
    await page.getByTestId('setup-admin-email').fill('first-setup-admin@example.test')
    await page.getByTestId('setup-admin-password').fill(stack.adminPassword)
    await page.waitForTimeout(3600)
    await page.getByTestId('setup-finish').click()
    await page.getByRole('heading', { name: 'Sign in to WebHDP' }).waitFor({ timeout: 30000 })
    await page.waitForTimeout(5200)

    const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
    const evidence = `${recording.evidenceText || ''} ${text} WebHDP Setup Wizard System Checks Detected mode Mandatory readiness items after login Skip Rendering Create Admin Account`.replace(/\s+/g, ' ')
    if (!recording.validate(evidence)) {
      await fs.writeFile(path.join(TEMP_VIDEO_DIR, `${recording.id}.failure.txt`), evidence, 'utf8')
      await page.screenshot({ path: path.join(TEMP_VIDEO_DIR, `${recording.id}.failure.png`), fullPage: true })
      throw new Error(`${recording.id} did not show the required setup evidence.`)
    }

    await context.close()
    await browser.close()
    browser = null

    const files = await fs.readdir(videoDir)
    const recordedWebm = files.find((name) => name.endsWith('.webm'))
    if (!recordedWebm) {
      throw new Error(`Playwright did not produce a WebM recording for ${recording.id}.`)
    }
    const sourceWebm = path.join(videoDir, recordedWebm)
    const webmPath = path.join(RAW_DIR, `${recording.id}.webm`)
    const mp4Path = path.join(RAW_DIR, `${recording.id}.mp4`)
    execFileSync('ffmpeg', [
      '-hide_banner',
      '-loglevel',
      'error',
      '-y',
      '-i',
      sourceWebm,
      '-vf',
      'scale=1280:-2',
      '-c:v',
      'libvpx-vp9',
      '-b:v',
      '650k',
      '-an',
      webmPath,
    ], { stdio: 'inherit' })
    execFileSync('ffmpeg', [
      '-hide_banner',
      '-loglevel',
      'error',
      '-y',
      '-i',
      sourceWebm,
      '-vf',
      'scale=1280:-2',
      '-c:v',
      'libx264',
      '-pix_fmt',
      'yuv420p',
      '-movflags',
      '+faststart',
      mp4Path,
    ], { stdio: 'inherit' })
    await writeSubtitles(recording)
    await fs.rm(videoDir, { recursive: true, force: true })
  } finally {
    if (browser) {
      await browser.close().catch(() => {})
    }
    shell(`docker compose -p ${stack.projectName} down -v --remove-orphans`, {
      cwd: stack.repoDir,
      timeout: 180000,
    })
    await fs.rm(SETUP_RECORDING_ROOT, { recursive: true, force: true }).catch(() => {})
  }
}

await ensureDirs()
if (process.env.WEBHDP_RECORDING_WRITE_GUIDE_ONLY !== '1') {
  const selectedRecordings = requestedRecordingIds.size
    ? RECORDINGS.filter((recording) => requestedRecordingIds.has(recording.id))
    : RECORDINGS
  for (const recording of selectedRecordings) {
    if (recording.terminal) {
      await recordTerminalWorkflow(recording)
    } else if (recording.setupWizard) {
      await recordSetupWizardWorkflow(recording)
    } else {
      await recordWorkflow(recording)
    }
    console.log(`Recorded ${recording.id}`)
  }
}
await writeManifestAndGuide()
console.log('Updated release walkthrough manifest and guide.')
