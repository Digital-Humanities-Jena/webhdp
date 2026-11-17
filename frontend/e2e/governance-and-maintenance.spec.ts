import { expect, test } from '@playwright/test'

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

async function mockAdminDashboardDependencies(page) {
  await mockAdminVersion(page, {
    version: '2.4.1',
    timestamp: '2026-04-10T11:15:00Z',
  })
  await page.route(apiV1('/admin/submissions'), async (route) => {
    await fulfillJson(route, {
      data: {
        submissions: [
          {
            id: 101,
            user_email: 'user@example.com',
            pipeline_id: 'render',
            status: 'pending',
            created_at: '2026-04-10T09:00:00Z',
          },
        ],
      },
    })
  })
  await page.route(apiV1('/admin/stats'), async (route) => {
    await fulfillJson(route, {
      data: {
        total_users: 3,
      },
    })
  })
  await page.route(apiV1('/admin/users'), async (route) => {
    await fulfillJson(route, {
      data: {
        users: [
          {
            id: adminUser.id,
            email: adminUser.email,
            role: 'admin',
            capabilities: [],
          },
        ],
      },
    })
  })
  await page.route(apiV1('/admin/upload-operations'), async (route) => {
    await fulfillJson(route, {
      data: {
        operations: [],
      },
    })
  })
}

