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
} from './support/api'

async function mockAppShell(page: Page) {
  await mockSetupStatus(page, true)
  await mockLogin(page, { user: adminUser })
  await mockCurrentUser(page, adminUser)
  await mockAdminVersion(page)
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

test.describe('Local EDM Validator browser coverage', () => {
  test('shows validator reachability and reported schema versions on EDM configuration', async ({ page }) => {
    await mockAppShell(page)
    await page.route(apiV1('/admin/edm-config'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          config: {
            types: { dataset: 'TEXT' },
            licenses: { 'cc-by': 'http://creativecommons.org/licenses/by/4.0/' },
          },
        },
      })
    })
    let reportsSchemaVersions = true
    let validatorRequired = false
    await page.route(apiV1('/admin/edm-validator/status'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          enabled: !validatorRequired,
          required: validatorRequired,
          active: true,
          url: 'http://local-edm-validator:8080',
          continue_on_error: true,
          health: {
            ok: true,
            status: 'UP',
            response_time_millis: 18,
          },
          info: {
            ok: true,
            summary: {
              version: '1.0.0-local',
              git_commit_short: 'b1ba678',
              build_time: '2026-04-30T13:12:00Z',
              image_tag: 'local-edm-validator:test',
              ...(reportsSchemaVersions ? { edm_schema_version: '20260720', metis_schema_version: '15' } : {}),
            },
          },
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/settings/edm')

    await expect(page.getByRole('heading', { name: 'Local EDM Validator' })).toBeVisible()
    await expect(page.getByText('Enabled', { exact: true })).toBeVisible()
    await expect(page.getByText('http://local-edm-validator:8080')).toBeVisible()
    await expect(page.getByText('Reachable')).toBeVisible()
    await expect(page.getByText('1.0.0-local')).toBeVisible()
    await expect(page.getByText('b1ba678')).toBeVisible()
    await expect(page.getByText('local-edm-validator:test')).toBeVisible()
    await expect(page.getByText('EDM Schema', { exact: true })).toBeVisible()
    await expect(page.getByText('20260720', { exact: true })).toBeVisible()
    await expect(page.getByText('Metis Schema', { exact: true })).toBeVisible()
    await expect(page.getByText('15', { exact: true })).toBeVisible()

    reportsSchemaVersions = false
    validatorRequired = true
    await page.getByRole('button', { name: 'Refresh' }).click()
    await expect(page.getByText('EDM Schema', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Metis Schema', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Required', { exact: true })).toBeVisible()
    await expect(page.getByText('Reachable')).toBeVisible()
  })

  test('renders full local validator steps after template validation', async ({ page }) => {
    await mockAppShell(page)
    await page.route(apiV1('/templates'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          templates: [
            {
              id: 1,
              name: 'Standard EDM Template',
              description: 'Default EDM template',
              standard: 'edm',
              format: 'xml',
              content: '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" />',
              is_default: true,
            },
          ],
        },
      })
    })
    await page.route(apiV1('/templates/preview'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          xml: '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" />',
        },
      })
    })
    await page.route(apiV1('/templates/validate'), async (route) => {
      await fulfillJson(route, {
        success: true,
        data: {
          valid: true,
          errors: [],
          warnings: ['[Local EDM Validator] [Problem Pattern] Very short description (P9)'],
          details: {
            basic: { valid: true },
            business: { valid: true },
            remote: {
              valid: true,
              validator: 'local-edm-validator',
              total_duration_millis: 43,
              validation_results: [
                { step: 'HARVEST_FILE', status: 'PASSED', valid: true, messages: [{ type: 'INFO', message: 'success' }] },
                { step: 'VALIDATE_EXTERNAL', status: 'PASSED', valid: true, messages: [{ type: 'INFO', message: 'success' }] },
                { step: 'TRANSFORM_INTERNAL', status: 'PASSED', valid: true, messages: [{ type: 'INFO', message: 'success' }] },
                { step: 'VALIDATE_INTERNAL', status: 'PASSED', valid: true, messages: [{ type: 'INFO', message: 'success' }] },
              ],
            },
          },
        },
      })
    })

    await loginThroughUi(page, { email: adminUser.email })
    await page.goto('/settings/edm-templates')
    await page.getByRole('button', { name: 'Edit' }).first().click()
    await page.getByRole('button', { name: 'Validate' }).click()

    await expect(page.getByRole('heading', { name: 'Validation Report' })).toBeVisible()
    await expect(page.getByText('Local Validator Steps')).toBeVisible()
    await expect(page.getByText('43 ms')).toBeVisible()
    await expect(page.getByText('Harvest File')).toBeVisible()
    await expect(page.getByText('Validate External')).toBeVisible()
    await expect(page.getByText('Transform Internal')).toBeVisible()
    await expect(page.getByText('Validate Internal')).toBeVisible()
  })
})
