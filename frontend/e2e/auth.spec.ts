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

    await expect(page).toHaveURL(/\/dashboard$/)
    await expect.poll(async () => {
      return page.evaluate(() => window.sessionStorage.getItem('token'))
    }).toBe('token-login-123')
  })

  test('recovers failed registration delivery and verifies only after form confirmation', async ({ page }) => {
    const verificationToken = 'a'.repeat(43)
    await mockSetupStatus(page, true)
    await page.route(apiV1('/auth/register'), async (route) => {
      expect(route.request().postDataJSON()).toEqual({ email: 'new-user@example.com' })
      await fulfillJson(route, { error: { message: 'WebHDP could not send the verification email.' } }, 503)
    })
    await page.route(apiV1('/auth/resend-verification'), async (route) => {
      expect(route.request().postDataJSON()).toEqual({ email: 'new-user@example.com' })
      await fulfillJson(route, { data: { accepted: true } }, 202)
    })
    let confirmations = 0
    await page.route(apiV1('/auth/verify-email'), async (route) => {
      expect(route.request().method()).toBe('POST')
      expect(route.request().postDataJSON()).toEqual({ token: verificationToken, password: 'TestPassword123!' })
      confirmations++
      if (confirmations > 1) {
        await fulfillJson(route, { error: { code: 'INVALID_EMAIL_VERIFICATION_LINK', message: 'This verification link has expired or has already been used.' } }, 400)
        return
      }
      await fulfillJson(route, { success: true })
    })

    await page.goto('/register')
    await page.getByLabel('Email address', { exact: true }).fill('new-user@example.com')
    await page.getByRole('button', { name: 'Send verification email' }).click()
    await expect(page.getByRole('alert')).toContainText('could not send')
    await page.getByRole('link', { name: 'Resend verification', exact: true }).click()
    await expect(page.getByLabel('Email address')).toHaveValue('new-user@example.com')
    await page.getByRole('button', { name: 'Resend verification email' }).click()
    await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeFocused()

    const confirm = async () => {
      await page.goto('/verify-email#token=' + verificationToken)
      await expect(page).toHaveURL(/\/verify-email$/)
      await page.getByLabel('Create password').fill('TestPassword123!')
      await page.getByLabel('Confirm password').fill('TestPassword123!')
      await page.getByRole('button', { name: 'Verify email and create account' }).click()
    }
    await expect.poll(() => confirmations).toBe(0)
    await confirm()
    await expect(page.getByRole('heading', { name: 'Email verified' })).toBeVisible()
    await expect.poll(() => confirmations).toBe(1)
    await confirm()
    await expect(page.getByRole('alert')).toContainText('has already been used')
    await expect(page.getByRole('link', { name: 'Request a new link' })).toHaveAttribute('href', '/register?resend=1')
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
