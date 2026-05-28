import { expect, test } from '@playwright/test'

import { apiV1, fulfillJson, mockLogin, mockSetupStatus } from './support/api'

test.describe('Authentication and setup routing', () => {
  test('redirects unauthenticated users to login when a protected route is opened', async ({ page }) => {
    await mockSetupStatus(page, true)

    await page.goto('/workflow/upload')

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Sign in to WebHDP' })).toBeVisible()
  })

  test('redirects to setup when the system is not initialized and can complete the setup flow', async ({ page }) => {
    const setupToken = 'setup-e2e-token'
    await mockSetupStatus(page, false)
    await page.route(apiV1('/setup/check'), async (route) => {
      expect(route.request().headers()['x-setup-token']).toBe(setupToken)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            renderer_enabled: false,
            blender_reachable: true,
            zenodo_sandbox_status: 'Reachable',
            zenodo_production_status: 'Not Configured',
          },
        }),
      })
    })
    await page.route(apiV1('/setup/create-admin'), async (route) => {
      expect(route.request().headers()['x-setup-token']).toBe(setupToken)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { created: true } }),
      })
    })
    await page.route(apiV1('/setup/complete'), async (route) => {
      expect(route.request().headers()['x-setup-token']).toBe(setupToken)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { completed: true } }),
      })
    })

    await page.goto(`/workflow/upload?setup_token=${setupToken}`)

    await expect(page).toHaveURL(new RegExp(`/setup\\?setup_token=${setupToken}$`))
    await page.getByTestId('setup-start').click()
    await expect(page.getByTestId('setup-skip-rendering')).toBeVisible()
    await page.getByTestId('setup-skip-rendering').click()
    await page.getByTestId('setup-admin-email').fill('admin@example.com')
    await page.getByTestId('setup-admin-password').fill('SecretPass123!')
    await page.getByTestId('setup-finish').click()

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Sign in to WebHDP' })).toBeVisible()
    await expect.poll(async () => {
      return page.evaluate(() => window.sessionStorage.getItem('setup_token'))
    }).toBeNull()
  })

  test('signs in and persists the access token', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page, {
      token: 'token-login-123',
    })

    await page.goto('/login')

    await page.getByTestId('login-email').fill('user@example.com')
    await page.getByTestId('login-password').fill('SecretPass123!')
    await page.getByTestId('login-submit').click()

    await expect(page).toHaveURL(/\/workflow\/upload$/)
    await expect.poll(async () => {
      return page.evaluate(() => window.sessionStorage.getItem('token'))
    }).toBe('token-login-123')
  })

  test('surfaces invalid-credential errors without leaving the login screen', async ({ page }) => {
    await mockSetupStatus(page, true)
    await page.route(apiV1('/auth/login'), async (route) => {
      await fulfillJson(route, {
        error: {
          message: 'Invalid credentials',
        },
      }, 401)
    })

    await page.goto('/login')

    await page.getByTestId('login-email').fill('user@example.com')
    await page.getByTestId('login-password').fill('WrongPass123!')
    await page.getByTestId('login-submit').click()

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByTestId('login-error')).toHaveText(/Invalid credentials/)
    await expect.poll(async () => {
      return page.evaluate(() => window.sessionStorage.getItem('token'))
    }).toBeNull()
  })
})
