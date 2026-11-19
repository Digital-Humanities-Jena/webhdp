import type { Page, Route } from '@playwright/test'
import { expect } from '@playwright/test'

const API_HOST_PATTERN = '(?:localhost:5000|127\\.0\\.0\\.1:\\d+)'

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function buildApiPattern(path: string) {
  return new RegExp(`https?:\/\/${API_HOST_PATTERN}${escapeRegex(path)}(?:\\?.*)?$`)
}

export function apiV1(path: string) {
  return buildApiPattern(`/api/v1${path}`)
}

export function apiV2(path: string) {
  return buildApiPattern(`/api/v2${path}`)
}

export const defaultUser = {
  id: 1,
  email: 'user@example.com',
  role: 'user',
  capabilities: [],
  groups: [],
  institutions: [],
  memberships: [],
}

export const moderatorUser = {
  ...defaultUser,
  id: 2,
  email: 'moderator@example.com',
  role: 'moderator',
}

export const adminUser = {
  ...defaultUser,
  id: 3,
  email: 'admin@example.com',
  role: 'admin',
}

export async function fulfillJson(route: Route, payload: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
}

export async function seedAuthToken(page: Page, token = 'test-token') {
  await page.addInitScript((nextToken) => {
    window.sessionStorage.setItem('token', nextToken)
  }, token)
}

export async function loginThroughUi(page: Page, {
  email = 'user@example.com',
  password = 'SecretPass123!',
} = {}) {
  await page.goto('/login')
  await page.getByTestId('login-email').fill(email)
  await page.getByTestId('login-password').fill(password)
  await page.getByTestId('login-submit').click()
  await expect(page).toHaveURL(/\/dashboard$/)
}

export async function mockSetupStatus(page: Page, initialized = true) {
  await page.route(apiV1('/setup/status'), async (route) => {
    await fulfillJson(route, {
      data: {
        initialized,
      },
    })
  })
}

export async function mockLogin(page: Page, {
  token = 'test-token',
  user = defaultUser,
} = {}) {
  await page.route(apiV1('/auth/login'), async (route) => {
    await fulfillJson(route, {
      data: {
        access_token: token,
        user,
      },
    })
  })
}

export async function mockCurrentUser(page: Page, user = defaultUser) {
  await page.route(apiV1('/auth/me'), async (route) => {
    await fulfillJson(route, {
      data: {
        user,
      },
    })
  })
}

export async function mockToolsContext(page: Page, {
  features = {},
} = {}) {
  await page.route(apiV1('/tools/context'), async (route) => {
    await fulfillJson(route, {
      data: {
        features,
      },
    })
  })
}

export async function mockAdminVersion(page: Page, {
  version = '1.0.0',
  timestamp = '2026-04-10T10:00:00Z',
} = {}) {
  await page.route(apiV1('/admin/version'), async (route) => {
    await fulfillJson(route, {
      success: true,
      data: {
        version,
        timestamp,
      },
    })
  })
}
