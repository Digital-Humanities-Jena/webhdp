import { expect, test } from '@playwright/test'

import { apiV1, fulfillJson, mockSetupStatus } from './support/api'

test.describe('Firefox onboarding and HPC access request flow', () => {
  test('covers first steps, user request, admin approval, and approved user status', async ({ page, browserName }) => {
    test.skip(browserName !== 'firefox', 'Dedicated Firefox coverage for onboarding and HPC access')

    await mockSetupStatus(page, true)

    const userBase = {
      id: 11,
      email: 'new-user@example.com',
      role: 'user',
      full_name: 'New Researcher',
      affiliation: 'Digital Heritage Lab',
      capabilities: [],
      groups: [],
      institutions: [],
      memberships: [],
      zenodo_credentials_configured: false,
    }
    const adminBase = {
      id: 1,
      email: 'admin@example.com',
      role: 'admin',
      capabilities: [],
      groups: [],
      institutions: [],
      memberships: [],
      zenodo_credentials_configured: false,
    }

    let userOnboardingRequired = true
    let userHasAccess = false
    const onboardingActions: string[] = []
    let latestRequest: null | {
      id: number
      full_name: string
      affiliation: string
      use_cases: string[]
      status: string
      submitted_at: string
      reviewed_at?: string
      review_comment?: string
      user: { id: number; email: string }
    } = null
    let activeUser: Record<string, unknown> | null = null

    const makeUser = () => ({
      ...userBase,
      onboarding_required: userOnboardingRequired,
      onboarding_completed_at: userOnboardingRequired ? null : '2026-05-04T12:30:00Z',
      onboarding_skipped_at: null,
      hpc: {
        has_access: userHasAccess,
        access_source: userHasAccess ? 'explicit' : null,
        latest_request: latestRequest,
        pending_request: latestRequest?.status === 'pending' ? latestRequest : null,
      },
    })

    const makeAdmin = () => ({
      ...adminBase,
      onboarding_required: false,
      onboarding_completed_at: null,
      onboarding_skipped_at: null,
      hpc: {
        has_access: true,
        access_source: 'implicit_admin',
        latest_request: null,
        pending_request: null,
      },
    })

    await page.route(apiV1('/auth/login'), async (route) => {
      const payload = await route.request().postDataJSON()
      activeUser = payload.email === adminBase.email ? makeAdmin() : makeUser()
      await fulfillJson(route, {
        data: {
          access_token: `token-${payload.email}`,
          user: activeUser,
        },
      })
    })

    await page.route(apiV1('/auth/me'), async (route) => {
      await fulfillJson(route, {
        data: {
          user: activeUser || makeUser(),
        },
      })
    })

    await page.route(apiV1('/auth/me/onboarding'), async (route) => {
      onboardingActions.push(route.request().postDataJSON().action)
      userOnboardingRequired = false
      activeUser = makeUser()
      await fulfillJson(route, {
        data: {
          user: activeUser,
        },
      })
    })

    await page.route(apiV1('/auth/me/zenodo-credentials'), async (route) => {
      await fulfillJson(route, { data: { credentials: [], active: {} } })
    })
    await page.route(apiV1('/auth/me/recovery-codes'), async (route) => {
      await fulfillJson(route, { data: { recovery_codes: { configured: false } } })
    })
    await page.route(apiV1('/institutions/workspace-requests'), async (route) => {
      await fulfillJson(route, { data: { requests: [], pagination: { total: 0 } } })
    })

    await page.route(apiV1('/hpc-resource-requests/me'), async (route) => {
      await fulfillJson(route, {
        data: {
          profile_defaults: {
            full_name: userBase.full_name,
            affiliation: userBase.affiliation,
          },
          use_cases: ['3D Models', 'Photographies', 'Historical Data', 'Documents', 'Other'],
          hpc: {
            has_access: userHasAccess,
            access_source: userHasAccess ? 'explicit' : null,
            latest_request: latestRequest,
            pending_request: latestRequest?.status === 'pending' ? latestRequest : null,
          },
        },
      })
    })

    await page.route(apiV1('/hpc-resource-requests'), async (route) => {
      const payload = await route.request().postDataJSON()
      latestRequest = {
        id: 44,
        full_name: payload.full_name,
        affiliation: payload.affiliation,
        use_cases: payload.use_cases,
        status: 'pending',
        submitted_at: '2026-05-04T12:00:00Z',
        user: { id: userBase.id, email: userBase.email },
      }
      activeUser = makeUser()
      await fulfillJson(route, {
        data: {
          request: latestRequest,
          hpc: (activeUser as { hpc?: unknown }).hpc,
        },
      }, 201)
    })

    await page.route(apiV1('/admin/hpc-resource-requests'), async (route) => {
      const status = new URL(route.request().url()).searchParams.get('status')
      const requests = latestRequest && (status === 'all' || latestRequest.status === status) ? [latestRequest] : []
      await fulfillJson(route, {
        data: {
          requests,
        },
      })
    })

    await page.route(apiV1('/admin/hpc-resource-requests/44/approve'), async (route) => {
      const payload = await route.request().postDataJSON()
      userHasAccess = true
      latestRequest = {
        ...latestRequest!,
        status: 'approved',
        reviewed_at: '2026-05-04T12:15:00Z',
        review_comment: payload.comment || '',
      }
      await fulfillJson(route, {
        data: {
          request: latestRequest,
        },
      })
    })

    await page.route(apiV1('/admin/hpc-access-users'), async (route) => {
      await fulfillJson(route, {
        data: {
          users: [
            { ...adminBase, hpc_access_source: 'implicit_admin' },
            ...(userHasAccess ? [{ ...userBase, hpc_access_source: 'explicit' }] : []),
          ],
        },
      })
    })

    await page.route(apiV1('/notifications/client-config'), async (route) => {
      await fulfillJson(route, { data: { poll_interval_seconds: 120 } })
    })
    await page.route(apiV1('/notifications/unread-count'), async (route) => {
      await fulfillJson(route, { data: { unread_count: 0 } })
    })
    await page.route(apiV1('/admin/version'), async (route) => {
      await fulfillJson(route, { success: true, data: { version: 'test', timestamp: '2026-05-04T12:00:00Z' } })
    })
    await page.route(apiV1('/hpc-link/status'), async (route) => {
      await fulfillJson(route, { data: { enabled: false, can_allocate: false } })
    })

    await page.goto('/login')
    await page.getByTestId('login-email').fill(userBase.email)
    await page.getByTestId('login-password').fill('SecretPass123!')
    await page.getByTestId('login-submit').click()

    await expect(page).toHaveURL(/\/onboarding$/)
    await expect(page.getByRole('heading', { name: 'Get started with WebHDP' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Start 3D tutorial' })).toHaveAttribute('href', '/tutorial/3d')
    await page.getByRole('button', { name: 'Take the tour' }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: 'Find your work' })).toBeFocused()
    await page.getByRole('button', { name: 'Next' }).click()
    await expect(page.getByRole('heading', { name: 'Add files and describe your assets' })).toBeFocused()
    await page.getByRole('button', { name: 'Pause tour' }).click()
    await expect(page.getByRole('button', { name: 'Continue the tour' })).toBeFocused()
    await page.reload()
    await expect(page.getByRole('button', { name: 'Continue the tour' })).toBeVisible()
    await page.getByRole('link', { name: 'Open account setup' }).click()
    await expect(page).toHaveURL(/\/account\/setup$/)
    await expect(page.getByRole('heading', { name: 'Set up your account' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Add Sandbox key' })).toHaveAttribute('href', '/account/configuration?zenodo=sandbox#zenodo-keys')
    await page.getByRole('link', { name: 'Add Production key' }).click()
    await expect(page.getByTestId('zenodo-key-environment')).toHaveValue('production')
    await page.getByRole('link', { name: 'Account setup', exact: true }).click()
    await expect(page.getByText('Request access to remote computing for pipelines that need it.', { exact: false })).toBeVisible()

    await page.getByRole('link', { name: 'Open HPC access' }).click()
    await expect(page).toHaveURL(/\/hpc-resources$/)
    await expect(page.getByLabel('Full name')).toHaveValue(userBase.full_name)
    await expect(page.getByLabel('Institutional affiliation')).toHaveValue(userBase.affiliation)
    await page.getByLabel('3D Models').check()
    await page.getByRole('button', { name: 'Submit request' }).click()
    await expect(page.getByText('Latest request: pending')).toBeVisible()

    await page.getByRole('button', { name: 'Logout' }).click()
    await page.getByTestId('login-email').fill(adminBase.email)
    await page.getByTestId('login-password').fill('SecretPass123!')
    await page.getByTestId('login-submit').click()
    await page.getByRole('link', { name: 'HPC Admin' }).click()

    await expect(page).toHaveURL(/\/admin\/hpc-access$/)
    await expect(page.getByText(userBase.email)).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByRole('dialog', { name: userBase.full_name })).toBeVisible()
    await page.getByLabel('Approval note').fill('Approved for Firefox E2E')
    await page.getByRole('button', { name: 'Approve request' }).click()
    await expect(page.getByText('No HPC requests found.')).toBeVisible()
    await page.getByRole('button', { name: 'Accounts' }).click()
    await expect(page.getByText('Admin implicit access')).toBeVisible()
    await expect(page.getByText('Explicit capability')).toBeVisible()
    await expect(page.getByText(userBase.email)).toBeVisible()

    await page.getByRole('button', { name: 'Logout' }).click()
    await page.getByTestId('login-email').fill(userBase.email)
    await page.getByTestId('login-password').fill('SecretPass123!')
    await page.getByTestId('login-submit').click()

    await expect(page).toHaveURL(/\/onboarding$/)
    await page.getByRole('link', { name: 'Open account setup' }).click()
    await expect(page.getByText('HPC access is enabled for this account.')).toBeVisible()
    await page.goBack()
    await page.getByRole('button', { name: 'Continue the tour' }).click()
    await expect(page.getByRole('heading', { name: 'Add files and describe your assets' })).toBeVisible()
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Finish tour' }).click()
    await expect(page.getByRole('button', { name: 'Replay the tour' })).toBeVisible()
    expect(onboardingActions).toEqual(['complete'])
    await page.getByRole('button', { name: 'Continue to upload' }).click()
    await expect(page).toHaveURL(/\/workflow\/upload$/)
    await expect(page.getByRole('link', { name: 'Getting started' })).toBeVisible()
    await page.getByRole('link', { name: 'HPC Access' }).click()
    await expect(page.getByText('Access: Enabled')).toBeVisible()
    await expect(page.getByText('HPC access is enabled')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Submit request' })).toHaveCount(0)
  })
})
