import { expect, test, type Page } from '@playwright/test'
import { adminUser, apiV1, fulfillJson, loginThroughUi, mockCurrentUser, mockLogin, mockSetupStatus } from './support/api'

async function shell(page: Page) {
  await page.route(/\/api\/v[12]\//, route => fulfillJson(route, { success: true, data: {} }))
  await mockSetupStatus(page, true)
  await mockLogin(page, { user: adminUser })
  await mockCurrentUser(page, adminUser)
  await loginThroughUi(page, { email: adminUser.email })
  const notice = page.getByRole('button', { name: 'OK', exact: true })
  if (await notice.isVisible()) await notice.click()
}
for (const width of [375, 1280]) {
  test(`metadata recovery explains partial failure and retries at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await shell(page)
    await page.route(apiV1('/sessions/42/records/1'), route => fulfillJson(route, { data: {
      session: { id: 42, name: 'Museum collection' }, record: { local_record_id: 1, record_title: 'Heritage object', record_status: 'draft' },
      health: {}, lineage: {}, files: [],
    } }))
    let attempts = 0
    await page.route(apiV1('/sessions/42/records/1/lod'), async route => {
      if (route.request().method() === 'POST') attempts++
      await fulfillJson(route, { data: { available: true, formats: {
        edm: attempts ? { success: true, status: 'generated', validation: { valid: true } } : { success: false, status: 'failed', error: 'EDM validation failed. Review the report and retry.', validation: { valid: false, errors: ['Missing rights statement'] } },
        jsonld: { success: true, status: 'generated', validation: { valid: true } },
      } } })
    })
    await page.goto('/sessions/42/records/1')
    await expect(page.getByRole('heading', { name: 'Metadata exports' })).toBeVisible()
    await expect(page.getByText('Needs attention', { exact: true })).toBeVisible()
    await page.getByText('Validation report', { exact: true }).first().click()
    await expect(page.getByText('Missing rights statement', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Retry failed formats' }).click()
    await expect(page.getByRole('button', { name: 'Retry failed formats' })).toHaveCount(0)
    expect(attempts).toBe(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('metadata-recovery.png'), fullPage: true })
  })
}