test.describe('Governance and maintenance flows', () => {
  test('shows dataset discovery and duplicate review context for privileged users', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page, { user: adminUser })
    await mockCurrentUser(page, adminUser)
    await page.route(apiV1('/datasets'), async (route) => {
      await fulfillJson(route, {
        data: {
          datasets: [
            {
              dataset_key: 'dataset-alpha',
              source_path_count: 2,
              published_source_path_count: 1,
              duplicate_published_source_path_count: 1,
              session_count: 2,
            },
          ],
        },
      })
    })
    await page.route(apiV1('/datasets/conflict-review'), async (route) => {
      await fulfillJson(route, {
        data: {
          duplicate_group_count: 1,
          datasets: [
            {
              dataset_key: 'dataset-alpha',
              duplicate_group_count: 1,
              duplicate_published_source_path_count: 1,
              affected_users: [
                { user_id: adminUser.id, email: adminUser.email },
              ],
              groups_preview: [
                { normalized_source_file_path: 'models/alpha.glb' },
              ],
            },
          ],
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/datasets')

    await expect(page).toHaveURL(/\/datasets$/)
    await expect(page.getByRole('heading', { name: 'Dataset Integrity Workspace' })).toBeVisible()
    await expect(page.getByText('Discoverable Datasets')).toBeVisible()
    await expect(page.getByText('Admin Conflict Review')).toBeVisible()
    await expect(page.getByRole('cell', { name: 'dataset-alpha' }).first()).toBeVisible()
    await expect(page.getByRole('cell', { name: 'models/alpha.glb' })).toBeVisible()
  })

  test('loads duplicate detail for a specific dataset and exposes authoritative session insight', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page, { user: adminUser })
    await mockCurrentUser(page, adminUser)
    await page.route(apiV1('/datasets'), async (route) => {
      await fulfillJson(route, {
        data: {
          datasets: [
            {
              dataset_key: 'dataset-alpha',
              source_path_count: 2,
              published_source_path_count: 1,
              duplicate_published_source_path_count: 1,
              session_count: 2,
            },
          ],
        },
      })
    })
    await page.route(apiV1('/datasets/dataset-alpha/summary'), async (route) => {
      await fulfillJson(route, {
        data: {
          source_path_count: 2,
          published_source_path_count: 1,
          duplicate_published_source_path_count: 1,
          unpublished_source_path_count: 1,
          authoritative_session_id: 44,
          primary_missing_doi_count: 0,
          primary_missing_glb_link_count: 0,
          draft_breakdown: {
            complete_draft: 1,
            partial_draft: 0,
            prepared_only: 0,
            repair_version_draft: 0,
          },
          environment_breakdown: {
            production: {
              source_path_count: 1,
              published_source_path_count: 1,
            },
            sandbox: {
              source_path_count: 1,
              published_source_path_count: 0,
            },
          },
          sessions: [
            {
              session_id: 44,
              published_records: 1,
              published_source_path_count: 1,
              draft_records: 1,
              prepared_records: 0,
              total_records: 2,
              latest_activity: '2026-04-10T10:00:00Z',
            },
          ],
        },
      })
    })
    await page.route(apiV1('/datasets/dataset-alpha/duplicates'), async (route) => {
      await fulfillJson(route, {
        data: {
          path_filter: '',
          groups: [
            {
              normalized_source_file_path: 'models/alpha.glb',
              record_count: 2,
              published_record_count: 1,
              lineage_count: 1,
              recommended_action: 'Review published duplicate lineage before versioning.',
              affected_users: [
                { user_id: 10, email: 'owner@example.com' },
              ],
              records: [
                {
                  session_id: 44,
                  local_record_id: 3,
                  record_title: 'Alpha model',
                  record_status: 'published',
                  session_owner_email: 'owner@example.com',
                  can_create_version: false,
                },
              ],
            },
          ],
        },
      })
    })
    await page.route(apiV1('/sessions/44/workspace-summary'), async (route) => {
      await fulfillJson(route, {
        data: {
          record_summary: {
            prepared_count: 0,
            draft_count: 1,
            published_count: 1,
          },
          upload_summary: {
            uploadable_item_count: 1,
          },
          versioning_summary: {
            latest_published_record: {
              record_title: 'Alpha model',
            },
          },
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/datasets/dataset-alpha')

    await expect(page.getByText('Authoritative Session Intelligence')).toBeVisible()
    await page.getByRole('button', { name: 'Duplicates' }).click()
    await expect(page).toHaveURL(url =>
      url.pathname === '/datasets/dataset-alpha' &&
      url.searchParams.get('tab') === 'duplicates' &&
      url.searchParams.get('environment') === 'production'
    )
    await expect(page.locator('p').filter({ hasText: 'models/alpha.glb' })).toBeVisible()
    await expect(page.getByText('Alpha model')).toBeVisible()
  })

  test('analyzes and executes session cleanup from the tools workspace', async ({ page }) => {
    const analyzePayloads = []
    const executePayloads = []

    await mockSetupStatus(page, true)
    await mockLogin(page, { user: adminUser })
    await mockCurrentUser(page, adminUser)
    await mockToolsContext(page, {
      features: {
        session_cleanup: { enabled: true, reason: '' },
      },
    })
    await page.route(apiV1('/tools/session-cleanup/analyze'), async (route) => {
      analyzePayloads.push(route.request().postDataJSON())
      await fulfillJson(route, {
        data: {
          candidate_count: 1,
          candidates: [
            {
              session_id: 55,
              status: 'failed',
              age_hours: 120,
              file_count: 4,
              submission_count: 1,
              reasons: ['stale'],
            },
          ],
        },
      })
    })
    await page.route(apiV1('/tools/session-cleanup/execute'), async (route) => {
      executePayloads.push(route.request().postDataJSON())
      await fulfillJson(route, {
        data: {
          removed_count: 1,
          missing_session_ids: [],
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/tools/session-cleanup')
    await page.getByRole('button', { name: 'Analyze' }).click()
    await page.getByRole('checkbox', { name: 'Select all candidates' }).check()
    await page.getByRole('button', { name: 'Delete (1)' }).click()

    await expect(page.getByText('Candidates found:')).toBeVisible()
    await expect(page.getByText('Removed:')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Session Cleanup' })).toBeVisible()
    expect(analyzePayloads).toEqual([
      { older_than_hours: 72 },
      { older_than_hours: 72 },
    ])
    expect(executePayloads).toEqual([
      {
        session_ids: [55],
        delete_directories: true,
      },
    ])
  })

  test('saves the version detection policy from the admin dashboard', async ({ page }) => {
    let savedPayload = null

    await mockSetupStatus(page, true)
    await mockLogin(page, { user: adminUser })
    await mockCurrentUser(page, adminUser)
    await mockAdminDashboardDependencies(page)
    await page.route(apiV1('/admin/version-detection-config'), async (route) => {
      if (route.request().method() === 'POST') {
        savedPayload = route.request().postDataJSON()
        await fulfillJson(route, {
          data: {
            config: {
              preset: 'strict',
              thresholds: {
                version_recommendation_score: 0.95,
                warning_score: 0.45,
              },
              allow_force_create_fresh: true,
              enabled_signals: {
                hash_matching: true,
                metadata_similarity: true,
              },
              hash_collision_policy: {
                enabled: true,
                min_size_bytes: 1048576,
                excluded_extensions: ['.csv', '.json', '.log', '.md', '.text', '.tsv', '.txt', '.xml'],
                exclude_generated_renders: true,
              },
            },
          },
        })
        return
      }

      await fulfillJson(route, {
        data: {
          config: {
            preset: 'balanced',
            thresholds: {
              version_recommendation_score: 0.9,
              warning_score: 0.35,
            },
            allow_force_create_fresh: true,
            enabled_signals: {
              hash_matching: true,
              metadata_similarity: true,
            },
            hash_collision_policy: {
              enabled: true,
              min_size_bytes: 1048576,
              excluded_extensions: ['.csv', '.json', '.log', '.md', '.text', '.tsv', '.txt', '.xml'],
              exclude_generated_renders: true,
            },
          },
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/admin/dashboard')
    await page.getByTestId('policy-preset-select').selectOption('strict')
    await expect(page.getByTestId('policy-dirty-state')).toHaveText('Unsaved changes')
    await page.getByTestId('policy-save').click()

    await expect(page.getByTestId('policy-dirty-state')).toHaveText('Saved configuration loaded')
    await expect(page.getByTestId('policy-threshold-version_recommendation_score')).toHaveText('0.95')
    expect(savedPayload).toEqual({
      preset: 'strict',
      allow_force_create_fresh: true,
      enabled_signals: {
        hash_matching: true,
        metadata_similarity: true,
      },
      hash_collision_policy: {
        enabled: true,
        min_size_bytes: 1048576,
        excluded_extensions: ['.csv', '.json', '.log', '.md', '.text', '.tsv', '.txt', '.xml'],
        exclude_generated_renders: true,
      },
    })
  })
})
