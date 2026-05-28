import { expect, type Page, test } from '@playwright/test'

import {
  adminUser,
  apiV1,
  fulfillJson,
  loginThroughUi,
  mockAdminVersion,
  mockCurrentUser,
  mockLogin,
  mockSetupStatus,
  mockToolsContext,
} from './support/api'

async function mockAppShell(page: Page) {
  await mockSetupStatus(page, true)
  await mockLogin(page, { user: adminUser })
  await mockCurrentUser(page, adminUser)
  await mockAdminVersion(page)
  await mockToolsContext(page, {
    features: {
      zenodo_account_retrieval: { enabled: true },
      community_migration: { enabled: true },
    },
  })
  await page.route(apiV1('/notifications/client-config'), async (route) => {
    await fulfillJson(route, { success: true, data: { enabled: false } })
  })
  await page.route(apiV1('/notifications/unread-count'), async (route) => {
    await fulfillJson(route, { success: true, data: { count: 0 } })
  })
  await page.route(apiV1('/hpc-link/status'), async (route) => {
    await fulfillJson(route, { success: true, data: { enabled: false } })
  })
}

const coverage = {
  collection_count: 1,
  earliest_created: '2024-03-26T00:00:00Z',
  latest_created: '2026-04-20T12:00:00Z',
  timeline: [
    {
      retrieval_id: 'base-collection',
      retrieval_mode: 'full',
      sync_mode: 'full',
      record_count: 120,
      shard_count: 3,
      earliest_created: '2024-03-26T00:00:00Z',
      latest_created: '2026-04-20T12:00:00Z',
    },
  ],
  gaps: [],
  overlaps: [],
}

test.describe('Firefox Zenodo Inventory coverage', () => {
  test.skip(({ browserName }) => browserName !== 'firefox', 'Dedicated Firefox coverage for Zenodo Inventory')

  test('preflights backfill, shows diagnostics, and runs local detectors', async ({ page }) => {
    await mockAppShell(page)
    await page.route(apiV1('/tools/zenodo-account-retrieval/context'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          credentials: [{ id: 10, name: 'Production key', environment: 'production', source: 'owned', masked_preview: 'sk-...abcd' }],
          active: { production: { id: 10, name: 'Production key', environment: 'production' } },
          recent_collections: coverage.timeline,
          coverage,
          detectors: [
            { id: 'community_migration_candidates', label: 'Community migration candidates' },
            { id: 'objaverse', label: 'Objaverse in description' },
            { id: '3d_model_files', label: '3D model files' },
          ],
          defaults: {
            retrieval_mode: 'full',
            execution_target: 'celery_local',
            initial_window_days: 31,
            request_retries: 2,
            request_timeout_seconds: 30,
            incremental_overlap_hours: 24,
          },
        },
      })
    })
    await page.route(apiV1('/tools/zenodo-account-retrieval/coverage'), async (route) => {
      await fulfillJson(route, { success: true, data: { coverage } })
    })
    await page.route(apiV1('/tools/zenodo-account-retrieval/preflight'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          preflight: {
            queueable: true,
            execution_target: 'celery_local',
            date_window: { start: null, end: '2024-03-26T23:59:59Z' },
            runtime_options: { proxy_policy: 'inherit_worker_environment' },
            coverage: { matching_collection_count: 1 },
            warnings: ['This backfill will create a separate shard tree/collection and may overlap existing inventory.'],
            checks: [{ key: 'credential_access', status: 'pass', label: 'Credential is accessible to the requesting user' }],
          },
        },
      })
    })
    await page.route(apiV1('/tools/zenodo-account-retrieval/jobs'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          jobs: [
            {
              retrieval_id: 'base-collection',
              state: 'SUCCESS',
              status: 'completed',
              environment: 'production',
              progress: { percent: 100, retrieved_records: 120, split_windows: 2, duplicate_records_skipped: 4, eta_confidence: 'low' },
              summary: { retrieved_records: 120, published_records: 100, draft_records: 20, split_windows: 2, duplicate_records_skipped: 4 },
              collection: coverage.timeline[0],
              manifest: { shards: [{ shard_index: 1, session_id: 7, record_count: 40, window: { status: 'published' } }] },
              diagnostics: {
                process_health: { status: 'exited', task_id: 'task-1', pid: 123 },
                heartbeat_age_seconds: 20,
                execution_target: 'celery_local',
                runtime: { proxy_policy: 'inherit_worker_environment', shard_root: '/tmp/webhdp/sessions', script_version: 'test-sha' },
                window: { page: 1 },
                log_tail: ['completed without secrets'],
              },
            },
          ],
        },
      })
    })
    await page.route(apiV1('/tools/zenodo-account-retrieval/jobs/base-collection'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          retrieval_id: 'base-collection',
          state: 'SUCCESS',
          status: 'completed',
          environment: 'production',
          progress: { percent: 100, retrieved_records: 120, split_windows: 2, duplicate_records_skipped: 4, eta_confidence: 'low' },
          summary: { retrieved_records: 120, published_records: 100, draft_records: 20, split_windows: 2, duplicate_records_skipped: 4 },
          collection: coverage.timeline[0],
          manifest: { shards: [{ shard_index: 1, session_id: 7, record_count: 40, window: { status: 'published' } }] },
          diagnostics: {
            process_health: { status: 'exited', task_id: 'task-1', pid: 123 },
            heartbeat_age_seconds: 20,
            execution_target: 'celery_local',
            runtime: { proxy_policy: 'inherit_worker_environment', shard_root: '/tmp/webhdp/sessions', script_version: 'test-sha' },
            window: { page: 1 },
            log_tail: ['completed without secrets'],
          },
        },
      })
    })
    await page.route(apiV1('/tools/zenodo-account-retrieval/jobs/base-collection/diagnostics'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          diagnostics: {
            process_health: { status: 'exited', task_id: 'task-1', pid: 123 },
            heartbeat_age_seconds: 20,
            execution_target: 'celery_local',
            runtime: { proxy_policy: 'inherit_worker_environment', shard_root: '/tmp/webhdp/sessions', script_version: 'test-sha' },
            window: { page: 1 },
            log_tail: ['completed without secrets'],
          },
        },
      })
    })
    await page.route(apiV1('/tools/zenodo-account-retrieval/jobs/base-collection/detectors'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          total: 1,
          candidates: [
            { session_id: 7, local_record_id: 1, title: 'Objaverse model', zenodo_record_id: '501', reason: 'Objaverse metadata; missing target community 3dbigdataspace.' },
          ],
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/tools/zenodo-account-retrieval')

    await expect(page.getByRole('heading', { name: 'Coverage' })).toBeVisible()
    await expect(page.getByText('base-collection').first()).toBeVisible()
    await page.getByRole('button', { name: 'Backfill Before' }).click()
    await page.getByRole('button', { name: 'Preflight' }).click()
    await expect(page.getByText('Ready to queue')).toBeVisible()
    await expect(page.getByText('Credential is accessible to the requesting user')).toBeVisible()

    await expect(page.getByText('Diagnostics', { exact: true })).toBeVisible()
    await expect(page.getByText('ETA uses current effective throughput')).toBeVisible()
    await expect(page.getByText('/tmp/webhdp/sessions')).toBeVisible()

    await page.getByRole('button', { name: 'Run' }).last().click()
    await expect(page.getByText('Objaverse model')).toBeVisible()
    await expect(page.getByText('1 candidates')).toBeVisible()
  })
})
