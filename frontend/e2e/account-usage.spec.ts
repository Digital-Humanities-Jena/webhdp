import { expect, test } from '@playwright/test'
import { apiV1, fulfillJson, mockCurrentUser, mockSetupStatus, seedAuthToken } from './support/api'

test('shows personal usage, quota categories and a recoverable load failure', async ({ page }) => {
  await page.route(/\/api\/v\d\//, route => fulfillJson(route, { data: {} }))
  await mockSetupStatus(page)
  await mockCurrentUser(page)
  await seedAuthToken(page)
  await page.addInitScript(() => localStorage.setItem('webhdp_cookie_notice_v1', 'accepted'))

  let available = false
  await page.route(apiV1('/account/usage'), route => available
    ? fulfillJson(route, { data: {
      uploads: { used_bytes: 1024, limit_bytes: 2048, active: 1, active_limit: 3, request_limit_bytes: 4096, stream_bytes_last_24_hours: 0, stream_limit_bytes: 5120 },
      native_processing: { queued: 2, running: 1, active: 3, active_limit: 3 },
      model_publication: { active: 0, active_limit: 3, accepted_last_24_hours: 3, daily_limit: 10, stored_bytes: 0, storage_limit_bytes: 268435456 },
    } })
    : fulfillJson(route, { error: { code: 'UNAVAILABLE', message: 'Could not load usage.' } }, 503))

  await page.goto('/account/usage')
  await expect(page.getByRole('heading', { name: 'Your usage and limits' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Could not load usage. Refresh to try again.')
  available = true
  await page.getByRole('button', { name: 'Refresh usage' }).click()
  await expect(page.getByRole('article').filter({ hasText: 'Uploads' })).toContainText('1 KiB of 2 KiB')
  await expect(page.getByRole('article').filter({ hasText: 'Pipelines and Playground' })).toContainText('3 of 3')
  await expect(page.getByRole('article').filter({ hasText: '3D tutorial and Sandbox' })).toContainText('3 of 10')
})
