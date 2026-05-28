import { expect, test } from '@playwright/test'

import { apiV1, apiV2, fulfillJson, loginThroughUi, mockCurrentUser, mockLogin, mockSetupStatus } from './support/api'

test.describe('Workflow resume and protected access', () => {
  test('resumes a saved workflow from the dashboard into pipeline selection', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page)
    await page.route(apiV1('/sessions'), async (route) => {
      const requestUrl = new URL(route.request().url())
      if (requestUrl.searchParams.get('scope') !== 'all') {
        await fulfillJson(route, { data: { sessions: [] } })
        return
      }

      await fulfillJson(route, {
        data: {
          sessions: [
            {
              id: 99,
              status: 'scanned',
              file_count: 1,
              created_at: '2026-04-10T10:00:00Z',
              permissions: {
                can_download_hdpc: false,
                can_download_shared_hdpc: false,
              },
              publishing_context: {
                effective_credential_source: 'user',
                default_zenodo_environment: 'sandbox',
              },
              workflow_hint: {
                can_resume_workflow: true,
                resume_route: '/workflow/pipeline',
                resume_label: 'Resume Pipeline Selection',
              },
            },
          ],
        },
      })
    })
    await page.route(apiV1('/sessions/99/workflow-state'), async (route) => {
      if (route.request().method() === 'PUT') {
        await fulfillJson(route, { data: { ok: true } })
        return
      }
      await fulfillJson(route, {
        data: {
          state: {
            phase: 'pipeline',
            current_step: 6,
            is_batch_mode: false,
            selected_file_keys: ['1'],
          },
        },
      })
    })
    await page.route(apiV1('/sessions/99/nodes'), async (route) => {
      await fulfillJson(route, {
        data: {
          nodes: [
            {
              file_id: 1,
              name: 'resume.glb',
              filename: 'resume.glb',
              relative_path: 'resume.glb',
              children: [],
            },
          ],
        },
      })
    })
    await page.route(apiV2('/pipelines'), async (route) => {
      await fulfillJson(route, {
        data: {
          pipelines: [
            {
              identifier: 'render',
              name: 'Render',
              description: 'Render previews',
              version: '2.0.0',
            },
          ],
        },
      })
    })
    await loginThroughUi(page)
    await page.getByRole('link', { name: 'Dashboard' }).click()
    await expect(page).toHaveURL(/\/dashboard$/)
    await page.getByRole('button', { name: 'Resume Pipeline Selection' }).click()

    await expect(page).toHaveURL(/\/workflow\/pipeline\?sessionId=99&resume=workflow$/)
    await expect(page.getByRole('heading', { name: 'Select Pipeline' })).toBeVisible()
  })

  test('redirects non-moderators away from moderator-only routes', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page, {
      user: {
        id: 1,
        email: 'user@example.com',
        role: 'user',
        capabilities: [],
        groups: [],
        institutions: [],
        memberships: [],
      },
    })
    await mockCurrentUser(page, {
      id: 1,
      email: 'user@example.com',
      role: 'user',
      capabilities: [],
      groups: [],
      institutions: [],
      memberships: [],
    })
    await page.route(apiV1('/sessions'), async (route) => {
      await fulfillJson(route, {
        data: {
          sessions: [],
        },
      })
    })

    await loginThroughUi(page)
    await page.goto('/admin/dashboard')

    await expect(page).toHaveURL(/\/dashboard$/)
    await expect(page.getByRole('heading', { name: 'Your Sessions' })).toBeVisible()
  })
})
