import { expect, test } from '@playwright/test'

import {
  adminUser,
  apiV1,
  apiV2,
  fulfillJson,
  loginThroughUi,
  mockAdminVersion,
  mockCurrentUser,
  mockLogin,
  mockSetupStatus,
  mockToolsContext,
  moderatorUser,
} from './support/api'

test.describe('Operator and admin browser surfaces', () => {
  test('lets moderators open Zenodo batch operations with live record groups', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page, { user: moderatorUser })
    await mockCurrentUser(page, moderatorUser)
    await mockToolsContext(page, {
      features: {
        zenodo_batch_operations: { enabled: true, reason: '' },
      },
    })
    await page.route(apiV1('/tools/zenodo-batch-operations/records'), async (route) => {
      const record = {
        session_id: 77,
        local_record_id: 1,
        record_title: 'Demo record',
        record_status: 'draft',
        is_sandbox: true,
        zenodo_record_id: null,
        zenodo_doi: null,
        creators_normalized: ['Jane Example'],
        communities_normalized: ['webhdp'],
        publication_date: '2026-04-01',
        updated_at: '2026-04-02T09:00:00Z',
        operation_eligibility: {
          append_if_missing: { eligible: true, reason: 'Ready' },
          remove_one: { eligible: false, reason: 'Community not present' },
          remove_all: { eligible: true, reason: 'Ready' },
        },
      }

      await fulfillJson(route, {
        data: {
          summary: {
            sessions_with_matches: 1,
            records_filtered: 1,
          },
          groups: [
            {
              session: {
                id: 77,
                status: 'scanned',
                owner_email: 'moderator@example.com',
                owner_user_id: moderatorUser.id,
                created_at: '2026-04-01T08:00:00Z',
              },
              summary: {
                records_returned: 1,
              },
              records: [record],
            },
          ],
          session_warnings: [],
          pagination: {
            page: 1,
            total_pages: 1,
            total_groups: 1,
            has_previous: false,
            has_next: false,
          },
          all_filtered_record_refs: [
            {
              session_id: 77,
              local_record_id: 1,
            },
          ],
          all_filtered_records_preview: [record],
        },
      })
    })
    await page.route(apiV1('/tools/zenodo-batch-operations/history'), async (route) => {
      await fulfillJson(route, {
        data: {
          tasks: [],
        },
      })
    })

    await loginThroughUi(page, { email: moderatorUser.email })
    await page.goto('/tools/zenodo-batch-operations')

    await expect(page).toHaveURL(/\/tools\/zenodo-batch-operations$/)
    await expect(page.getByRole('heading', { name: 'Community membership operations across sessions' })).toBeVisible()
    await expect(page.getByText('Session #77')).toBeVisible()
    await expect(page.getByText('Demo record')).toBeVisible()
  })

  test('shows Playground components when the feature is enabled', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page)
    await mockCurrentUser(page)
    await mockToolsContext(page, {
      features: {
        native_playground: { enabled: true, reason: '' },
      },
    })
    await page.route(apiV2('/components'), async (route) => {
      await fulfillJson(route, {
        data: {
          components: [
            {
              key: 'demo.playground',
              version: '1.0.0',
              source_type: 'native',
              profiles: [{}],
              manifest: {
                metadata: {
                  label: 'Demo Playground',
                  description: 'Standalone demo component',
                  category: 'QA',
                  tags: ['demo'],
                },
              },
              playground_schema: {
                title: 'Demo Playground',
                description: 'Standalone demo component',
                metadata: {
                  category: 'QA',
                  tags: ['demo'],
                },
              },
            },
          ],
        },
      })
    })
    await page.route(apiV1('/sessions'), async (route) => {
      await fulfillJson(route, {
        data: {
          sessions: [
            {
              id: 12,
              created_at: '2026-04-10T09:00:00Z',
              status: 'scanned',
            },
          ],
        },
      })
    })

    await loginThroughUi(page)
    await page.goto('/tools/playground')

    await expect(page).toHaveURL(/\/tools\/playground$/)
    await expect(page.getByRole('heading', { name: 'Playground', exact: true, level: 2 })).toBeVisible()
    await expect(page.getByRole('button', { name: /Demo Playground/i })).toBeVisible()
  })

  test('renders the admin dashboard with system management and policy controls', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page, { user: adminUser })
    await mockCurrentUser(page, adminUser)
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
    await page.route(apiV1('/admin/version-detection-config'), async (route) => {
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
          },
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/admin/dashboard')

    await expect(page).toHaveURL(/\/admin\/dashboard$/)
    await expect(page.getByRole('heading', { name: 'System Management' })).toBeVisible()
    await expect(page.getByTestId('version-detection-policy-card')).toBeVisible()
    await expect(page.getByText('User Management')).toBeVisible()
  })
})
